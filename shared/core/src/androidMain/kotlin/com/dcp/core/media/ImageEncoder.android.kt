package com.dcp.core.media

import android.graphics.Bitmap
import java.io.ByteArrayOutputStream

/** Android: Bitmap.compress(PNG), in memory. */
actual class ImageEncoder actual constructor() {

    actual fun encodePng(pixels: ByteArray, width: Int, height: Int): ByteArray {
        requirePixelBuffer(pixels, width, height)
        // Bitmap wants ARGB ints; the buffer is RGBA bytes.
        val argb = IntArray(width * height)
        var i = 0
        for (p in argb.indices) {
            val r = pixels[i].toInt() and 0xFF
            val g = pixels[i + 1].toInt() and 0xFF
            val b = pixels[i + 2].toInt() and 0xFF
            val a = pixels[i + 3].toInt() and 0xFF
            argb[p] = (a shl 24) or (r shl 16) or (g shl 8) or b
            i += 4
        }
        val bitmap = Bitmap.createBitmap(argb, width, height, Bitmap.Config.ARGB_8888)
        val out = ByteArrayOutputStream()
        try {
            // The quality argument is ignored for PNG: it is lossless, which is
            // the point — see the expect declaration.
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, out)
        } finally {
            bitmap.recycle()
        }
        return out.toByteArray()
    }
}
