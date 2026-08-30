package com.dcp.core.media

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import java.awt.Color
import java.awt.image.BufferedImage
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.util.Properties
import javax.imageio.ImageIO
import kotlin.test.Test
import kotlin.test.assertContentEquals
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking

/**
 * The two rules that decide whether a captured answer is worth keeping:
 * how much of a photograph is uploaded, and how bad a position fix may be.
 */
class CaptureRulesTest {

    // -- compression -------------------------------------------------------

    private fun jpeg(width: Int, height: Int): ByteArray {
        val image = BufferedImage(width, height, BufferedImage.TYPE_INT_RGB)
        val g = image.createGraphics()
        // Not a flat fill: a uniform image compresses to almost nothing at any
        // quality, which would make the quality assertions below vacuous.
        for (x in 0 until width) for (y in 0 until height) {
            image.setRGB(x, y, Color((x * 7) % 256, (y * 11) % 256, ((x + y) * 3) % 256).rgb)
        }
        g.dispose()
        val out = ByteArrayOutputStream()
        ImageIO.write(image, "jpeg", out)
        return out.toByteArray()
    }

    private fun sizeOf(bytes: ByteArray): Pair<Int, Int> =
        ImageIO.read(ByteArrayInputStream(bytes)).let { it.width to it.height }

    @Test
    fun `scaling fits inside the limit and keeps the aspect ratio`() {
        assertEquals(1600 to 1200, scaledDimensions(4000, 3000, 1600))
        assertEquals(1200 to 1600, scaledDimensions(3000, 4000, 1600))
        // Already smaller: untouched, never upscaled. Inventing pixels would
        // make a low-resolution photograph look like a better one.
        assertEquals(800 to 600, scaledDimensions(800, 600, 1600))
        assertEquals(1600 to 1200, scaledDimensions(1600, 1200, 1600))
        // A 4000x3 panorama must not round its height to zero and fail to
        // encode; one pixel each way is the floor.
        assertEquals(1600 to 1, scaledDimensions(4000, 3, 1600))
    }

    @Test
    fun `compression applies the project's dimension limit`() {
        val compressor = ImageCompressor()
        val original = jpeg(2400, 1800)

        assertEquals(1600 to 1200, sizeOf(compressor.compressJpeg(original, 1600, 80)))
        assertEquals(1024 to 768, sizeOf(compressor.compressJpeg(original, 1024, 80)))
        // Below the limit: re-encoded at the project's quality, not resized.
        assertEquals(2400 to 1800, sizeOf(compressor.compressJpeg(original, 4000, 80)))
    }

    @Test
    fun `a lower quality setting produces a smaller file`() {
        val compressor = ImageCompressor()
        val original = jpeg(1200, 900)
        val high = compressor.compressJpeg(original, 1200, 90).size
        val low = compressor.compressJpeg(original, 1200, 40).size
        assertTrue(low < high, "quality 40 ($low bytes) was not smaller than 90 ($high bytes)")
    }

    @Test
    fun `bytes that are not an image are refused rather than passed through`() {
        // Returning the input unchanged would be the tempting fallback, and a
        // caller that asked for 1024px and silently got a 4000px original would
        // blow a project's bandwidth budget with nothing saying so.
        assertFailsWith<ImageDecodeException> {
            ImageCompressor().compressJpeg("not an image".encodeToByteArray(), 1600, 80)
        }
    }

    // -- GPS ---------------------------------------------------------------

