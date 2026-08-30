package com.dcp.core.sync

import com.dcp.core.db.DcpDatabase
import com.dcp.core.security.DatabaseKeyStore
import com.dcp.core.security.DatabaseKeyUnavailable

/**
 * Builds the store from a platform driver factory. Keeps the generated
 * SQLDelight database type out of client modules' compile classpaths.
 *
 * The key store is taken, not the key: nothing above this line should hold key
 * material, and the key is destroyed here as soon as the driver has it
 * (encryption envelope §14).
 */
fun createSubmissionStore(
    driverFactory: DatabaseDriverFactory,
    keyStore: DatabaseKeyStore,
    actorId: String = "usr_local",
): SubmissionStore {
    // An encrypted database and a keystore with no key in it is not a first
    // run — it is a lost key, and generating a replacement here would leave
    // every unsynced answer on the device permanently unreadable while the app
    // looked healthy. Checked separately because a keystore cannot always tell
    // "no such item" from "I will not answer you": macOS reports both as
    // errSecItemNotFound.
    if (driverFactory.databaseState() == LocalDatabaseState.ENCRYPTED && !keyStore.exists()) {
        throw DatabaseKeyUnavailable(
            "there is an encrypted local database but the keystore holds no key for it. " +
                "Generating one now would orphan it permanently (encryption envelope §14.3). " +
                "Either the keystore is locked or unavailable — unlock it and start again — or " +
                "the key really is gone, and the device has to be re-enrolled, losing whatever " +
                "had not synced.",
        )
    }

    val key = keyStore.loadOrCreate()
    val driver = try {
        driverFactory.createDriver(key)
    } finally {
        // The binding that opened the database keeps its own copy for the life
        // of the connection — §14.8 puts a running, unlocked device out of
        // scope — so this narrows the window rather than closing it.
        key.destroy()
    }
    return SubmissionStore(DcpDatabase(driver), actorId)
}
