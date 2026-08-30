package com.amr.data_collection_lab.collection

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.interop.UIKitView
import androidx.compose.ui.unit.dp
import com.dcp.core.media.CameraCancelled
import com.dcp.core.media.CameraCapture
import com.dcp.core.media.CameraException
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.readValue
import kotlinx.cinterop.usePinned
import kotlinx.coroutines.launch
import platform.CoreGraphics.CGRectZero
import platform.Foundation.NSData
import platform.UIKit.UIApplication
import platform.UIKit.UIImage
import platform.UIKit.UIImageJPEGRepresentation
import platform.UIKit.UIImagePickerController
import platform.UIKit.UIImagePickerControllerDelegateProtocol
import platform.UIKit.UIImagePickerControllerOriginalImage
import platform.UIKit.UIImagePickerControllerSourceType
import platform.UIKit.UINavigationControllerDelegateProtocol
import platform.UIKit.UIView
import platform.darwin.NSObject
import platform.posix.memcpy

/**
 * iOS: an AVFoundation viewfinder, and the system photo picker.
 *
 * The preview LAYER comes from `shared/core`; the UIKit view that hosts it is
 * built here. That is the same seam as on Android and it points the same way:
 * the UI depends on the camera, never the reverse, and no UIKit view is
 * constructed in `shared/core`.
 */

@OptIn(ExperimentalForeignApi::class)
@Composable
actual fun CameraCaptureScreen(
    onCaptured: (ByteArray) -> Unit,
    onCancel: () -> Unit,
    onUnavailable: (String) -> Unit,
) {
    val camera = remember { CameraCapture() }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        try {
            camera.start()
        } catch (cause: CameraException) {
            onUnavailable(cause.message ?: "the camera could not be opened")
        }
    }

    DisposableEffect(Unit) {
        onDispose { camera.release() }
    }

    Box(modifier = Modifier.fillMaxSize()) {
        UIKitView(
            factory = {
                UIView(frame = CGRectZero.readValue()).apply {
                    layer.addSublayer(camera.previewLayer)
                }
            },
            // The layer does not follow its host view's bounds on its own, so
            // it is resized on every layout pass. Without this the viewfinder
            // is a small rectangle in the corner on rotation.
            onResize = { view, rect -> camera.previewLayer.setFrame(rect) },
            modifier = Modifier.fillMaxSize(),
        )

        Button(
            modifier = Modifier.align(Alignment.BottomCenter).padding(bottom = 40.dp),
            onClick = {
                scope.launch {
                    try {
                        onCaptured(camera.capturePhoto().bytes)
                    } catch (_: CameraCancelled) {
                        onCancel()
                    } catch (cause: CameraException) {
                        onUnavailable(cause.message ?: "the photograph could not be taken")
                    }
                }
            },
        ) { Text("Capture") }

        TextButton(
            modifier = Modifier.align(Alignment.TopStart).padding(12.dp),
            onClick = onCancel,
        ) { Text("Cancel") }
    }
}

@OptIn(ExperimentalForeignApi::class)
@Composable
actual fun rememberGalleryPicker(onPicked: (ByteArray?) -> Unit): () -> Unit {
    // Held across recompositions: UIKit keeps only a weak reference to a
    // picker delegate, and one collected while the picker is open produces no
    // callback at all — the caller would wait forever rather than fail.
    val delegate = remember { PickerDelegate() }
    return {
        delegate.onResult = onPicked
        val picker = UIImagePickerController().apply {
            sourceType = UIImagePickerControllerSourceType.UIImagePickerControllerSourceTypePhotoLibrary
            this.delegate = delegate
        }
        val root = UIApplication.sharedApplication.keyWindow?.rootViewController
        if (root == null) onPicked(null)
        else root.presentViewController(picker, animated = true, completion = null)
    }
}

@Composable
actual fun rememberLocationPermissionRequest(onResult: (Boolean) -> Unit): () -> Unit = {
    // CoreLocation raises its own prompt the first time the provider is asked
    // (LocationProvider.availability calls requestWhenInUseAuthorization), so
    // there is nothing to launch here. Proceeding lets the provider ask and
    // then report — a second prompt from this layer would be a duplicate.
    onResult(true)
}

@Composable
actual fun isCaptureSupported(): Boolean = true

@OptIn(ExperimentalForeignApi::class)
private class PickerDelegate :
    NSObject(),
    UIImagePickerControllerDelegateProtocol,
    UINavigationControllerDelegateProtocol {

    var onResult: ((ByteArray?) -> Unit)? = null

    override fun imagePickerController(
        picker: UIImagePickerController,
        didFinishPickingMediaWithInfo: Map<Any?, *>,
    ) {
        val image = didFinishPickingMediaWithInfo[UIImagePickerControllerOriginalImage] as? UIImage
        // Re-encoded at quality 1.0 rather than passed through: the picker
        // hands back a decoded UIImage, not the original file's bytes, so
        // something has to encode it. Compression to the project's settings
        // happens afterwards, in shared/core.
        val data = image?.let { UIImageJPEGRepresentation(it, 1.0) }
        picker.dismissViewControllerAnimated(true, completion = null)
        onResult?.invoke(data?.toByteArray())
    }

    override fun imagePickerControllerDidCancel(picker: UIImagePickerController) {
        picker.dismissViewControllerAnimated(true, completion = null)
        // Dismissed. A normal outcome, not an error.
        onResult?.invoke(null)
    }
}

@OptIn(ExperimentalForeignApi::class)
private fun NSData.toByteArray(): ByteArray {
    val size = length.toInt()
    return ByteArray(size).also { out ->
        if (size > 0) out.usePinned { memcpy(it.addressOf(0), bytes, length) }
    }
}