    private fun store(policy: MediaPolicy? = null): MediaStore {
        val driver = JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)
        return MediaStore(DcpDatabase(driver)).also { s -> policy?.let(s::putPolicy) }
    }

    /** A provider that reports whatever the test tells it to. */
    private class FakeProvider(
        private val fix: GeoFix?,
        private val unavailable: String? = null,
    ) : LocationSource {
        override fun availability() = unavailable
        override suspend fun awaitFix(timeoutMs: Long, targetAccuracyM: Double) = fix
    }

    @Test
    fun `a fix inside the project threshold is accepted`() = runBlocking {
        val store = store(MediaPolicy(gpsMaxAccuracyM = 50))
        val fix = GeoFix(lat = -1.28, lon = 36.81, accuracyM = 12.0)

        val outcome = GeoCapture(FakeProvider(fix), store).capture()

        assertIs<GeoCaptureOutcome.Accepted>(outcome)
        assertEquals(fix, outcome.fix)
        assertEquals(
            com.dcp.form.FormValue.GeoPoint(-1.28, 36.81, null, 12.0),
            outcome.fix.toFormValue(),
            "the accuracy travels with the point, so a later threshold change " +
                "cannot rewrite how good this reading actually was",
        )
    }

    @Test
    fun `a fix worse than the threshold is refused, and handed back to be shown`() =
        runBlocking {
            val store = store(MediaPolicy(gpsMaxAccuracyM = 50))
            // A phone indoors. This is not a rare failure — it is what a GPS
            // does under a tin roof, and it looks exactly like a good fix.
            val fix = GeoFix(lat = -1.28, lon = 36.81, accuracyM = 2100.0)

            val outcome = GeoCapture(FakeProvider(fix), store).capture()

            val refused = assertIs<GeoCaptureOutcome.TooImprecise>(outcome)
            assertEquals(50, refused.requiredM)
            // Handed back rather than dropped: the enumerator has to be told
            // "240 m, need 50 m — step outside", not shown a silent failure.
            assertEquals(2100.0, refused.fix.accuracyM)
        }

    @Test
    fun `a fix with no reported accuracy is refused, not trusted`() = runBlocking {
        val store = store(MediaPolicy(gpsMaxAccuracyM = 50))
        // Null accuracy is "I do not know how good this is", which is not the
        // same as "perfect". Treating it as perfect is how a fix from another
        // village ends up on a submission.
        val outcome = GeoCapture(
            FakeProvider(GeoFix(lat = 0.0, lon = 0.0, accuracyM = null)), store,
        ).capture()

        assertIs<GeoCaptureOutcome.TooImprecise>(outcome)
        Unit
    }

    @Test
    fun `no fix at all is distinguishable from a bad one`() = runBlocking {
        // Both mean "wait", and neither means "record this" — but they need
        // different words on the screen.
        val outcome = GeoCapture(FakeProvider(null), store()).capture()
        assertIs<GeoCaptureOutcome.TimedOut>(outcome)

        val denied = GeoCapture(
            FakeProvider(null, unavailable = "permission denied"), store(),
        ).capture()
        assertIs<GeoCaptureOutcome.Unavailable>(denied)
        assertEquals("permission denied", denied.reason)
    }

    // -- signatures --------------------------------------------------------

    @Test
    fun `a signature encodes to a PNG that decodes back to the same pixels`() {
        // A signature is a few dark strokes on white. PNG, not JPEG: JPEG
        // renders exactly that as a grey haze of ringing artefacts around every
        // line, and this is evidence someone may be asked to stand behind.
        val width = 40
        val height = 20
        val pixels = ByteArray(width * height * 4)
        for (i in pixels.indices step 4) {
            pixels[i] = 0xFF.toByte()      // white ground
            pixels[i + 1] = 0xFF.toByte()
            pixels[i + 2] = 0xFF.toByte()
            pixels[i + 3] = 0xFF.toByte()
        }
        // One black pixel run, the "stroke".
        for (x in 5 until 35) {
            val i = ((10 * width) + x) * 4
            pixels[i] = 0; pixels[i + 1] = 0; pixels[i + 2] = 0
        }

        val png = ImageEncoder().encodePng(pixels, width, height)

        assertTrue(png.size > 8, "no PNG was produced")
        // The 8-byte PNG signature. Checking the magic rather than the length
        // means a JPEG smuggled in here would fail.
        assertContentEquals(
            byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A),
            png.copyOfRange(0, 8),
        )

        val decoded = ImageIO.read(ByteArrayInputStream(png))
        assertEquals(width, decoded.width)
        assertEquals(height, decoded.height)
        // Lossless: the stroke is still black and the ground is still white.
        assertEquals(0x000000, decoded.getRGB(20, 10) and 0xFFFFFF)
        assertEquals(0xFFFFFF, decoded.getRGB(20, 5) and 0xFFFFFF)
    }

    @Test
    fun `a pixel buffer that does not match its dimensions is refused`() {
        assertFailsWith<ImageDecodeException> {
            ImageEncoder().encodePng(ByteArray(10), 40, 20)
        }
    }

    @Test
    fun `the default threshold matches the server's own column default`() {
        // A device that has never synced still has to capture, and it captures
        // under these. Drift here would mean the first submission from a new
        // device is held to a different standard from every one after it.
        assertEquals(50, store().policy().gpsMaxAccuracyM)
        assertEquals(1600, store().policy().imageMaxDimension)
        assertEquals(80, store().policy().imageQuality)
    }
}
