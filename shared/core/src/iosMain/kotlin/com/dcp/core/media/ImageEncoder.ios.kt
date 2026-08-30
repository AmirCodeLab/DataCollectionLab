package com.dcp.core.media

import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.usePinned
import platform.CoreGraphics.CGBitmapContextCreate
import platform.CoreGraphics.CGBitmapContextCreateImage
import platform.CoreGraphics.CGColorSpaceCreateDeviceRGB
import platform.CoreGraphics.CGImageAlphaInfo
import platform.UIKit.UIImage
import platform.UIKit.UIImagePNGRepresentation
import platform.posix.memcpy

/** iOS: a CoreGraphics bitmap context, then UIImagePNGRepresentation. */
@OptIn(ExperimentalForeignApi::class)
actual class ImageEncoder actual constructor() {

    actual fun encodePng(pixels: ByteArray, width: Int, height: Int): ByteArray {
        requirePixelBuffer(pixels, width, height)

        val copy = pixels.copyOf()
        return copy.usePinned { pinned ->
            val colorSpace = CGColorSpaceCreateDeviceRGB()
            // kCGImageAlphaPremultipliedLast == RGBA with premultiplied alpha.
            // The signature canvas draws opaque strokes on a transparent ground,
            // where premultiplied and straight alpha agree, so no conversion is
            // needed — a canvas with translucent strokes would need one.
            val context = CGBitmapContextCreate(
                data = pinned.addressOf(0),
                width = width.toULong(),
                height = height.toULong(),
                bitsPerComponent = 8u,
                bytesPerRow = (width * 4).toULong(),
                space = colorSpace,
                bitmapInfo = CGImageAlphaInfo.kCGImageAlphaPremultipliedLast.value,
            ) ?: throw ImageDecodeException("could not create a ${width}x$height bitmap context")

            val cgImage = CGBitmapContextCreateImage(context)
                ?: throw ImageDecodeException("could not render the bitmap context")
            val png = UIImagePNGRepresentation(UIImage.imageWithCGImage(cgImage))
                ?: throw ImageDecodeException("could not encode the image as PNG")

            val length = png.length.toInt()
            ByteArray(length).also { out ->
                if (length > 0) out.usePinned { memcpy(it.addressOf(0), png.bytes, png.length) }
            }
        }
    }
}
