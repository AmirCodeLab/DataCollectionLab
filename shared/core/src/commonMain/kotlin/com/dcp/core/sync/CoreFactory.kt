package com.dcp.core.sync

import com.dcp.core.db.DcpDatabase

/**
 * Builds the store from a platform driver factory. Keeps the generated
 * SQLDelight database type out of client modules' compile classpaths.
 */
fun createSubmissionStore(
    driverFactory: DatabaseDriverFactory,
    actorId: String = "usr_local",
): SubmissionStore = SubmissionStore(DcpDatabase(driverFactory.createDriver()), actorId)
