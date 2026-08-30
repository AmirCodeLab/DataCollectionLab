package com.dcp.core.media

import java.awt.image.BufferedImage
import java.io.ByteArrayOutputStream
import javax.imageio.ImageIO

/** Desktop: ImageIO, in memory (no disk cache — see [ImageCompressor]). */
actual class ImageEncoder actual constructor() {

    init {
        ImageIO.setUseCache(false)
    }

    actual fun encodePng(pixels: ByteArray, width: Int, height: Int): ByteArray {
        requirePixelBuffer(pixels, width, height)
        val image = BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB)
        var i = 0
        for (y in 0 until height) {
            for (x in 0 until width) {
                val r = pixels[i].toInt() and 0xFF
                val g = pixels[i + 1].toInt() and 0xFF
                val b = pixels[i + 2].toInt() and 0xFF
                val a = pixels[i + 3].toInt() and 0xFF
                image.setRGB(x, y, (a shl 24) or (r shl 16) or (g shl 8) or b)
                i += 4
            }
        }
        val out = ByteArrayOutputStream()
        ImageIO.write(image, "png", out)
        return out.toByteArray()
    }
}
