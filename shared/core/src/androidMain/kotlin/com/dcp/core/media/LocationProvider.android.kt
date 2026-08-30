package com.dcp.core.media

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Looper
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull

/**
 * Android: the platform LocationManager, GPS provider.
 *
 * Not Google Play Services' FusedLocationProvider, deliberately. Play Services
 * is absent on a large share of the devices this product targets — Chinese
 * Android builds, government-issued tablets, anything sideloaded — and a
 * dependency that makes location silently unavailable on those devices is a
 * dependency that makes the app unusable exactly where it is needed.
 */
actual class LocationProvider(private val context: Context) : LocationSource {

    private val manager: LocationManager? =
        context.getSystemService(Context.LOCATION_SERVICE) as? LocationManager

    actual override fun availability(): String? {
        val granted = context.checkSelfPermission(Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
        if (!granted) return "location permission has not been granted"
        val m = manager ?: return "this device has no location service"
        if (!m.isProviderEnabled(LocationManager.GPS_PROVIDER) &&
            !m.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
        ) {
            return "location is switched off on this device"
        }
        return null
    }

    actual override suspend fun awaitFix(timeoutMs: Long, targetAccuracyM: Double): GeoFix? {
        val m = manager ?: return null
        return withTimeoutOrNull(timeoutMs) {
            suspendCancellableCoroutine { continuation ->
                var best: Location? = null

                val listener = object : LocationListener {
                    override fun onLocationChanged(location: Location) {
                        // Keep the best fix seen, not the latest. GPS accuracy
                        // improves over the first seconds but is not monotonic,
                        // and taking the last reading throws away a good fix
                        // for a worse one that arrived after it.
                        val incumbent = best
                        if (incumbent == null || location.accuracy < incumbent.accuracy) {
                            best = location
                        }
                        val good = best!!
                        if (good.hasAccuracy() && good.accuracy <= targetAccuracyM) {
                            // Good enough; stop burning the battery.
                            runCatching { m.removeUpdates(this) }
                            if (continuation.isActive) continuation.resume(good.toFix())
                        }
                    }

                    @Deprecated("required by the pre-API-29 interface")
                    override fun onStatusChanged(p: String?, s: Int, e: android.os.Bundle?) = Unit

                    override fun onProviderDisabled(provider: String) = Unit
                    override fun onProviderEnabled(provider: String) = Unit
                }

                continuation.invokeOnCancellation {
                    runCatching { m.removeUpdates(listener) }
                    // The timeout path: hand back the best fix so far rather
                    // than nothing. GeoCapture decides whether it is good
                    // enough — this class does not get to make that call.
                }

                for (provider in listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)) {
                    if (!m.isProviderEnabled(provider)) continue
                    runCatching {
                        m.requestLocationUpdates(provider, 1000L, 0f, listener, Looper.getMainLooper())
                    }
                }
            }
        } ?: bestEffort(m)
    }

    /**
     * What the platform already knows, when no new fix arrived in time.
     *
     * A cached fix carries its own timestamp and accuracy, so it is handed on
     * with both and judged like any other — a fix from two hours ago in another
     * village is exactly the kind of thing the accuracy threshold and the
     * enumerator's own eyes are there to catch.
     */
    private fun bestEffort(m: LocationManager): GeoFix? =
        runCatching {
            listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
                .mapNotNull { m.getLastKnownLocation(it) }
                .minByOrNull { if (it.hasAccuracy()) it.accuracy else Float.MAX_VALUE }
                ?.toFix()
        }.getOrNull()

    private fun Location.toFix() = GeoFix(
        lat = latitude,
        lon = longitude,
        altM = if (hasAltitude()) altitude else null,
        accuracyM = if (hasAccuracy()) accuracy.toDouble() else null,
        timestampMs = time,
    )
}
