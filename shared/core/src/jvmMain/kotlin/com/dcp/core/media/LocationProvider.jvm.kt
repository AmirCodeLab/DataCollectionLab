package com.dcp.core.media

/**
 * Desktop: no location hardware, and no pretence of one.
 *
 * Returning null and an explanation rather than a plausible-looking fix is the
 * whole content of this class. A desktop that reported a geocoded IP address as
 * a GPS point would be producing a coordinate that looks exactly like a real
 * one and is a fact about a data centre — and the console has no way to tell
 * the two apart once it is stored.
 *
 * The desktop app is a supervision and review client. If it ever needs a point,
 * it should ask a person to enter one, and that answer will carry no accuracy —
 * which [GeoCapture] already treats as the worst case.
 */
actual class LocationProvider : LocationSource {

    actual override fun availability(): String? =
        "this computer has no location hardware; capture the point on a device that does"

    actual override suspend fun awaitFix(timeoutMs: Long, targetAccuracyM: Double): GeoFix? = null
}
