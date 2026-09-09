package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import io.ktor.http.Cookie
import io.ktor.http.Url
import io.ktor.util.date.GMTDate
import io.ktor.util.date.getTimeMillis
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlinx.coroutines.runBlocking

/**
 * The session survives a restart, goes only to the host that set it, and can
 * be forgotten. Proposal §3.3: Ktor's own storage forgets on restart, and
 * this is the one class that is ours.
 */
class SessionStoreTest {

    private fun database() =
        DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema))

    private val server = Url("http://10.0.2.2:8000/api/v1/auth/login")

    @Test
    fun `a cookie set by the server is carried back to it, and survives a new store on the same database`() =
        runBlocking {
            val db = database()
            val first = SessionStore(db)
            first.cookies.addCookie(server, Cookie("dcp_session", "tok-1", path = "/api", maxAge = 3600))
            first.cookies.addCookie(server, Cookie("dcp_org", "dev", path = "/api", maxAge = 3600))

            // A restart: a new store over the same rows.
            val second = SessionStore(db)
            val sent = second.cookies.get(Url("http://10.0.2.2:8000/api/v1/sync/push"))
            assertEquals(setOf("dcp_session=tok-1", "dcp_org=dev"), sent.map { "${it.name}=${it.value}" }.toSet())
        }

    @Test
    fun `only the host that set the cookie gets it, and only under its path`() = runBlocking {
        val store = SessionStore(database())
        store.cookies.addCookie(server, Cookie("dcp_session", "tok-1", path = "/api", maxAge = 3600))

        assertEquals(emptyList(), store.cookies.get(Url("http://other.example:8000/api/v1/sync/push")))
        assertEquals(emptyList(), store.cookies.get(Url("http://10.0.2.2:8000/health")))
    }

    @Test
    fun `an expired cookie is not sent, and a past expiry deletes one`() = runBlocking {
        val store = SessionStore(database())
        store.cookies.addCookie(server, Cookie("dcp_session", "tok-1", path = "/api", maxAge = 3600))
        // The server's logout: the same cookie with an expiry in the past.
        store.cookies.addCookie(
            server,
            Cookie("dcp_session", "", path = "/api", expires = GMTDate(getTimeMillis() - 1000)),
        )
        assertEquals(emptyList(), store.cookies.get(Url("http://10.0.2.2:8000/api/v1/sync/push")))
    }

    @Test
    fun `the person is remembered for the screen, and forgotten with the cookies`() = runBlocking {
        val store = SessionStore(database())
        store.cookies.addCookie(server, Cookie("dcp_session", "tok-1", path = "/api", maxAge = 3600))
        store.remember(SignedIn("u1", "amina", "Amina", "2026-10-09T00:00:00Z"))
        assertEquals("Amina", store.signedIn()?.displayName)

        store.forget()
        assertNull(store.signedIn())
        assertEquals(emptyList(), store.cookies.get(Url("http://10.0.2.2:8000/api/v1/sync/push")))
    }
}
