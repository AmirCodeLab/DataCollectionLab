package com.dcp.core.media

/**
 * Scales and re-encodes a captured image before it is staged
 * (project.media_image_* — see [MediaPolicy]).
 *
 * Compression is a project decision, not a device one, because it trades
 * evidentiary quality against bandwidth and only the study knows which side it
 * is on: a housing-condition survey over 2G wants 1024px at quality 60; a
 * clinical wound-progression study wants the sensor's own pixels. So the
 * numbers come from the server and are cached locally, and this class applies
 * them rather than deciding them.
 *
 * It runs **before** encryption and staging, entirely in memory, and that
 * ordering matters: a compressor that spilled a full-resolution temporary file
 * to disk would put the plaintext photograph on the device for exactly as long
 * as it takes somebody to pick the phone up, which is the exposure the whole
 * at-rest design exists to close. Every actual must decode, scale and encode
 * without touching the filesystem.
 *
 * Scaling is fit-inside, never crop and never upscale: an image already smaller
 * than the limit is re-encoded at the project's quality and no more. Cropping
 * would silently discard part of the evidence.
 */
expect class ImageCompressor() {

    /**
     * Returns JPEG bytes no larger than [maxDimension] on the longest edge.
     *
     * @param quality 1–100, JPEG quality
     * @throws ImageDecodeException if the bytes are not an image this platform
     *   can decode. Never returns the input unchanged as a fallback — a caller
     *   that asked for 1024px and silently got 4000px would blow a project's
     *   bandwidth budget without anything saying so.
     */
    fun compressJpeg(input: ByteArray, maxDimension: Int, quality: Int): ByteArray
}

class ImageDecodeException(message: String, cause: Throwable? = null) : Exception(message, cause)

/**
 * The scaled size for an image, fit inside a square of [maxDimension].
 *
 * Shared rather than reimplemented per platform: three implementations of one
 * rounding rule is three chances for Android and iOS to produce images a
 * different size from the same photograph, and the first symptom would be a
 * cross-platform test nobody can reproduce.
 */
fun scaledDimensions(width: Int, height: Int, maxDimension: Int): Pair<Int, Int> {
    require(width > 0 && height > 0) { "image has no size: ${width}x$height" }
    val longest = maxOf(width, height)
    if (longest <= maxDimension) return width to height
    val scale = maxDimension.toDouble() / longest
    // At least one pixel each way: a 4000x3 panorama scaled to 1600 would
    // otherwise round its height to zero and fail to encode.
    return maxOf(1, (width * scale).toInt()) to maxOf(1, (height * scale).toInt())
}
