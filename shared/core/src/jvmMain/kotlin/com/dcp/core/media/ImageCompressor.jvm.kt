package com.dcp.core.media

import java.awt.RenderingHints
import java.awt.image.BufferedImage
import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import javax.imageio.IIOImage
import javax.imageio.ImageIO
import javax.imageio.ImageWriteParam

/**
 * Desktop: ImageIO, entirely in memory.
 *
 * ImageIO is told not to use a disk cache — by default it will spill a
 * temporary file for large images, which would put the full-resolution
 * plaintext photograph on the disk this design exists to keep it off.
 */
actual class ImageCompressor actual constructor() {

    init {
        ImageIO.setUseCache(false)
    }

    actual fun compressJpeg(input: ByteArray, maxDimension: Int, quality: Int): ByteArray {
        require(quality in 1..100) { "JPEG quality must be 1..100, got $quality" }
        val source = try {
            ImageIO.read(ByteArrayInputStream(input))
        } catch (cause: Exception) {
            throw ImageDecodeException("could not decode ${input.size} bytes as an image", cause)
        } ?: throw ImageDecodeException("no ImageIO reader for these ${input.size} bytes")

        val (width, height) = scaledDimensions(source.width, source.height, maxDimension)

        // TYPE_INT_RGB, not ARGB: JPEG has no alpha channel, and writing an
        // image that has one produces a file most decoders render with the
        // colours inverted.
        val scaled = BufferedImage(width, height, BufferedImage.TYPE_INT_RGB)
        val g = scaled.createGraphics()
        try {
            g.setRenderingHint(
                RenderingHints.KEY_INTERPOLATION, RenderingHints.VALUE_INTERPOLATION_BILINEAR,
            )
            g.setRenderingHint(RenderingHints.KEY_RENDERING, RenderingHints.VALUE_RENDER_QUALITY)
            g.drawImage(source, 0, 0, width, height, null)
        } finally {
            g.dispose()
        }

        val writer = ImageIO.getImageWritersByFormatName("jpeg").next()
        val out = ByteArrayOutputStream()
        try {
            ImageIO.createImageOutputStream(out).use { stream ->
                writer.output = stream
                val params = writer.defaultWriteParam.apply {
                    compressionMode = ImageWriteParam.MODE_EXPLICIT
                    compressionQuality = quality / 100f
                }
                writer.write(null, IIOImage(scaled, null, null), params)
            }
        } finally {
            writer.dispose()
        }
        return out.toByteArray()
    }
}
