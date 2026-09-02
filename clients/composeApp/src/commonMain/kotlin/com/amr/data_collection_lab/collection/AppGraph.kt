package com.amr.data_collection_lab.collection

import com.amr.data_collection_lab.defaultSyncBaseUrl
import com.amr.data_collection_lab.platformDeviceInfo
import com.dcp.core.media.GeoCapture
import com.dcp.core.media.ImageCompressor
import com.dcp.core.media.ImageEncoder
import com.dcp.core.media.LocationProvider
import com.dcp.core.media.MediaFileStore
import com.dcp.core.media.MediaStaging
import com.dcp.core.media.MediaStore
import com.dcp.core.media.MediaUploader
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.sync.DatabaseDriverFactory
import com.dcp.core.sync.FormSensitivity
import com.dcp.core.sync.FormStore
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.SyncClient
import com.dcp.core.sync.openDatabase
import com.dcp.form.sensitiveFields

/**
 * Where a platform's media hardware is handed in.
 *
 * Both together or neither: a client that can photograph but not locate, or the
 * reverse, is not a shape any platform actually has, and pretending otherwise
 * would mean four states to reason about instead of two.
 */
class MediaPlatform(
    val files: MediaFileStore,
    val location: LocationProvider,
)

/**
 * Manual wiring for the app's few long-lived objects. Replaced by Koin when DI
 * lands.
 *
 * Constructing this opens the local database, which means reading the database
 * key out of the platform keystore (encryption envelope §14). It throws rather
 * than degrading if that fails — see [com.amr.data_collection_lab.App], which
 * turns the throw into a screen that says what went wrong.
 *
 * [media] is null on a client with no camera or GPS — the desktop review app —
 * and the collection screen then shows image, signature and geopoint questions
 * as unavailable rather than as widgets that cannot answer them.
 */
class AppGraph(
    driverFactory: DatabaseDriverFactory,
    keyStore: DatabaseKeyStore,
    platform: MediaPlatform? = null,
) {
    /**
     * Opened ONCE, and shared by every store below.
     *
     * That is not tidiness. The per-file media keys live in this database, and
     * they are protected precisely because it is the SQLCipher file whose key
     * the platform keystore holds (§6, §14). A second database — or an
     * unencrypted one — would leave staged photographs openable by whoever
     * picked the phone up, while everything still looked healthy.
     */
    private val db = openDatabase(driverFactory, keyStore)

    val store: SubmissionStore = SubmissionStore(db)

    /**
     * The form versions this device has been sent (sync §5). Empty until the
     * first sync — there is no bundled form any more, and a device is not
     * entitled to collect on a form nobody deployed to it.
     */
    val formStore: FormStore = FormStore(db)
    val formCatalog: FormCatalog = FormCatalog(formStore)

    val media: MediaCaptureGraph? = platform?.let { p ->
        val mediaStore = MediaStore(db)
        MediaCaptureGraph(
            store = mediaStore,
            staging = MediaStaging(mediaStore, p.files, store),
            compressor = ImageCompressor(),
            encoder = ImageEncoder(),
            geo = GeoCapture(p.location, mediaStore),
        )
    }

    /**
     * What `field_level` encryption acts on (Form IR §2.1). Answering null for
     * a form version this device has not compiled makes the sync path fail
     * closed and encrypt the value rather than assume it is safe to send in the
     * clear.
     *
     * Now a lookup across every version the device holds rather than a check
     * against the one bundled form. That matters more than it looks: with one
     * form the wrong answer was "encrypt everything", which is safe; with
     * several, resolving to the wrong *version* would apply another version's
     * sensitivity flags to these answers, and a field that stopped being
     * sensitive in v3 would be sent in the clear from a v2 submission.
     */
    private val formSensitivity = FormSensitivity { formId, formVersion ->
        formCatalog.compiledForm(formId, formVersion)?.sensitiveFields()
    }

    val syncClient: SyncClient = SyncClient(
        store,
        defaultSyncBaseUrl(),
        deviceInfo = platformDeviceInfo(),
        formSensitivity = formSensitivity,
        // Media rides the same sync, after the ops (sync §9). Null here means
        // the loop is ops only, which is what the desktop review app wants.
        media = media?.let { graph ->
            MediaUploader(
                store = graph.store,
                files = platform!!.files,
                staging = graph.staging,
                submissions = store,
                baseUrl = defaultSyncBaseUrl(),
            )
        },
        // Where delivered forms land. Passed on every client that collects —
        // without it a device asks the server for no manifest and stays on
        // whatever forms it already had, which for a fresh install is none.
        forms = formStore,
    )
}
