package com.dcp.core.media

/**
 * Desktop: no capture, and no pretence of one.
 *
 * The desktop app is a supervision and review client — it reads submissions
 * collected in the field rather than collecting them. A webcam path would be a
 * feature nobody asked for standing in the way of the ones they did, and a
 * silent no-op would leave a question that can never be answered with no
 * explanation on the screen.
 */
actual class CameraCapture {

    actual suspend fun start(): Unit =
        throw CameraUnavailable(
            "the desktop app does not capture photographs; take them on the device " +
                "collecting the submission",
        )

    actual suspend fun capturePhoto(): CapturedImage = throw CameraUnavailable(
        "the desktop app does not capture photographs",
    )

    actual fun release() = Unit
}
