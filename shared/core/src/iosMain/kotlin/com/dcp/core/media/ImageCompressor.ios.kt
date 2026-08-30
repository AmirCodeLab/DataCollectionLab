package com.dcp.core.media

import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.allocArrayOf
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.useContents
import kotlinx.cinterop.usePinned
import platform.CoreGraphics.CGRectMake
import platform.CoreGraphics.CGSizeMake
import platform.Foundation.NSData
import platform.Foundation.create
import platform.UIKit.UIGraphicsBeginImageContextWithOptions
import platform.UIKit.UIGraphicsEndImageContext
import platform.UIKit.UIGraphicsGetImageFromCurrentImageContext
import platform.UIKit.UIImage
import platform.UIKit.UIImageJPEGRepresentation
import platform.posix.memcpy

/**
 * iOS: UIImage in, UIImageJPEGRepresentation out, entirely in memory.
 *
 * UIKit here rather than Core Image or vImage because this is a resize and a
 * re-encode, not image processing, and the UIKit path is the one that handles
 * EXIF orientation for free — a photograph taken in portrait and re-encoded
 * without it comes out rotated, which enumerators notice immediately and
 * nothing downstream can fix.
 */
@OptIn(ExperimentalForeignApi::class)
actual class ImageCompressor actual constructor() {

    actual fun compressJpeg(input: ByteArray, maxDimension: Int, quality: Int): ByteArray {
        require(quality in 1..100) { "JPEG quality must be 1..100, got $quality" }

        val data = memScoped {
            NSData.create(bytes = allocArrayOf(input), length = input.size.toULong())
        }
        val image = UIImage.imageWithData(data)
            ?: throw ImageDecodeException("could not decode ${input.size} bytes as an image")

        val width = image.size.useContents { width }.toInt()
        val height = image.size.useContents { height }.toInt()
        if (width <= 0 || height <= 0) {
            throw ImageDecodeException("decoded image has no size")
        }
        val (targetWidth, targetHeight) = scaledDimensions(width, height, maxDimension)

        // scale = 1.0: draw at exactly the pixel size asked for, not at the
        // screen's scale factor. Without it a 1600px target produces a 4800px
        // image on a 3x device, which is precisely the bandwidth the project
        // setting exists to control.
        UIGraphicsBeginImageContextWithOptions(
            CGSizeMake(targetWidth.toDouble(), targetHeight.toDouble()),
            opaque = true,
            scale = 1.0,
        )
        image.drawInRect(CGRectMake(0.0, 0.0, targetWidth.toDouble(), targetHeight.toDouble()))
        val scaled = UIGraphicsGetImageFromCurrentImageContext()
        UIGraphicsEndImageContext()

        val jpeg = scaled?.let { UIImageJPEGRepresentation(it, quality / 100.0) }
            ?: throw ImageDecodeException("could not re-encode the scaled image as JPEG")

        val length = jpeg.length.toInt()
        val bytes = ByteArray(length)
        if (length > 0) {
            bytes.usePinned { memcpy(it.addressOf(0), jpeg.bytes, jpeg.length) }
        }
        return bytes
    }
}
