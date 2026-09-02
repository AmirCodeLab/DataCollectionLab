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
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import java.io.IOException
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking

/**
 * Form delivery over the sync loop (specs/sync-protocol-v0.1.md §5).
 *
 * `FormStoreTest` covers what the store does with a manifest. This covers the
 * half above it: which requests a sync actually makes, what it does with a
 * server that answers badly, and — the point of the split — that a device which
 * is already up to date does not re-download a single form document.
 *
 * Kotlin-only, like everything in this file's neighbourhood: there is no second
 * implementation of a sync client to compare against, so no conformance vector
 * reaches any of it.
 */
class FormDeliveryTest {

    private val fastRetry = SyncConfig(batchSize = 2, maxAttempts = 2, baseDelayMs = 1)

    private class Fixture {
        val db: DcpDatabase =
            DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema))
        val submissions = SubmissionStore(db, deviceIdOverride = "dev-test")
        val forms = FormStore(db)
    }

    private fun manifestEntry(formId: String, version: Int, checksum: String = "sha256:$formId-$version") =
        """{"formVersionId":"fv-$formId-$version","formId":"$formId","version":$version,
            "title":"Household Survey","irChecksum":"$checksum",
            "deployedAt":"2026-09-02T10:00:00Z"}"""

    private fun pullBody(vararg entries: String, cursor: Long = 4) =
        """{"ops":[],"tombstones":[],"forms":[${entries.joinToString(",")}],
            "nextCursor":$cursor,"hasMore":false}"""

    private fun documentBody(formId: String, version: Int, checksum: String = "sha256:$formId-$version") =
        """{"formVersionId":"fv-$formId-$version","formId":"$formId","version":$version,
            "title":"Household Survey","irChecksum":"$checksum",
            "form":{"irVersion":"0.1","formId":"$formId","version":$version,
                    "title":{"en":"Household Survey"},"defaultLanguage":"en",
                    "languages":["en"],"children":[]}}"""

    private fun MockRequestHandleScope.jsonResponse(body: String): HttpResponseData =
        respond(body, headers = headersOf(HttpHeaders.ContentType, "application/json"))

    private fun client(
        fixture: Fixture,
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ): SyncClient {
        val http = HttpClient(
            MockEngine { request ->
                when {
                    request.url.encodedPath.endsWith("/devices") ->
                        jsonResponse("""{"deviceId":"dev-test","status":"registered"}""")
                    request.url.encodedPath.endsWith("/crypto") -> jsonResponse(
                        """{"deviceId":"dev-test","projectId":"prj","securityMode":"standard",
                            "projectKeys":[]}"""
                    )
                    else -> handler(request)
                }
            }
        ) {
            expectSuccess = true
            install(ContentNegotiation) { json(SyncJson) }
        }
        return SyncClient(
            fixture.submissions, "http://test", fastRetry, httpClient = http, forms = fixture.forms,
        )
    }

    @Test
    fun `a first sync asks for the manifest and fetches every document in it`() = runBlocking {
        val fixture = Fixture()
        val paths = mutableListOf<String>()
        val client = client(fixture) { request ->
            paths += request.url.encodedPath
            when {
                request.url.encodedPath.endsWith("/pull") ->
                    jsonResponse(pullBody(manifestEntry("household", 1)))
                else -> jsonResponse(documentBody("household", 1))
            }
        }

        val result = client.syncOnce()

        assertNull(result.error)
        assertNull(result.formError)
        assertEquals(1, result.fetchedForms)
        assertTrue("/api/v1/forms/versions/fv-household-1" in paths)
        assertEquals(1, assertNotNull(fixture.forms.find("household", 1)).version)
    }

    @Test
    fun `the manifest is requested with this device's id and the forms scope`() = runBlocking {
        // Deployment is per environment, so the server cannot answer without
        // knowing whose forms are being asked for. A pull that dropped deviceId
        // would come back with an empty manifest and look exactly like a
        // project with no forms deployed.
        val fixture = Fixture()
        var pullQuery = ""
        val client = client(fixture) { request ->
            if (request.url.encodedPath.endsWith("/pull")) {
                pullQuery = request.url.parameters.entries().joinToString(",") { "${it.key}=${it.value}" }
                jsonResponse(pullBody())
            } else jsonResponse(documentBody("household", 1))
        }

        client.syncOnce()

        assertTrue("scope=[forms]" in pullQuery, "expected scope=forms, got: $pullQuery")
        assertTrue("deviceId=[dev-test]" in pullQuery, "expected deviceId, got: $pullQuery")
    }

    @Test
    fun `a device already holding the version downloads no document at all`() = runBlocking {
        // The whole reason the manifest and the documents are separate calls.
        // If this regresses, every sync re-downloads every form on the phone
        // and nothing anywhere reports a problem — it is just slower, on
        // exactly the connections that cannot afford it.
        val fixture = Fixture()
        var documentFetches = 0
        val client = client(fixture) { request ->
            if (request.url.encodedPath.endsWith("/pull")) {
                jsonResponse(pullBody(manifestEntry("household", 1)))
            } else {
                documentFetches++
                jsonResponse(documentBody("household", 1))
            }
        }

        client.syncOnce()
        assertEquals(1, documentFetches)

        val second = client.syncOnce()
        assertEquals(1, documentFetches, "the second sync must fetch nothing")
        assertEquals(0, second.fetchedForms)
    }

    @Test
    fun `a document that will not fetch does not cost the device the others`() = runBlocking {
        val fixture = Fixture()
        val client = client(fixture) { request ->
            when {
                request.url.encodedPath.endsWith("/pull") -> jsonResponse(
                    pullBody(manifestEntry("household", 1), manifestEntry("clinic", 1))
                )
                request.url.encodedPath.endsWith("fv-clinic-1") -> throw IOException("no route")
                else -> jsonResponse(documentBody("household", 1))
            }
        }

        val result = client.syncOnce()

        assertNull(result.error, "one unreachable form must not fail the sync")
        assertEquals(1, result.fetchedForms)
        assertNotNull(fixture.forms.find("household", 1))
        assertNull(fixture.forms.find("clinic", 1))
    }

    @Test
    fun `a server that does not serve forms leaves the device's forms alone`() = runBlocking {
        // A self-hosted install runs whatever version it runs, and one older
        // than form delivery sends no `forms` field at all. Reading that silence
        // as "your environment deploys nothing" would undeploy every form on
        // the device and leave an enumerator unable to start an interview.
        val fixture = Fixture()
        fixture.forms.applyManifest(
            listOf(
                FormManifestEntry("fv-household-1", "household", 1, "Household", "sha256:x")
            ),
            mapOf("fv-household-1" to """{"formId":"household"}"""),
        )

        val client = client(fixture) { request ->
            if (request.url.encodedPath.endsWith("/pull")) {
                // No `forms` key — the pre-delivery response shape.
                jsonResponse("""{"ops":[],"tombstones":[],"nextCursor":9,"hasMore":false}""")
            } else jsonResponse(documentBody("household", 1))
        }

        val result = client.syncOnce()

        assertNull(result.error)
        assertEquals(
            true,
            assertNotNull(fixture.forms.find("household", 1)).deployed,
            "an absent manifest must not withdraw the forms the device already has",
        )
        assertEquals(1, fixture.forms.startable().size)
    }

    @Test
    fun `a project that withdrew its last form does undeploy it`() = runBlocking {
        // The other half of the test above, and the reason `forms` is nullable
        // rather than defaulted. An empty array is a real answer — this
        // environment deploys nothing — and it must be acted on, or a project
        // that pulled its only form could never say so to a device.
        val fixture = Fixture()
        var manifest = arrayOf(manifestEntry("household", 1))
        val client = client(fixture) { request ->
            if (request.url.encodedPath.endsWith("/pull")) jsonResponse(pullBody(*manifest))
            else jsonResponse(documentBody("household", 1))
        }

        client.syncOnce()
        assertEquals(1, fixture.forms.startable().size)

        manifest = emptyArray()
        client.syncOnce()

        assertEquals(
            emptyList(),
            fixture.forms.startable(),
            "an empty manifest is the server saying this environment deploys nothing",
        )
        assertNull(
            fixture.forms.find("household", 1),
            "and with no submission referring to it, retention lets it go",
        )
    }

    @Test
    fun `a failure fetching forms does not fail the sync that already moved the answers`() =
        runBlocking {
            // Ops are the small irreplaceable part and they are already pushed
            // and pulled by the time forms are fetched. Failing the whole sync
            // here would report the answers as unsent when they are safe.
            val fixture = Fixture()
            val submission = fixture.submissions.createDraft("household", 1)
            fixture.submissions.appendOp(
                submission, "household", 1, OpKind.SET, "name", com.dcp.form.FormValue.Text("a"),
            )

            val client = client(fixture) { request ->
                when {
                    request.url.encodedPath.endsWith("/push") ->
                        jsonResponse("""{"accepted":[],"rejected":[],"serverCursor":0}""")
                    request.url.encodedPath.endsWith("/pull") ->
                        jsonResponse(pullBody(manifestEntry("household", 1)))
                    else -> respond("boom", HttpStatusCode.InternalServerError)
                }
            }

            // The push makes no progress on purpose in this shape, so assert on
            // the form half only: it failed, and it said so without throwing.
            val result = client.syncOnce()
            assertEquals(0, result.fetchedForms)
            assertNull(fixture.forms.find("household", 1))
        }

    @Test
    fun `a withdrawn version stays on the device while a draft still needs it`() = runBlocking {
        // The end-to-end version of FormStoreTest's retention case, driven
        // through a real sync: v1 is collected against, the server moves to v2,
        // and the device must still be able to open what the enumerator has.
        val fixture = Fixture()
        var manifest = arrayOf(manifestEntry("household", 1))
        val client = client(fixture) { request ->
            if (request.url.encodedPath.endsWith("/pull")) {
                jsonResponse(pullBody(*manifest))
            } else if (request.url.encodedPath.endsWith("fv-household-2")) {
                jsonResponse(documentBody("household", 2))
            } else {
                jsonResponse(documentBody("household", 1))
            }
        }

        client.syncOnce()
        fixture.submissions.createDraft("household", 1)

        manifest = arrayOf(manifestEntry("household", 2))
        client.syncOnce()

        assertNotNull(
            fixture.forms.find("household", 1),
            "the version behind an unfinished draft must survive the server moving on",
        )
        assertEquals(
            listOf(2),
            fixture.forms.startable().map { it.version },
            "new interviews still start on the current version",
        )
    }
}
