package com.dcp.core.media

import com.dcp.form.FormValue

/**
 * One position fix, as the platform reported it.
 *
 * [accuracyM] is the radius of 68% horizontal confidence in metres — what
 * Android calls `Location.accuracy` and iOS `horizontalAccuracy`. Null means
 * the platform declined to say, which is **not** the same as "perfect": a fix
 * with no accuracy is a fix nothing can vouch for, and it is treated as the
 * worst case everywhere below.
 */
data class GeoFix(
    val lat: Double,
    val lon: Double,
    val altM: Double? = null,
    val accuracyM: Double? = null,
    /** Milliseconds since the epoch, as the platform stamped the fix. */
    val timestampMs: Long? = null,
) {
    fun toFormValue(): FormValue.GeoPoint =
        FormValue.GeoPoint(lat = lat, lon = lon, alt = altM, accuracy = accuracyM)
}

/** Why a location could not be captured, as something the UI can say out loud. */
sealed interface GeoCaptureOutcome {
    /** A fix good enough for the project's threshold. */
    data class Accepted(val fix: GeoFix) : GeoCaptureOutcome

    /**
     * A fix arrived and is not good enough.
     *
     * **This is not an error and must not be discarded silently.** A phone
     * indoors will report a two-kilometre "fix" with exactly the authority of a
     * good one, and once it is stored nothing downstream can tell them apart —
     * it is wrong in the same shape as right. So the reading is handed back
     * with its accuracy, for the enumerator to be told "still finding your
     * position: 240 m, need 50 m" and to step outside, rather than for the app
     * to record it and move on.
     */
    data class TooImprecise(val fix: GeoFix, val requiredM: Int) : GeoCaptureOutcome

    /** No fix at all within the time allowed. Indoors, or no sky. */
    data object TimedOut : GeoCaptureOutcome

    /** Location permission was refused, or location services are off. */
    data class Unavailable(val reason: String) : GeoCaptureOutcome
}

/**
 * Somewhere position fixes come from.
 *
 * An interface rather than the expect class directly, because the rule that
 * matters — whether a fix is good enough to keep — has to be testable without a
 * GPS receiver. [GeoCapture] depends on this; [LocationProvider] is the real
 * one.
 */
interface LocationSource {

    /**
     * Streams fixes until [timeoutMs] elapses, best so far last.
     *
     * A stream rather than a single call because that is how GPS actually
     * behaves: the first fix is a cell-tower estimate good to a kilometre, and
     * accuracy improves over the following seconds. Asking once and taking the
     * answer is how an app ends up storing that first estimate.
     *
     * Returns null if no fix arrived at all.
     */
    suspend fun awaitFix(timeoutMs: Long, targetAccuracyM: Double): GeoFix?

    /**
     * Null when a fix can be attempted; otherwise why it cannot, in words the
     * UI can put on the screen.
     */
    fun availability(): String?
}

/**
 * The platform's location service (Android LocationManager, iOS
 * CLLocationManager).
 *
 * Each platform's actual takes its own constructor arguments, following
 * [MediaFileStore] and [com.dcp.core.security.DatabaseKeyStore].
 */
expect class LocationProvider : LocationSource {
    override suspend fun awaitFix(timeoutMs: Long, targetAccuracyM: Double): GeoFix?
    override fun availability(): String?
}

/**
 * Captures a point, holding it to the project's accuracy threshold.
 *
 * The threshold check lives here, in common code, rather than in each
 * platform's actual: it is the rule that decides whether someone's data is
 * trustworthy, and three copies of it is three chances for one platform to
 * quietly accept what another refuses.
 */
class GeoCapture(
    private val provider: LocationSource,
    private val store: MediaStore,
) {

    /**
     * @param timeoutMs how long to keep improving the fix before giving up.
     *   Ten seconds is enough for a phone that already has a lock and far too
     *   short for a cold start under tree cover, which is why the outcome
     *   distinguishes "no fix yet" from "not good enough yet" — both mean
     *   "wait", and neither means "record this".
     */
    suspend fun capture(timeoutMs: Long = 10_000): GeoCaptureOutcome {
        provider.availability()?.let { return GeoCaptureOutcome.Unavailable(it) }

        val required = store.policy().gpsMaxAccuracyM
        val fix = provider.awaitFix(timeoutMs, required.toDouble())
            ?: return GeoCaptureOutcome.TimedOut

        // No reported accuracy is the worst case, not the best. A platform that
        // will not say how good a fix is has not given us grounds to accept it.
        val accuracy = fix.accuracyM
        return if (accuracy != null && accuracy <= required) {
            GeoCaptureOutcome.Accepted(fix)
        } else {
            GeoCaptureOutcome.TooImprecise(fix, required)
        }
    }
}
