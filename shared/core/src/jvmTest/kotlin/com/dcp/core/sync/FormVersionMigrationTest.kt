package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * v9 -> v10 carries the forms a device already holds.
 *
 * Every migration before this one was additive — a new table, a new column,
 * an index. This one **rebuilds `form_version`**, because SQLite cannot drop a
 * NOT NULL and the document column had to become nullable (item 4 §5.1). A
 * rebuild that dropped a row would take an enumerator's form with it, and a
 * draft against that version could then never be opened: the op log holds the
 * answers and the document holds the questions.
 *
 * `MigrationChainTest` checks the chain's shape. This runs the step.
 *
 * The v9 table is written out here rather than imported, deliberately: the
 * point is to migrate the schema as it was, and reading it from today's `.sq`
 * would be migrating from the answer.
 */
class FormVersionMigrationTest {

    /** `form_version` exactly as v9 had it, NOT NULL document and all. */
    private val v9 = listOf(
        """
        CREATE TABLE form_version (
            form_version_id TEXT NOT NULL PRIMARY KEY,
            form_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            title TEXT NOT NULL,
            ir_json TEXT NOT NULL,
            ir_checksum TEXT NOT NULL,
            deployed INTEGER NOT NULL DEFAULT 1,
            fetched_at TEXT NOT NULL
        )
        """,
        "CREATE UNIQUE INDEX form_version_key ON form_version(form_id, version)",
        "CREATE INDEX form_version_deployed ON form_version(deployed)",
    )

    private fun driverAtV9(): JdbcSqliteDriver {
        val driver = JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties())
        v9.forEach { driver.execute(null, it.trimIndent(), 0) }
        driver.execute(
            null,
            """
            INSERT INTO form_version(form_version_id, form_id, version, title, ir_json,
                                     ir_checksum, deployed, fetched_at)
            VALUES ('fv-h-2', 'household', 2, 'Household Survey', '{"formId":"household"}',
                    'sha256:h2', 1, '2026-09-01T08:00:00Z'),
                   ('fv-h-1', 'household', 1, 'Household Survey', '{"formId":"household"}',
                    'sha256:h1', 0, '2026-08-01T08:00:00Z')
            """.trimIndent(),
            0,
        )
        return driver
    }

    private fun rows(driver: JdbcSqliteDriver, sql: String): List<List<String?>> =
        driver.executeQuery(null, sql, { cursor ->
            val out = mutableListOf<List<String?>>()
            while (cursor.next().value) {
                out.add((0 until 4).map { cursor.getString(it) })
            }
            app.cash.sqldelight.db.QueryResult.Value(out.toList())
        }, 0).value

    @Test
    fun `the forms a device holds survive the rebuild, deployed flag and all`() {
        val driver = driverAtV9()

        DcpDatabase.Schema.migrate(driver, 9, 10).value

        val held = rows(
            driver,
            "SELECT form_version_id, ir_json, ir_checksum, CAST(deployed AS TEXT) " +
                "FROM form_version ORDER BY form_version_id",
        )
        assertEquals(2, held.size, "the rebuild dropped a form an enumerator was holding")
        assertEquals("fv-h-1", held[0][0])
        assertEquals("sha256:h1", held[0][2])
        assertEquals("0", held[0][3], "the withdrawn version must stay withdrawn")
        assertEquals("fv-h-2", held[1][0])
        assertEquals("1", held[1][3])
        held.forEach { assertTrue(it[1]!!.contains("household"), "a document was lost") }
    }

    @Test
    fun `after the rebuild a deployed version may be recorded without its document`() {
        val driver = driverAtV9()
        DcpDatabase.Schema.migrate(driver, 9, 10).value

        driver.execute(
            null,
            "INSERT INTO form_version(form_version_id, form_id, version, title, ir_json, " +
                "ir_checksum, deployed, fetched_at) " +
                "VALUES ('fv-c-1', 'clinic', 1, 'Clinic', NULL, 'sha256:c1', 1, 'now')",
            0,
        )
        val placeholder = rows(
            driver,
            "SELECT form_version_id, ir_json, ir_checksum, CAST(deployed AS TEXT) " +
                "FROM form_version WHERE form_id = 'clinic'",
        )
        assertEquals(1, placeholder.size)
        assertNull(placeholder[0][1], "the document column is still NOT NULL")
    }

    @Test
    fun `the indexes come back with the table`() {
        val driver = driverAtV9()
        DcpDatabase.Schema.migrate(driver, 9, 10).value

        // Two ids claiming to be the same (form, version) is a device that
        // cannot say which document a submission meant. The unique index is
        // what refuses it, and a rebuild that forgot to recreate it would
        // leave that door open with every test still green.
        val duplicate = runCatching {
            driver.execute(
                null,
                "INSERT INTO form_version(form_version_id, form_id, version, title, ir_json, " +
                    "ir_checksum, deployed, fetched_at) " +
                    "VALUES ('fv-other', 'household', 2, 'Household', '{}', 'sha256:x', 1, 'now')",
                0,
            )
        }
        assertTrue(duplicate.isFailure, "form_version_key did not survive the rebuild")
    }
}
