package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Composable

/**
 * Desktop: no capture.
 *
 * The desktop app is a supervision and review client — it reads submissions
 * collected in the field. [isCaptureSupported] returning false is what makes
 * the image question show its gallery button and nothing else, rather than a
 * shutter that does nothing.
 */

@Composable
actual fun CameraCaptureScreen(
    onCaptured: (ByteArray) -> Unit,
    onCancel: () -> Unit,
    onUnavailable: (String) -> Unit,
) {
    // Never reached: the button that opens this is not drawn on desktop. If it
    // ever is, saying so beats a blank screen.
    onUnavailable("this computer cannot take photographs")
}

@Composable
actual fun rememberGalleryPicker(onPicked: (ByteArray?) -> Unit): () -> Unit = {
    // A desktop file chooser belongs here when the review app needs to attach
    // a file. Until it does, a no-op that reports "nothing chosen" is honest;
    // a Swing dialog wired to a Compose Multiplatform window is a piece of
    // work, and building it speculatively is how the desktop app ends up with
    // a half-tested path nobody uses.
    onPicked(null)
}

@Composable
actual fun rememberLocationPermissionRequest(onResult: (Boolean) -> Unit): () -> Unit = {
    // Nothing to ask for: the desktop provider reports that there is no
    // location hardware, which is the honest answer and the one the UI shows.
    onResult(true)
}

@Composable
actual fun isCaptureSupported(): Boolean = false
