package com.dcp.core.sync

/**
 * The .sqm chain is contiguous, and each file still migrates the version its
 * name claims.
 *
 * A device in the field carries its op log and its logical counter across
 * upgrades. The counter especially must survive: operation nonces are derived
 * from `(deviceId, counter)` (encryption envelope §4.5), so a device that lost
 * it and later encrypted would reuse a nonce — the one failure AES-GCM does not
 * tolerate. Recreating the database instead of migrating it is not an option.
 *
 * SQLDelight's own `verifyMigrations` would be the stronger check, but it
 * cannot be switched on here: it type-checks each .sqm against the schema as of
 * that version, reconstructed from a committed snapshot, and no snapshots were
 * kept for versions 1-3 — enabling it fails the build on the existing
 * migrations rather than on anything wrong. Adopting it means committing a
 * snapshot now and turning it on for the versions after it. Until then, this is
 * the check standing between a mistake here and a bricked device.
 */

import com.dcp.core.db.DcpDatabase
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class MigrationChainTest {

    private val migrationDir: File by lazy {
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null) {
            val candidate = dir.resolve("shared/core/src/commonMain/sqldelight/com/dcp/core/db")
            if (candidate.isDirectory) return@lazy candidate
            dir = dir.parentFile
        }
        error("sqldelight source directory not found above ${System.getProperty("user.dir")}")
    }

    private fun migrations(): List<File> =
        migrationDir.listFiles { f -> f.extension == "sqm" }!!
            .sortedBy { it.nameWithoutExtension.toInt() }

    @Test
    fun `migrations are numbered contiguously from 1`() {
        val versions = migrations().map { it.nameWithoutExtension.toInt() }
        assertEquals((1..versions.size).toList(), versions, "gap or duplicate in the .sqm chain")
    }

    @Test
    fun `the schema version accounts for every migration`() {
        // SQLDelight derives the version as 1 + the number of migrations. A
        // mismatch means a migration was added without the schema following,
        // or one was deleted and devices on it can never upgrade.
        assertEquals(migrations().size + 1L, DcpDatabase.Schema.version)
    }

    @Test
    fun `each migration still declares the step it performs`() {
        // Overwriting an existing migration rather than adding a new one is the
        // easy mistake, and a silent one: the build stays green, tests that
        // create a fresh database stay green, and only an already-installed
        // device is broken. Naming the step in the file makes the overwrite
        // fail here instead.
        migrations().forEach { file ->
            val version = file.nameWithoutExtension.toInt()
            val header = file.readLines().first()
            assertTrue(
                header.startsWith("-- v$version -> v${version + 1}:"),
                "${file.name} should begin with \"-- v$version -> v${version + 1}: ...\", " +
                    "but begins with: $header",
            )
        }
    }
}
