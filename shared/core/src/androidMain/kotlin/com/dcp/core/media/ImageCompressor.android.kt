package com.dcp.core.media

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import java.io.ByteArrayOutputStream

/**
 * Android: BitmapFactory in, Bitmap.compress out, entirely in memory.
 *
 * Two-pass decode. The first pass reads only the header (`inJustDecodeBounds`)
 * to learn the real size; the second decodes with `inSampleSize` so a 12 MP
 * photograph is never fully materialised as a 48 MB bitmap. On the phones this
 * runs on, decoding at full size is not slow — it is an OutOfMemoryError, and
 * the camera is the one place an app reliably meets one.
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

        val out = ByteArrayOutputStream()
        try {
            scaled.compress(Bitmap.CompressFormat.JPEG, quality, out)
        } finally {
            scaled.recycle()
        }
        return out.toByteArray()
    }
}
