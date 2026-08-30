package com.dcp.core.media

import kotlin.coroutines.resume
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.useContents
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import platform.CoreLocation.CLAuthorizationStatus
import platform.CoreLocation.CLLocation
import platform.CoreLocation.CLLocationManager
import platform.CoreLocation.CLLocationManagerDelegateProtocol
import platform.CoreLocation.kCLAuthorizationStatusAuthorizedAlways
import platform.CoreLocation.kCLAuthorizationStatusAuthorizedWhenInUse
import platform.CoreLocation.kCLAuthorizationStatusDenied
import platform.CoreLocation.kCLAuthorizationStatusNotDetermined
import platform.CoreLocation.kCLAuthorizationStatusRestricted
import platform.CoreLocation.kCLLocationAccuracyBest
import platform.Foundation.NSError
import platform.Foundation.timeIntervalSince1970
import platform.darwin.NSObject

/**
 * iOS: CoreLocation.
 *
 * `horizontalAccuracy` is negative when CoreLocation considers the coordinate
 * invalid, which is its way of saying "I do not know where you are" while still
 * handing back a coordinate. Mapping that to a null accuracy rather than to a
 * negative number matters: [GeoCapture] treats an unknown accuracy as the worst
 * case, whereas a negative one would compare as better than any threshold and
 * be accepted.
 */
@OptIn(ExperimentalForeignApi::class)
actual class LocationProvider : LocationSource {

    private val manager = CLLocationManager()

    actual override fun availability(): String? {
        if (!CLLocationManager.locationServicesEnabled()) {
            return "location is switched off on this device"
        }
        return when (manager.authorizationStatus) {
            kCLAuthorizationStatusDenied -> "location permission has been denied for this app"
            kCLAuthorizationStatusRestricted -> "location is restricted on this device"
            kCLAuthorizationStatusNotDetermined -> {
                manager.requestWhenInUseAuthorization()
                "waiting for location permission"
            }
            kCLAuthorizationStatusAuthorizedAlways,
            kCLAuthorizationStatusAuthorizedWhenInUse,
            -> null
            else -> "location permission is in an unknown state"
        }
    }

    actual override suspend fun awaitFix(timeoutMs: Long, targetAccuracyM: Double): GeoFix? {
        var best: CLLocation? = null

        val fix = withTimeoutOrNull(timeoutMs) {
            suspendCancellableCoroutine { continuation ->
                val delegate = object : NSObject(), CLLocationManagerDelegateProtocol {
                    override fun locationManager(
                        manager: CLLocationManager,
                        didUpdateLocations: List<*>,
                    ) {
                        val location = didUpdateLocations.lastOrNull() as? CLLocation ?: return
                        // Best seen, not latest: accuracy improves over the
                        // first seconds but not monotonically, and taking the
                        // last reading throws away a good fix for a worse one.
                        val incumbent = best
                        if (incumbent == null || location.betterThan(incumbent)) {
                            best = location
                        }
                        val accuracy = best?.horizontalAccuracy ?: return
                        if (accuracy in 0.0..targetAccuracyM) {
                            manager.stopUpdatingLocation()
                            if (continuation.isActive) continuation.resume(best?.toFix())
                        }
                    }

                    override fun locationManager(
                        manager: CLLocationManager,
                        didFailWithError: NSError,
                    ) {
                        manager.stopUpdatingLocation()
                        if (continuation.isActive) continuation.resume(null)
                    }

                    override fun locationManagerDidChangeAuthorization(manager: CLLocationManager) =
                        Unit
                }

                continuation.invokeOnCancellation {
                    manager.stopUpdatingLocation()
                    manager.delegate = null
                }

                manager.delegate = delegate
                manager.desiredAccuracy = kCLLocationAccuracyBest
                manager.startUpdatingLocation()
            }
        }

        // On timeout, hand back the best fix so far rather than nothing.
        // GeoCapture decides whether it is good enough; this class does not.
        return fix ?: best?.toFix()
    }

    private fun CLLocation.betterThan(other: CLLocation): Boolean {
        val mine = horizontalAccuracy
        val theirs = other.horizontalAccuracy
        if (mine < 0) return false
        if (theirs < 0) return true
        return mine < theirs
    }

    private fun CLLocation.toFix(): GeoFix = coordinate.useContents {
        GeoFix(
            lat = latitude,
            lon = longitude,
            altM = if (verticalAccuracy >= 0) altitude else null,
            // Negative means CoreLocation does not vouch for the coordinate.
            // Null, not the negative number: an unknown accuracy is the worst
            // case, and a negative one would beat every threshold.
            accuracyM = horizontalAccuracy.takeIf { it >= 0 },
            timestampMs = (timestamp.timeIntervalSince1970 * 1000).toLong(),
        )
    }
}
