package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.form.FormValue
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.content.TextContent
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

class SyncClientTest {

    private val fastRetry = SyncConfig(batchSize = 2, maxAttempts = 3, baseDelayMs = 1)

    private fun store(): SubmissionStore {
        val driver = JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema)
        return SubmissionStore(DcpDatabase(driver), deviceIdOverride = "dev-test")
    }

    private fun seedOps(store: SubmissionStore, count: Int): List<SyncOp> {
        val submission = store.createDraft("f", 1)
        return (1..count).map {
            store.appendOp(submission, "f", 1, OpKind.SET, "q$it", FormValue.Integer(it.toLong()))
        }
    }

    private fun client(
        store: SubmissionStore,
        config: SyncConfig = fastRetry,
        /** Answers POST /api/v1/devices; defaults to accepting registration. */
        registrationHandler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData = {
            jsonResponse("""{"deviceId":"dev-test","status":"registered"}""")
        },
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ): SyncClient {
        val http = HttpClient(
            MockEngine { request ->
                when {
                    request.url.encodedPath.endsWith("/devices") -> registrationHandler(request)
                    // Every sync asks for the project's security mode before it
                    // pushes anything (sync §4). These tests are all `standard`.
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
        return SyncClient(store, { "http://test" }, config, httpClient = http)
    }

    // ------------------------------------------------------------------
    // The server address is asked for, not held.
    //
    // Two properties, and they pull in opposite directions, which is why both
    // are here. The client must *not* cache the address across syncs — the
    // settings screen would then need an app restart to take effect, on the one
    // screen whose whole purpose is to fix an address that is not working. And
    // it must cache it *within* one sync — see the note in syncOnce.
    // ------------------------------------------------------------------

    @Test
    fun `a changed address is picked up by the next sync, with no new client`() = runBlocking {
        val store = store()
        seedOps(store, 1)
        val hosts = mutableListOf<String>()
        var address = "http://first.example"

        val http = HttpClient(
            MockEngine { request ->
                hosts += request.url.host
                when {
                    request.url.encodedPath.endsWith("/devices") ->
                        jsonResponse("""{"deviceId":"dev-test","status":"registered"}""")
                    request.url.encodedPath.endsWith("/crypto") -> jsonResponse(
                        """{"deviceId":"dev-test","projectId":"prj","securityMode":"standard",
                            "projectKeys":[]}"""
                    )
                    request.url.encodedPath.endsWith("/push") ->
                        jsonResponse("""{"accepted":[],"rejected":[]}""")
                    else -> jsonResponse(emptyPull())
                }
            }
        ) {
            expectSuccess = true
            install(ContentNegotiation) { json(SyncJson) }
        }
        // The one object, for both syncs — exactly as AppGraph holds it.
        val client = SyncClient(store, { address }, fastRetry, httpClient = http)

        client.syncOnce()
        assertTrue(hosts.all { it == "first.example" }, "first sync went to $hosts")

        address = "http://second.example"
        hosts.clear()
        client.syncOnce()

        assertTrue(
            hosts.isNotEmpty() && hosts.all { it == "second.example" },
            "a saved address must take effect on the next sync, not the next launch: $hosts",
        )
    }

    @Test
    fun `an address changed mid-sync does not split one sync across two servers`() = runBlocking {
        // The reason the address is read once per pass rather than per request.
        // refreshCrypto caches the recipient set of the project the server
        // names and the push encrypts to it, so a sync split across two servers
        // could wrap content keys to one project and hand the ciphertext to
        // another — which stores it, reports success, and is holding answers
        // only a third party can ever open.
        val store = store()
        seedOps(store, 1)
        val hosts = mutableListOf<String>()
        var address = "http://first.example"

        val http = HttpClient(
            MockEngine { request ->
                hosts += request.url.host
                // Change it under the client, after the very first request.
                address = "http://second.example"
                when {
                    request.url.encodedPath.endsWith("/devices") ->
                        jsonResponse("""{"deviceId":"dev-test","status":"registered"}""")
                    request.url.encodedPath.endsWith("/crypto") -> jsonResponse(
                        """{"deviceId":"dev-test","projectId":"prj","securityMode":"standard",
                            "projectKeys":[]}"""
                    )
                    request.url.encodedPath.endsWith("/push") ->
                        jsonResponse("""{"accepted":[],"rejected":[]}""")
                    else -> jsonResponse(emptyPull())
                }
            }
        ) {
            expectSuccess = true
            install(ContentNegotiation) { json(SyncJson) }
        }

        SyncClient(store, { address }, fastRetry, httpClient = http).syncOnce()

        assertTrue(hosts.size > 1, "expected several requests in one sync, got $hosts")
        assertEquals(
            setOf("first.example"),
            hosts.toSet(),
            "one sync must talk to one server",
        )
    }

    @Test
    fun `a failed sync reports the address it tried and the original message`() = runBlocking {
        // Before SyncFailure this recorded `Connect timeout has expired`, which
        // names no server and suggests no fix.
        val store = store()
        seedOps(store, 1)
        val http = HttpClient(
            MockEngine { throw java.net.ConnectException("Connection refused") }
        ) {
            expectSuccess = true
            install(ContentNegotiation) { json(SyncJson) }
        }

        val result = SyncClient(
            store,
            { "http://192.168.1.20:8000" },
            SyncConfig(maxAttempts = 1),
            httpClient = http,
        ).syncOnce()

        val error = assertNotNull(result.error)
        assertTrue("192.168.1.20:8000" in error, "the address must be named: $error")
        assertTrue("Connection refused" in error, "the original must survive: $error")
        // And it is what the screen reads back.
        assertEquals(error, store.syncStatus().lastError)
    }

    private fun MockRequestHandleScope.jsonResponse(body: String): HttpResponseData =
        respond(body, headers = headersOf(HttpHeaders.ContentType, "application/json"))

    private fun requestedOpIds(request: HttpRequestData): List<String> {
        val body = (request.body as TextContent).text
        return SyncJson.decodeFromString(WirePushRequest.serializer(), body).ops.map { it.opId }
    }

    private fun emptyPull(cursor: Long = 7) =
        """{"ops":[],"tombstones":[],"nextCursor":$cursor,"hasMore":false}"""

    @Test
    fun `only server-acknowledged ops leave the outbox`() = runBlocking {
        val store = store()
        val ops = seedOps(store, 2)
        val client = client(store) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                val (first, second) = requestedOpIds(request)
                jsonResponse(
                    """{"accepted":["$first"],
                        "rejected":[{"opId":"$second","reason":"unknown_form_version"}],
                        "serverCursor":1}"""
                )
            } else jsonResponse(emptyPull())
        }

        val result = client.syncOnce()

        assertNull(result.error)
        assertEquals(1, result.pushedOps)
        assertEquals(1, result.rejectedOps)
        val states = store.opsFor(ops[0].submissionId).associateBy { it.opId }
        assertTrue(states.getValue(ops[0].opId).synced)
        // the rejected op stays in the outbox, unsynced, with the reason kept
        assertEquals(1, store.pendingCount())
        assertEquals(false, states.getValue(ops[1].opId).synced)
        assertEquals("unknown_form_version", states.getValue(ops[1].opId).rejectReason)
        assertEquals(
            listOf(RejectedOpGroup("unknown_form_version", 1)),
            store.rejectedOpSummary(),
        )
    }

    @Test
    fun `server accepting three of five leaves two pending with their reason`() = runBlocking {
        val store = store()
        val ops = seedOps(store, 5)
        val client = client(store, config = SyncConfig(batchSize = 5, maxAttempts = 1)) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                val ids = requestedOpIds(request)
                val accepted = ids.take(3).joinToString(",") { "\"$it\"" }
                val rejected = ids.drop(3)
                    .joinToString(",") { """{"opId":"$it","reason":"not_authorized"}""" }
                jsonResponse("""{"accepted":[$accepted],"rejected":[$rejected],"serverCursor":1}""")
            } else jsonResponse(emptyPull())
        }

        val result = client.syncOnce()

        assertNull(result.error)
        assertEquals(3, result.pushedOps)
        assertEquals(2, result.rejectedOps)
        assertEquals(2, store.pendingCount())
        val states = store.opsFor(ops[0].submissionId).associateBy { it.opId }
        ops.take(3).forEach { assertTrue(states.getValue(it.opId).synced) }
        ops.drop(3).forEach {
            assertEquals(false, states.getValue(it.opId).synced)
            assertEquals("not_authorized", states.getValue(it.opId).rejectReason)
        }
        assertEquals(listOf(RejectedOpGroup("not_authorized", 2)), store.rejectedOpSummary())
    }

    @Test
    fun `a non-2xx response marks nothing synced`() = runBlocking {
        val store = store()
        seedOps(store, 3)
        val client = client(store, config = SyncConfig(maxAttempts = 1)) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                respond(
                    """{"accepted":["should","be","ignored"],"rejected":[],"serverCursor":1}""",
                    HttpStatusCode.InternalServerError,
                    headersOf(HttpHeaders.ContentType, "application/json"),
                )
            } else jsonResponse(emptyPull())
        }

        val result = client.syncOnce()

        assertNotNull(result.error)
        assertEquals(0, result.pushedOps)
        assertEquals(3, store.pendingCount())
        assertTrue(store.opsFor(store.pendingOps(10).first().submissionId).none { it.synced })
    }

    @Test
    fun `an op rejected then accepted on retry ends up synced exactly once`() = runBlocking {
        val store = store()
        val op = seedOps(store, 1).single()
        val rejecting = client(store) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                jsonResponse(
                    """{"accepted":[],
                        "rejected":[{"opId":"${op.opId}","reason":"not_authorized"}],
                        "serverCursor":1}"""
                )
            } else jsonResponse(emptyPull())
        }
        assertNull(rejecting.syncOnce().error)
        assertEquals(1, store.pendingCount())

        // the device is authorized in the meantime; the retry pushes the op
        // again — exactly once — and acceptance clears the recorded reason
        val pushedIds = mutableListOf<String>()
        val accepting = client(store) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                val ids = requestedOpIds(request)
                pushedIds += ids
                jsonResponse(
                    """{"accepted":[${ids.joinToString(",") { "\"$it\"" }}],
                        "rejected":[],"serverCursor":2}"""
                )
            } else jsonResponse(emptyPull())
        }
        val retry = accepting.syncOnce()

        assertNull(retry.error)
        assertEquals(1, retry.pushedOps)
        assertEquals(listOf(op.opId), pushedIds)
        assertEquals(0, store.pendingCount())
        val stored = store.opsFor(op.submissionId).single()
        assertTrue(stored.synced)
        assertNull(stored.rejectReason)
        assertTrue(store.rejectedOpSummary().isEmpty())
    }

    @Test
    fun `a fresh device registers before its first push and only once`() = runBlocking {
        val store = store()
        seedOps(store, 1)
        val paths = mutableListOf<String>()
        fun syncingClient() = client(
            store,
            registrationHandler = { request ->
                paths += request.url.encodedPath
                jsonResponse("""{"deviceId":"dev-test","status":"registered"}""")
            },
        ) { request ->
            paths += request.url.encodedPath
            if (request.url.encodedPath.endsWith("/push")) {
                val ids = requestedOpIds(request).joinToString(",") { "\"$it\"" }
                jsonResponse("""{"accepted":[$ids],"rejected":[],"serverCursor":1}""")
            } else jsonResponse(emptyPull())
        }

        assertNull(syncingClient().syncOnce().error)
        assertEquals(
            listOf("/api/v1/devices", "/api/v1/sync/push", "/api/v1/sync/pull"),
            paths,
        )

        // registration is remembered: the next sync goes straight to pull
        assertNull(syncingClient().syncOnce().error)
        assertEquals("/api/v1/sync/pull", paths.last())
        assertEquals(1, paths.count { it == "/api/v1/devices" })
    }

    @Test
    fun `already registered counts as a successful registration`() = runBlocking {
        val store = store()
        seedOps(store, 1)
        val client = client(
            store,
            registrationHandler = {
                jsonResponse("""{"deviceId":"dev-test","status":"already_registered"}""")
            },
        ) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                val ids = requestedOpIds(request).joinToString(",") { "\"$it\"" }
                jsonResponse("""{"accepted":[$ids],"rejected":[],"serverCursor":1}""")
            } else jsonResponse(emptyPull())
        }

        val result = client.syncOnce()

        assertNull(result.error)
        assertEquals(1, result.pushedOps)
        assertEquals(0, store.pendingCount())
    }

    @Test
    fun `a refused registration reports the server's reason, not the status code`() = runBlocking {
        val store = store()
        seedOps(store, 2)
        var registrationAttempts = 0
        val client = client(
            store,
            registrationHandler = {
                registrationAttempts++
                respond(
                    """{"detail":{"reason":"project_not_found",
                        "message":"The server has no active project to register this device
                        against. Run scripts/seed_dev.py to create the development project."}}""",
                    HttpStatusCode.Conflict,
                    headersOf(HttpHeaders.ContentType, "application/json"),
                )
            },
        ) { jsonResponse(emptyPull()) }

        val result = client.syncOnce()

        assertEquals("project_not_found", result.registrationFailure)
        val error = assertNotNull(result.error)
        assertTrue(error.contains("project_not_found"), "reason is in the message: $error")
        assertTrue(error.contains("seed_dev.py"), "server's advice survives: $error")
        assertEquals(false, error.contains("409"), "not reported as a bare status: $error")
        assertEquals(error, store.syncStatus().lastError)
        // A refusal is a decision, not a hiccup — it must not be retried.
        assertEquals(1, registrationAttempts)
        assertEquals(2, store.pendingCount())
    }

    @Test
    fun `a refusal with no structured body still reports something usable`() = runBlocking {
        val store = store()
        seedOps(store, 1)
        val client = client(
            store,
            registrationHandler = { respond("<html>502 from a proxy</html>", HttpStatusCode.BadGateway) },
        ) { jsonResponse(emptyPull()) }

        val result = client.syncOnce()

        assertNull(result.registrationFailure) // no machine-readable reason to report
        val error = assertNotNull(result.error)
        assertTrue(error.contains("502"), "falls back to the status: $error")
        assertTrue(error.contains("proxy"), "keeps the raw body: $error")
    }

    @Test
    fun `failed registration pushes nothing and is retried next sync`() = runBlocking {
        val store = store()
        seedOps(store, 2)
        var pushAttempted = false
        val failing = client(
            store,
            config = SyncConfig(maxAttempts = 1),
            registrationHandler = {
                respond("device registry down", HttpStatusCode.InternalServerError)
            },
        ) { request ->
            if (request.url.encodedPath.endsWith("/push")) pushAttempted = true
            jsonResponse(emptyPull())
        }

        val failed = failing.syncOnce()

        assertNotNull(failed.error)
        assertEquals(false, pushAttempted)
        assertEquals(2, store.pendingCount())

        // the server recovers: registration happens on the next sync, then push
        val recovered = client(store) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                val ids = requestedOpIds(request).joinToString(",") { "\"$it\"" }
                jsonResponse("""{"accepted":[$ids],"rejected":[],"serverCursor":1}""")
            } else jsonResponse(emptyPull())
        }
        assertNull(recovered.syncOnce().error)
        assertEquals(0, store.pendingCount())
    }

    @Test
    fun `mid-batch failure keeps unacked ops pending and loses nothing`() = runBlocking {
        val store = store()
        seedOps(store, 5) // batchSize 2 -> batches of 2, 2, 1
        var pushCalls = 0
        val client = client(store) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                pushCalls++
                if (pushCalls == 1) {
                    val ids = requestedOpIds(request).joinToString(",") { "\"$it\"" }
                    jsonResponse("""{"accepted":[$ids],"rejected":[],"serverCursor":1}""")
                } else throw IOException("server went away") // mid-batch outage
            } else jsonResponse(emptyPull())
        }

        val result = client.syncOnce()

        assertNotNull(result.error)
        assertEquals(2, result.pushedOps)
        assertEquals(3, store.pendingCount()) // unacked ops all still pending
        assertNotNull(store.syncStatus().lastError)

        // server "comes back": everything drains, and only pending ops are
        // re-sent — the acked batch is never pushed twice
        val resent = mutableListOf<String>()
        val recovered = client(store) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                val ids = requestedOpIds(request)
                resent += ids
                jsonResponse(
                    """{"accepted":[${ids.joinToString(",") { "\"$it\"" }}],
                        "rejected":[],"serverCursor":1}"""
                )
            } else jsonResponse(emptyPull())
        }
        val second = recovered.syncOnce()

        assertNull(second.error)
        assertEquals(3, second.pushedOps)
        assertEquals(0, store.pendingCount())
        assertEquals(3, resent.size, "only the unacked ops are re-sent")
        assertEquals(resent.distinct(), resent)
        assertNull(store.syncStatus().lastError) // success clears the error
    }

    @Test
    fun `pull cursor persists with the batch and resumes across restarts`() = runBlocking {
        val store = store()
        val cursorsSeen = mutableListOf<Long>()
        fun pullingClient() = client(store) { request ->
            cursorsSeen += request.url.parameters["cursor"]!!.toLong()
            when (cursorsSeen.size) {
                1 -> jsonResponse(
                    """{"ops":[{"opId":"01REMOTE1","submissionId":"01RSUB","formId":"f",
                        "formVersion":1,"kind":"set","path":"name","value":"remote",
                        "deviceId":"dev-other","actorId":"usr-2","counter":1,
                        "wallClock":"2026-08-29T10:00:00Z","serverSeq":41}],
                        "tombstones":[],"nextCursor":41,"hasMore":true}"""
                )
                else -> jsonResponse(emptyPull(cursor = 55))
            }
        }

        assertNull(pullingClient().syncOnce().error)
        assertEquals(listOf(0L, 41L), cursorsSeen)
        assertEquals(55L, store.syncStatus().pullCursor)

        // a "restarted" client resumes from the persisted cursor
        assertNull(pullingClient().syncOnce().error)
        assertEquals(55L, cursorsSeen.last())

        // the pulled remote op was durably stored and folds into local state
        assertEquals(
            mapOf("name" to FormValue.Text("remote")),
            store.materialisedAnswers("01RSUB"),
        )
    }

    @Test
    fun `transient failures are retried with backoff until they succeed`() = runBlocking {
        val store = store()
        seedOps(store, 1)
        var attempts = 0
        val client = client(store) { request ->
            if (request.url.encodedPath.endsWith("/push")) {
                attempts++
                if (attempts < 3) throw IOException("flaky network")
                val ids = requestedOpIds(request).joinToString(",") { "\"$it\"" }
                jsonResponse("""{"accepted":[$ids],"rejected":[],"serverCursor":1}""")
            } else jsonResponse(emptyPull())
        }

        val result = client.syncOnce()

        assertNull(result.error)
        assertEquals(3, attempts)
        assertEquals(0, store.pendingCount())
    }
}
