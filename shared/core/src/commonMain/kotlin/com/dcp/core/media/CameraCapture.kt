package com.dcp.core.media

/**
 * A still, as it comes off the camera or out of the gallery.
 *
 * Bytes, not a file path. A path would mean the plaintext image exists
 * somewhere on the filesystem for as long as it takes the app to read it back,
 * and the whole point of [MediaStaging] is that it never does — a photograph of
 * an ID card is compressed and encrypted in memory and only ciphertext is
 * written.
 */
class CapturedImage(
    val bytes: ByteArray,
    val mimeType: String = "image/jpeg",
    /** A human-meaningful name for the file. Never a path. */
    val filename: String = "photo.jpg",
)

/**
 * Refused, cancelled, or the hardware was not there. Cancellation is a normal
 * outcome — an enumerator who opens the camera and changes their mind has not
 * caused an error — so it is [CameraCancelled] rather than a failure.
 */
open class CameraException(message: String, cause: Throwable? = null) : Exception(message, cause)

class CameraCancelled : CameraException("the capture was cancelled")

class CameraUnavailable(message: String) : CameraException(message)

/**
 * Still capture from the device camera (CameraX on Android, AVFoundation on
 * iOS).
 *
 * **The preview is not here.** This class owns the capture pipeline; showing
 * the viewfinder is the UI's job, and lives in `clients/composeApp`. Each
 * platform's actual therefore carries one extra member beyond this declaration
 * — Android hands out a `Preview.SurfaceProvider` sink, iOS an
 * `AVCaptureVideoPreviewLayer` — which the UI attaches to whatever it is
 * drawing. That is the seam: no Android View and no UIKit view is constructed
 * in `shared/core`.
 *
 * Capture returns the sensor's own JPEG. Compression to the project's settings
 * happens afterwards, in [ImageCompressor], because the numbers come from the
 * server and the camera has no business knowing them.
 */
expect class CameraCapture {

    /**
     * Starts the camera. Must be called before [capturePhoto] and paired with
     * [release].
     *
     * @throws CameraUnavailable if there is no camera, or permission is refused
     */
    suspend fun start()

    /**
     * Takes one photograph.
     *
     * @throws CameraCancelled if the user backed out
     * @throws CameraException if the hardware failed
     */
    suspend fun capturePhoto(): CapturedImage

    /** Releases the camera. Safe to call twice, and safe to call unstarted. */
    fun release()
}
