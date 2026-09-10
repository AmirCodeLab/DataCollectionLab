package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.HttpHeaders
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking

/**
 * Three actions, and which of them spends what (item 4).
 *
 * The work sync must carry the answers and both manifests and **nothing
 * expensive**: a person who taps it on a village connection has not agreed to
 * a 38,000-row list, and a person who never taps the other two must still have
 * their morning's interviews sent. Everything below is about which bytes leave
 * the phone for which tap.
 */
class SeparateSyncTest {

    private val fastRetry = SyncConfig(batchSize = 2, maxAttempts = 2, baseDelayMs = 1)

    private class Fixture {
        val db: DcpDatabase = DcpDatabase(
            JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)
        )
        val submissions = SubmissionStore(db, deviceIdOverride = "dev-test")
        val forms = FormStore(db)
        val datasets = DatasetStore(db)
        val referenceData = ReferenceData(forms, datasets, submissions)
    }

    private fun formEntry(formId: String, version: Int) =
        """{"formVersionId":"fv-$formId-$version","formId":"$formId","version":$version,
            "title":"Household Survey","irChecksum":"sha256:$formId-$version",
            "deployedAt":"2026-09-02T10:00:00Z"}"""

    private fun datasetEntry(key: String, version: Int, formId: String, rows: Int) =
        """{"formVersionId":"fv-$formId-1","datasetKey":"$key",
            "datasetVersionId":"dv-$key-$version","version":$version,"rowCount":$rows,
            "checksum":"sha256:$key-$version","filterColumns":["name"]}"""

    private fun pullBody(forms: String, datasets: String, cursor: Long = 4) =
        """{"ops":[],"tombstones":[],"forms":[$forms],"datasets":[$datasets],
            "nextCursor":$cursor,"hasMore":false}"""

    private fun documentBody(formId: String, version: Int) =
        """{"formVersionId":"fv-$formId-$version","formId":"$formId","version":$version,
            "title":"Household Survey","irChecksum":"sha256:$formId-$version",
            "form":{"irVersion":"0.1","formId":"$formId","version":$version,
                    "title":{"en":"Household Survey"},"defaultLanguage":"en",
                    "languages":["en"],"children":[]}}"""

    private fun rowsBody(datasetVersionId: String, count: Int) =
        """{"datasetVersionId":"$datasetVersionId","rows":[""" +
            (1..count).joinToString(",") {
                // The record key is the value column's cell (§3.1), which the
                // client reads from `name`.
                """{"name":"V$it","label":"Village $it","district":"D"}"""
            } + """],"nextCursor":null,"hasMore":false}"""

    private fun MockRequestHandleScope.jsonResponse(body: String): HttpResponseData =
        respond(body, headers = headersOf(HttpHeaders.ContentType, "application/json"))

    /** Everything the server is asked for, in order, as `METHOD path?query`. */
    private fun client(fixture: Fixture, seen: MutableList<String>): SyncClient {
        val http = HttpClient(
            MockEngine { request ->
                val path = request.url.encodedPath
                when {
                    path.endsWith("/devices") ->
                        jsonResponse("""{"deviceId":"dev-test","status":"registered"}""")
                    path.endsWith("/crypto") -> jsonResponse(
                        """{"deviceId":"dev-test","projectId":"prj","securityMode":"standard",
                            "projectKeys":[]}"""
                    )
                    else -> {
                        seen += "$path?${request.url.parameters["limit"] ?: ""}"
                        when {
                            path.endsWith("/pull") -> jsonResponse(
                                pullBody(
                                    formEntry("household", 1),
                                    datasetEntry("villages", 8, "household", 3) + "," +
                                        datasetEntry("clinics", 2, "household", 2),
                                )
                            )
                            path.endsWith("/push") ->
                                jsonResponse("""{"accepted":[],"rejected":[]}""")
                            path.contains("dv-villages-8") -> jsonResponse(
                                rowsBody("dv-villages-8", 3)
                            )
                            path.contains("dv-clinics-2") -> jsonResponse(
                                rowsBody("dv-clinics-2", 2)
                            )
                            else -> jsonResponse(documentBody("household", 1))
                        }
                    }
                }
            }
        ) {
            expectSuccess = true
            install(ContentNegotiation) { json(SyncJson) }
        }
        return SyncClient(
            fixture.submissions,
            fixedServerConfig("http://test"),
            fastRetry,
            httpClient = http,
            forms = fixture.forms,
            datasets = fixture.datasets,
        )
    }

    @Test
    fun `a work sync applies both manifests and downloads neither a document nor a row`() =
        runBlocking {
            val fixture = Fixture()
            val seen = mutableListOf<String>()

            val result = client(fixture, seen).syncWork()

            assertNull(result.error)
            assertEquals(0, result.fetchedForms)
            assertEquals(0, result.fetchedDatasetRows)
            assertTrue(
                seen.none { it.contains("/forms/versions/") || it.contains("/datasets/") },
                "a work sync spent bytes on a document or a list: $seen",
            )

            // What it DID do is know what is missing, which is the whole point:
            // the manifests are a few hundred bytes and they are what make the
            // other two actions honest.
            val deployed = fixture.forms.deployedNotHeld()
            assertEquals(listOf("fv-household-1"), deployed.map { it.formVersionId })
            assertEquals(
                listOf("clinics", "villages"),
                fixture.referenceData.pendingFetches().map { it.list.datasetKey },
            )
        }

    @Test
    fun `updating forms asks for no ops, fetches the document, and names what it now needs`() =
        runBlocking {
            val fixture = Fixture()
            val seen = mutableListOf<String>()
            val client = client(fixture, seen)

            val result = client.updateForms()

            assertNull(result.error)
            assertEquals(1, result.fetched)
            assertNotNull(fixture.forms.find("household", 1)?.irJson)
            // limit=0: the manifests and nothing else. A person who tapped
            // "update forms" spends bytes on the form, not the op stream.
            assertTrue(seen.any { it == "/api/v1/sync/pull?0" }, "not a manifest-only pull: $seen")
            assertTrue(seen.none { it.endsWith("/push?") }, "a form update pushed: $seen")

            // And the gap the new form just created is named, while the person
            // is still standing somewhere with a connection.
            assertEquals(
                listOf("clinics", "villages"),
                result.nowNeeded.map { it.list.datasetKey },
            )
        }

    @Test
    fun `reference data is fetched one list at a time`() = runBlocking {
        val fixture = Fixture()
        val seen = mutableListOf<String>()
        val client = client(fixture, seen)
        client.updateForms()

        val villages = client.updateReferenceData("villages")

        assertNull(villages.error)
        assertEquals(3, villages.fetched)
        assertTrue(
            seen.none { it.contains("dv-clinics-2") },
            "asking for villages fetched the other list too: $seen",
        )
        // Villages is served; clinics is still waiting and still says so.
        assertEquals(listOf("V1", "V2", "V3"), fixture.datasets.rowsFor("fv-household-1", "villages").map { it.first })
        assertTrue(fixture.datasets.rowsFor("fv-household-1", "clinics").isEmpty())
        assertEquals(listOf("clinics"), villages.nowNeeded.map { it.list.datasetKey })

        assertNull(client.updateReferenceData("clinics").error)
        assertTrue(fixture.referenceData.pendingFetches().isEmpty())
    }

    @Test
    fun `each scope keeps its own status`() = runBlocking {
        val fixture = Fixture()
        val seen = mutableListOf<String>()
        val client = client(fixture, seen)

        client.syncWork()
        client.updateForms()

        val statuses = fixture.submissions.scopeStatuses().associateBy { it.scope }
        assertNotNull(statuses[SyncScope.WORK]?.lastOkAt, "work did not record a success")
        assertNotNull(statuses[SyncScope.FORMS]?.lastOkAt, "forms did not record a success")
        // Reference data was never asked for, so it says nothing rather than
        // "up to date" — the difference the whole screen rests on.
        assertNull(statuses[SyncScope.DATASETS]?.lastOkAt)
    }

    @Test
    fun `what a fetch will cost is answerable before it is asked for`() = runBlocking {
        val fixture = Fixture()
        val seen = mutableListOf<String>()
        val client = client(fixture, seen)
        client.updateForms()

        // Nothing of either list is held, so there is no measured row to
        // estimate bytes from, and the honest line is the row count.
        val first = fixture.referenceData.pendingFetches().first { it.list.datasetKey == "villages" }
        assertNull(first.deltaBaseVersion)
        assertEquals("villages v8 — not downloaded", first.statusLine)
        assertEquals("Full download — 3 rows.", first.costLine)

        // Once rows OF THAT LIST are on the device, the estimate is measured
        // off them. Deliberately per list and not across lists: a village row
        // and a facility row do not weigh the same, and borrowing one for the
        // other would put a confident wrong number on the button.
        fixture.datasets.appendRows(
            "dv-villages-8",
            listOf("V1" to """{"name":"V1","label":"Village 1","district":"D"}"""),
            nextCursor = "resume-here",
        )
        val partial = fixture.referenceData.pendingFetches()
            .first { it.list.datasetKey == "villages" }
        assertEquals("villages v8 — 1 of 3 rows", partial.statusLine)
        assertNotNull(partial.estimatedFullBytes, "no estimate from rows this device holds")
        assertTrue(partial.costLine.startsWith("Full download — about "), partial.costLine)
        // And the other list, of which nothing is held, still refuses to guess.
        val clinics = fixture.referenceData.pendingFetches()
            .first { it.list.datasetKey == "clinics" }
        assertNull(clinics.estimatedFullBytes)
    }

    @Test
    fun `a list this device has an older whole copy of is offered as an update, not a download`() {
        val fixture = Fixture()
        // v7 held whole, v8 pinned by the form and not here: the ordinary
        // weekly case, and the one where the cost differs by two orders of
        // magnitude. The line has to say which it is before it is tapped.
        fixture.datasets.applyManifest(
            listOf(
                DatasetManifestEntry("fv-old-1", "villages", "dv-villages-7", 7, 2, "sha256:v7"),
            )
        )
        fixture.datasets.appendRows(
            "dv-villages-7",
            listOf("V1" to """{"name":"Village 1"}""", "V2" to """{"name":"Village 2"}"""),
            nextCursor = null,
        )
        fixture.forms.applyManifest(
            listOf(FormManifestEntry("fv-household-1", "household", 1, "Household", "sha256:h1")),
            mapOf("fv-household-1" to """{"formId":"household"}"""),
        )
        fixture.datasets.applyManifest(
            listOf(
                DatasetManifestEntry(
                    "fv-household-1", "villages", "dv-villages-8", 8, 38_000, "sha256:v8",
                ),
            )
        )

        val pending = fixture.referenceData.pendingFetches().single()

        assertEquals(7, pending.deltaBaseVersion)
        assertTrue(
            pending.costLine.startsWith("Update from v7 — only the rows that changed."),
            pending.costLine,
        )
        assertTrue(pending.costLine.contains("The whole list is about "), pending.costLine)
    }

    @Test
    fun `a size below a kilobyte is said in bytes, not rounded away to zero`() {
        // "about 0 KB" reads as "this costs nothing", which is a different
        // claim from "this is small" and the wrong one to put on a button.
        // Seen on a device against a three-row list.
        assertEquals("150 bytes", formatBytes(150))
        assertEquals("1.0 KB", formatBytes(1024))
        assertEquals("11.3 MB", formatBytes(11_849_297))
    }
}
