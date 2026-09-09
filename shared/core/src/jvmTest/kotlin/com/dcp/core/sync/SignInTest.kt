package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import io.ktor.client.HttpClient
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.MockRequestHandleScope
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.contentnegotiation.ContentNegotiation
import io.ktor.client.plugins.cookies.HttpCookies
import io.ktor.client.request.HttpRequestData
import io.ktor.client.request.HttpResponseData
import io.ktor.http.ContentType
import io.ktor.http.HttpHeaders
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import io.ktor.serialization.kotlinx.json.json
import io.ktor.utils.io.core.toByteArray
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertTrue
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.Json

/**
 * Signing in from the handset (proposal §4): one POST naming the device, a
 * cookie the server sets and this client carries back, and a refusal handed
 * to the screen as the reason the server gave.
 */
class SignInTest {

    private val json = Json { ignoreUnknownKeys = true }

    private fun database() =
        DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema))

    private fun MockRequestHandleScope.jsonResponse(
        body: String,
        status: HttpStatusCode = HttpStatusCode.OK,
        cookie: String? = null,
    ): HttpResponseData {
        val headers = if (cookie == null) {
            headersOf(HttpHeaders.ContentType, ContentType.Application.Json.toString())
        } else {
            headersOf(
                HttpHeaders.ContentType to listOf(ContentType.Application.Json.toString()),
                HttpHeaders.SetCookie to listOf(cookie),
            )
        }
        return respond(body.toByteArray(), status, headers)
    }

    private fun client(
        session: SessionStore,
        store: SubmissionStore,
        handler: suspend MockRequestHandleScope.(HttpRequestData) -> HttpResponseData,
    ): SyncClient {
        val http = HttpClient(MockEngine { request -> handler(request) }) {
            expectSuccess = true
            install(ContentNegotiation) { json(SyncJson) }
            install(HttpCookies) { storage = session.cookies }
        }
        return SyncClient(
            store,
            fixedServerConfig("http://test"),
            SyncConfig(maxAttempts = 1, baseDelayMs = 1),
            httpClient = http,
            session = session,
        )
    }

    @Test
    fun `the login names the device, the cookie is kept, and the next request carries it`() = runBlocking {
        val db = database()
        val store = SubmissionStore(db, deviceIdOverride = "dev-test")
        val session = SessionStore(db)
        val seen = mutableListOf<Pair<String, String?>>()

        val sync = client(session, store) { request ->
            seen += request.url.encodedPath to request.headers[HttpHeaders.Cookie]
            when {
                request.url.encodedPath.endsWith("/devices") ->
                    jsonResponse("""{"deviceId":"dev-test","status":"registered"}""")
                request.url.encodedPath.endsWith("/auth/login") -> {
                    val body = json.decodeFromString<WireLoginRequest>(
                        String((request.body as io.ktor.http.content.OutgoingContent.ByteArrayContent).bytes()),
                    )
                    assertEquals("amina", body.username)
                    assertEquals("app", body.kind)
                    assertEquals("dev-test", body.deviceId)
                    jsonResponse(
                        """{"userId":"u1","username":"amina","displayName":"Amina",
                           "sessionKind":"app","deviceId":"dev-test","scopeKind":"team",
                           "permissions":[],"expiresAt":"2026-10-09T00:00:00Z"}""",
                        cookie = "dcp_session=tok-1; HttpOnly; Path=/api; SameSite=strict; Max-Age=3600",
                    )
                }
                request.url.encodedPath.endsWith("/crypto") -> jsonResponse(
                    """{"deviceId":"dev-test","projectId":"prj","securityMode":"standard","projectKeys":[]}""",
                )
                request.url.encodedPath.endsWith("/pull") ->
                    jsonResponse("""{"ops":[],"tombstones":[],"nextCursor":0,"hasMore":false}""")
                else -> jsonResponse("{}")
            }
        }

        val result = sync.signIn("amina", "pw")
        assertIs<SignInResult.Signed>(result)
        assertEquals("Amina", session.signedIn()?.displayName)

        // The device introduced itself first, then logged in; the login carried no cookie.
        assertEquals(listOf("/api/v1/devices", "/api/v1/auth/login"), seen.map { it.first })
        assertEquals(null, seen[1].second)

        // And the sync that follows carries the session on every request.
        sync.syncOnce()
        val afterLogin = seen.drop(2)
        assertTrue(afterLogin.isNotEmpty())
        afterLogin.forEach { (path, cookie) ->
            assertTrue(cookie != null && "dcp_session=tok-1" in cookie, "no session on $path")
        }
    }

    @Test
    fun `a refusal is the server's reason, and a pending account is told so`() = runBlocking {
        val db = database()
        val store = SubmissionStore(db, deviceIdOverride = "dev-test")
        val session = SessionStore(db)
        val sync = client(session, store) { request ->
            when {
                request.url.encodedPath.endsWith("/devices") ->
                    jsonResponse("""{"deviceId":"dev-test","status":"registered"}""")
                else -> jsonResponse(
                    """{"detail":{"reason":"pending_approval","message":"waiting"}}""",
                    status = HttpStatusCode.Forbidden,
                )
            }
        }
        val result = sync.signIn("new", "pw")
        assertIs<SignInResult.Refused>(result)
        assertEquals("pending_approval", result.reason)
        assertEquals(null, session.signedIn())
    }

    @Test
    fun `a sync with no session says so, and points at the settings screen`() = runBlocking {
        val db = database()
        val store = SubmissionStore(db, deviceIdOverride = "dev-test")
        store.createDraft("f", 1)
        val session = SessionStore(db)
        val sync = client(session, store) { request ->
            when {
                request.url.encodedPath.endsWith("/devices") ->
                    jsonResponse("""{"deviceId":"dev-test","status":"registered"}""")
                else -> jsonResponse(
                    """{"detail":{"reason":"not_signed_in","message":"Sign in to continue."}}""",
                    status = HttpStatusCode.Unauthorized,
                )
            }
        }
        sync.syncOnce()
        val error = store.syncStatus().lastError ?: ""
        assertTrue("Not signed in" in error, error)
        assertTrue("Settings" in error, error)
    }
}
