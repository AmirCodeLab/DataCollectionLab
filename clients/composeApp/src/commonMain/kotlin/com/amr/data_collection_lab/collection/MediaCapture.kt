package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Composable

/**
 * The two places the UI has to touch the platform to get a photograph.
 *
 * Everything else about media — compression, encryption, chunking, hashing,
 * upload — is in `shared/core` and identical on every platform. What cannot be
 * shared is the viewfinder and the system picker, because one is a
 * platform-drawn surface and the other is another app's screen.
 *
 * Both hand back **bytes**, never a file path. A path would mean the
 * full-resolution plaintext photograph exists on the filesystem for as long as
 * it takes to read it back, and the whole of `MediaStaging` is arranged so that
 * it never does.
 */

/**
 * A full-screen viewfinder with a shutter.
 *
 * Shown in place of the question list, not over it: a camera preview inside a
 * scrolling form is a viewfinder people cannot aim, and on the handsets this
 * ships to it is also a surface the compositor struggles to keep smooth.
 *
 * [onCaptured] receives the sensor's own JPEG. Scaling to the project's
 * settings happens afterwards, in `shared/core` — the camera has no business
 * knowing them.
 */
@Composable
expect fun CameraCaptureScreen(
    onCaptured: (ByteArray) -> Unit,
    onCancel: () -> Unit,
    onUnavailable: (String) -> Unit,
)

/**
 * Returns a function that opens the system photo picker.
 *
 * The picker rather than a permission to read all photos: on Android it is
 * `PickVisualMedia`, which needs no storage permission at all and shows the
 * user exactly which image they are handing over. Asking for
 * READ_MEDIA_IMAGES to achieve the same thing would be asking a respondent's
 * enumerator to grant an app access to their entire camera roll.
 *
 * The callback receives null when the picker was dismissed — a normal outcome,
 * not an error.
 */
@Composable
expect fun rememberGalleryPicker(onPicked: (ByteArray?) -> Unit): () -> Unit

/**
 * Asks for location permission, then reports whether it was granted.
 *
 * Its own request rather than a share of the camera's, because the two are
 * asked at different moments and a person may reasonably allow one and refuse
 * the other. Photographing a dwelling and recording where it is are separate
 * disclosures.
 *
 * This was missing entirely and only showed on a device: the geopoint question
 * asked the platform for a fix, was told permission had not been granted,
 * reported that honestly — and offered no way to grant it. Correct refusal,
 * dead end for the enumerator.
 *
 * Already granted calls back immediately, so the caller has one path rather
 * than two.
 */
@Composable
expect fun rememberLocationPermissionRequest(onResult: (Boolean) -> Unit): () -> Unit

/** Whether this platform can capture at all. False on desktop. */
@Composable
expect fun isCaptureSupported(): Boolean
