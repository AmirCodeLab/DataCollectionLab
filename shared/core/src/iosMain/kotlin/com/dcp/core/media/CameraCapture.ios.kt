package com.dcp.core.media

import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.usePinned
import kotlinx.coroutines.suspendCancellableCoroutine
import platform.AVFoundation.AVAuthorizationStatusAuthorized
import platform.AVFoundation.AVCaptureDevice
import platform.AVFoundation.AVCaptureDeviceInput
import platform.AVFoundation.AVCapturePhotoCaptureDelegateProtocol
import platform.AVFoundation.AVCapturePhotoOutput
import platform.AVFoundation.AVCapturePhotoSettings
import platform.AVFoundation.AVCaptureSession
import platform.AVFoundation.AVCaptureSessionPresetPhoto
import platform.AVFoundation.AVCaptureVideoPreviewLayer
import platform.AVFoundation.AVMediaTypeVideo
import platform.AVFoundation.authorizationStatusForMediaType
import platform.AVFoundation.fileDataRepresentation
import platform.AVFoundation.requestAccessForMediaType
import platform.Foundation.NSError
import platform.darwin.NSObject
import platform.posix.memcpy

/**
 * iOS: AVFoundation.
 *
 * The preview layer is handed out rather than attached here: showing the
 * viewfinder is the UI's job and lives in `clients/composeApp`, which puts
 * [previewLayer] into a `UIKitView`. No UIKit view is constructed in
 * `shared/core`.
 */
@OptIn(ExperimentalForeignApi::class)
actual class CameraCapture {

    private val session = AVCaptureSession()
    private val output = AVCapturePhotoOutput()

    /**
     * The layer the UI puts on screen. Created eagerly and tied to the session,
     * so the UI can lay it out before [start] has finished — a viewfinder that
     * appears a beat after the screen does reads as a stutter.
     */
    val previewLayer: AVCaptureVideoPreviewLayer = AVCaptureVideoPreviewLayer(session = session)

    // Held as a field: AVFoundation keeps only a weak reference to a capture
    // delegate, and a delegate that is collected mid-capture produces no
    // callback at all — the coroutine would hang rather than fail.
    private var delegate: PhotoDelegate? = null

    actual suspend fun start() {
        if (!requestAccess()) {
            throw CameraUnavailable("camera permission has not been granted")
        }

        val device = AVCaptureDevice.defaultDeviceWithMediaType(AVMediaTypeVideo)
            ?: throw CameraUnavailable("this device has no camera")
        val input = AVCaptureDeviceInput.deviceInputWithDevice(device, null)
            ?: throw CameraUnavailable("the camera could not be opened")

        session.beginConfiguration()
        session.sessionPreset = AVCaptureSessionPresetPhoto
        if (session.canAddInput(input)) session.addInput(input)
        if (session.canAddOutput(output)) session.addOutput(output)
        session.commitConfiguration()

        if (!session.isRunning()) session.startRunning()
    }

    private suspend fun requestAccess(): Boolean {
        if (AVCaptureDevice.authorizationStatusForMediaType(AVMediaTypeVideo) ==
            AVAuthorizationStatusAuthorized
        ) {
            return true
        }
        return suspendCancellableCoroutine { continuation ->
            AVCaptureDevice.requestAccessForMediaType(AVMediaTypeVideo) { granted ->
                if (continuation.isActive) continuation.resume(granted)
            }
        }
    }

    actual suspend fun capturePhoto(): CapturedImage =
        suspendCancellableCoroutine { continuation ->
            val handler = PhotoDelegate { bytes, error ->
                delegate = null
                if (!continuation.isActive) return@PhotoDelegate
                when {
                    error != null ->
                        continuation.resumeWithException(
                            CameraException("capture failed: ${error.localizedDescription}")
                        )
                    bytes == null ->
                        continuation.resumeWithException(
                            CameraException("the camera returned no image data")
                        )
                    else -> continuation.resume(CapturedImage(bytes))
                }
            }
            delegate = handler
            output.capturePhotoWithSettings(AVCapturePhotoSettings(), handler)
        }

    actual fun release() {
        if (session.isRunning()) session.stopRunning()
        delegate = null
    }
}

@OptIn(ExperimentalForeignApi::class)
private class PhotoDelegate(
    private val onResult: (ByteArray?, NSError?) -> Unit,
) : NSObject(), AVCapturePhotoCaptureDelegateProtocol {

    override fun captureOutput(
        output: AVCapturePhotoOutput,
        didFinishProcessingPhoto: platform.AVFoundation.AVCapturePhoto,
        error: NSError?,
    ) {
        if (error != null) {
            onResult(null, error)
            return
        }
        val data = didFinishProcessingPhoto.fileDataRepresentation()
        if (data == null) {
            onResult(null, null)
            return
        }
        val length = data.length.toInt()
        val bytes = ByteArray(length)
        if (length > 0) {
            bytes.usePinned { memcpy(it.addressOf(0), data.bytes, data.length) }
        }
        onResult(bytes, null)
    }
}
