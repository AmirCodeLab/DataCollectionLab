package com.dcp.core.media

/**
 * Encodes raw pixels as PNG. What a signature becomes.
 *
 * A signature is drawn on a Compose canvas as strokes, rasterised there into an
 * `ImageBitmap`, and read back as pixels — all in common code. Only the final
 * encode needs a platform, because there is no PNG encoder in common Kotlin and
 * a hand-rolled one would mean hand-rolling DEFLATE.
 *
 * PNG rather than JPEG, and this is the one place in the media path where that
 * is the right choice: a signature is a few dark strokes on white, which JPEG
 * renders as a grey haze of ringing artefacts around every line, and which PNG
 * compresses to a fraction of the size losslessly. It is also evidence someone
 * may later be asked to stand behind, and lossy compression of evidence is a
 * conversation worth never having.
 */
expect class ImageEncoder() {

    /**
     * @param pixels RGBA8888, row-major, `width * height * 4` bytes
     * @throws ImageDecodeException if the buffer is not that size
     */
    fun encodePng(pixels: ByteArray, width: Int, height: Int): ByteArray
}

/** Checks the buffer is the size the dimensions claim. Shared by every actual. */
internal fun requirePixelBuffer(pixels: ByteArray, width: Int, height: Int) {
    val expected = width.toLong() * height.toLong() * 4L
    if (width <= 0 || height <= 0 || pixels.size.toLong() != expected) {
        throw ImageDecodeException(
            "expected $expected bytes of RGBA for ${width}x$height, got ${pixels.size}",
        )
    }
}
