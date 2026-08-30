package com.amr.data_collection_lab.collection

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.view.PreviewView
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.dcp.core.media.CameraCancelled
import com.dcp.core.media.CameraCapture
import com.dcp.core.media.CameraException
import kotlinx.coroutines.launch

/**
 * Android: a CameraX viewfinder, and the system photo picker.
 *
 * `PreviewView` — the only UI class in the CameraX family — is a dependency of
 * THIS module, not of `shared/core`. `shared/core` owns the capture pipeline
 * and hands out a `Preview.SurfaceProvider` sink; this attaches the view to it.
 * That is the whole seam, and it points the right way: the UI depends on the
 * camera, never the reverse.
 */

@Composable
actual fun CameraCaptureScreen(
    onCaptured: (ByteArray) -> Unit,
    onCancel: () -> Unit,
    onUnavailable: (String) -> Unit,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val scope = rememberCoroutineScope()

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            onUnavailable(
                "Camera permission was refused. Grant it in Settings to take photographs."
            )
        }
    }

    val camera = remember { CameraCapture(context, lifecycleOwner) }
    val previewView = remember {
        PreviewView(context).apply {
            // COMPATIBLE, not PERFORMANCE: on the cheap handsets this ships to,
            // the SurfaceView-backed mode leaves a black rectangle on a
            // meaningful share of devices, and a viewfinder that does not draw
            // is a photograph that does not get taken.
            implementationMode = PreviewView.ImplementationMode.COMPATIBLE
        }
    }

    LaunchedEffect(Unit) {
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            permissionLauncher.launch(Manifest.permission.CAMERA)
            return@LaunchedEffect
        }
        camera.setSurfaceProvider(previewView.surfaceProvider)
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
        AndroidView(factory = { previewView }, modifier = Modifier.fillMaxSize())

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

@Composable
actual fun rememberGalleryPicker(onPicked: (ByteArray?) -> Unit): () -> Unit {
    val context = LocalContext.current
    val launcher = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia()
    ) { uri ->
        if (uri == null) {
            // Dismissed. A normal outcome, not an error.
            onPicked(null)
            return@rememberLauncherForActivityResult
        }
        // Read straight into memory and hand over bytes. Copying to a cache
        // file first would put the plaintext image on the filesystem, which is
        // the exposure the staging pipeline exists to avoid.
        val bytes = runCatching {
            context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
        }.getOrNull()
        onPicked(bytes)
    }
    return {
        // PickVisualMedia needs no storage permission at all, and shows the
        // user exactly which image they are handing over. READ_MEDIA_IMAGES
        // would achieve the same thing by asking for the entire camera roll.
        launcher.launch(
            PickVisualMediaRequest.Builder()
                .setMediaType(ActivityResultContracts.PickVisualMedia.ImageOnly)
                .build()
        )
    }
}

@Composable
actual fun isCaptureSupported(): Boolean = true
