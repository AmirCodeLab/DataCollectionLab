package com.dcp.core.media

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine

/**
 * Android: CameraX.
 *
 * `camera-core`, `camera-camera2` and `camera-lifecycle` only — no
 * `camera-view`. PreviewView is a UI class and belongs in
 * `clients/composeApp`, which attaches itself through [surfaceProvider] below.
 *
 * CameraX rather than Camera2 directly because Camera2 requires per-device
 * workarounds for orientation, aspect ratio and capture latency that CameraX
 * already carries — and the devices this ships to are exactly the cheap
 * handsets those workarounds exist for.
 */
actual class CameraCapture(
    private val context: Context,
    private val lifecycleOwner: LifecycleOwner,
) {

    private val preview = Preview.Builder().build()

    private val imageCapture = ImageCapture.Builder()
        // Latency over quality. An enumerator taking forty photographs in a
        // day notices a shutter that takes two seconds; nobody notices the
        // difference MAXIMIZE_QUALITY makes to a JPEG that is about to be
        // scaled to 1600px and compressed to quality 80 anyway.
        .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
        .build()

    private var provider: ProcessCameraProvider? = null

    /**
     * Where the viewfinder's frames go.
     *
     * The UI hands this a `PreviewView.surfaceProvider`. This is the one seam
     * between capture and presentation, and it points the right way: the UI
     * depends on the camera, not the other way round.
     */
    fun setSurfaceProvider(surfaceProvider: Preview.SurfaceProvider?) {
        preview.surfaceProvider = surfaceProvider
    }

    actual suspend fun start() {
        if (context.checkSelfPermission(Manifest.permission.CAMERA) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            throw CameraUnavailable("camera permission has not been granted")
        }

        val cameraProvider = suspendCancellableCoroutine { continuation ->
            val future = ProcessCameraProvider.getInstance(context)
            future.addListener(
                {
                    runCatching { future.get() }
                        .onSuccess { continuation.resume(it) }
                        .onFailure {
                            continuation.resumeWithException(
                                CameraUnavailable("the camera service is unavailable: ${it.message}")
                            )
                        }
                },
                ContextCompat.getMainExecutor(context),
            )
        }

        // Unbind first: re-entering the capture screen without this leaves the
        // previous binding holding the camera, and the second bind fails on
        // devices that allow only one open session.
        cameraProvider.unbindAll()
        try {
            cameraProvider.bindToLifecycle(
                lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, imageCapture,
            )
        } catch (cause: Exception) {
            throw CameraUnavailable("could not open the back camera: ${cause.message}")
        }
        provider = cameraProvider
    }

    actual suspend fun capturePhoto(): CapturedImage =
        suspendCancellableCoroutine { continuation ->
            imageCapture.takePicture(
                ContextCompat.getMainExecutor(context),
                object : ImageCapture.OnImageCapturedCallback() {
                    override fun onCaptureSuccess(image: ImageProxy) {
                        // In memory, and closed immediately. CameraX's
                        // file-output variant would write the full-resolution
                        // plaintext photograph to disk, which is the exposure
                        // the staging pipeline exists to avoid.
                        val bytes = try {
                            image.planes[0].buffer.let { buffer ->
                                ByteArray(buffer.remaining()).also(buffer::get)
                            }
                        } finally {
                            image.close()
                        }
                        if (continuation.isActive) {
                            continuation.resume(CapturedImage(bytes))
                        }
                    }

                    override fun onError(exception: ImageCaptureException) {
                        if (continuation.isActive) {
                            continuation.resumeWithException(
                                CameraException("capture failed: ${exception.message}", exception)
                            )
                        }
                    }
                },
            )
        }

    actual fun release() {
        preview.surfaceProvider = null
        provider?.unbindAll()
        provider = null
    }
}
