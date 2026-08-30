package com.dcp.core.media

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream

/**
 * Android: BitmapFactory in, Bitmap.compress out, entirely in memory.
 *
 * Two-pass decode. The first pass reads only the header (`inJustDecodeBounds`)
 * to learn the real size; the second decodes with `inSampleSize` so a 12 MP
 * photograph is never fully materialised as a 48 MB bitmap. On the phones this
 * runs on, decoding at full size is not slow — it is an OutOfMemoryError, and
 * the camera is the one place an app reliably meets one.
 *
 * **Orientation is applied to the pixels, not carried as metadata.** A camera
 * sensor is mounted one way round and reports the rotation in EXIF; the JPEG
 * bytes themselves are sideways. `BitmapFactory` does not apply that tag, and
 * re-encoding drops EXIF entirely — so without this every portrait photograph
 * is stored permanently rotated. It was, until an emulator run produced a
 * recovered image lying on its side. Baking the rotation in is the right fix
 * rather than preserving the tag: the file is about to be encrypted and
 * chunked, and every viewer downstream would have to honour a tag that most
 * of them ignore.
 */
actual class ImageCompressor actual constructor() {

    actual fun compressJpeg(input: ByteArray, maxDimension: Int, quality: Int): ByteArray {
        require(quality in 1..100) { "JPEG quality must be 1..100, got $quality" }

        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(input, 0, input.size, bounds)
        if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
            throw ImageDecodeException("could not decode ${input.size} bytes as an image")
        }

        val (width, height) = scaledDimensions(bounds.outWidth, bounds.outHeight, maxDimension)

        // inSampleSize only halves, so this gets within 2x of the target and
        // the exact scale is done below. Decoding at 1/8 and scaling up would
        // be worse than decoding at 1/4 and scaling down.
        val options = BitmapFactory.Options().apply {
            inSampleSize = generateSequence(1) { it * 2 }
                .takeWhile { bounds.outWidth / it >= width && bounds.outHeight / it >= height }
                .last()
        }
        val decoded = BitmapFactory.decodeByteArray(input, 0, input.size, options)
            ?: throw ImageDecodeException("BitmapFactory returned no bitmap for ${input.size} bytes")

        val scaled = if (decoded.width == width && decoded.height == height) {
            decoded
        } else {
            Bitmap.createScaledBitmap(decoded, width, height, true).also {
                if (it !== decoded) decoded.recycle()
            }
        }

        val upright = applyExifRotation(scaled, input)

        val out = ByteArrayOutputStream()
        try {
            upright.compress(Bitmap.CompressFormat.JPEG, quality, out)
        } finally {
            upright.recycle()
        }
        return out.toByteArray()
    }

    /**
     * Rotates and flips the bitmap to match the EXIF orientation of the ORIGINAL
     * bytes. Returns the input untouched when there is nothing to do.
     *
     * Applied after scaling: the scale is fit-inside a square bound, so a
     * quarter turn cannot push the longest edge past the project's limit.
     */
    private fun applyExifRotation(bitmap: Bitmap, original: ByteArray): Bitmap {
        val orientation = try {
            ExifInterface(ByteArrayInputStream(original))
                .getAttributeInt(ExifInterface.TAG_ORIENTATION, ExifInterface.ORIENTATION_NORMAL)
        } catch (_: Exception) {
            // An image with no readable EXIF is not an error — a PNG, or a
            // camera that reports nothing. Treat it as already upright.
            ExifInterface.ORIENTATION_NORMAL
        }

        val matrix = Matrix()
        when (orientation) {
            ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
            ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
            ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(270f)
            ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.postScale(-1f, 1f)
            ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.postScale(1f, -1f)
            ExifInterface.ORIENTATION_TRANSPOSE -> { matrix.postRotate(90f); matrix.postScale(-1f, 1f) }
            ExifInterface.ORIENTATION_TRANSVERSE -> { matrix.postRotate(270f); matrix.postScale(-1f, 1f) }
            else -> return bitmap
        }
        return Bitmap.createBitmap(bitmap, 0, 0, bitmap.width, bitmap.height, matrix, true)
            .also { if (it !== bitmap) bitmap.recycle() }
    }
}
