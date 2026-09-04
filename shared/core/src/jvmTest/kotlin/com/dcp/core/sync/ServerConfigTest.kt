package com.dcp.core.sync

/**
 * The server address: how one typed by a person is read, and how it is kept.
 *
 * This is Kotlin-only client code and no conformance vector can reach it
 * (docs/project-conventions.md, "Where the conformance architecture stops protecting you"). The
 * Python reference has no device, so it has no address to configure and there
 * is no second implementation to compare against — a vector cannot be written
 * here at all.
 *
 * Break 32 in docs/known-breaks.md is what has been watched to fail.
 */

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ServerConfigTest {

    // ---------------------------------------------------------------- parsing

    @Test
    fun `an address with no scheme is read as http`() {
        assertEquals(
            ServerUrlResult.Valid("http://192.168.1.20:8000"),
            parseServerUrl("192.168.1.20:8000"),
        )
    }

    @Test
    fun `a host with a port is not read as a scheme`() {
        // `localhost:8000` has a colon and no scheme. Splitting on ':' rather
        // than on '://' turns the host into a scheme and the port into a host,
        // and the message a person then gets is about neither.
        assertEquals(
            ServerUrlResult.Valid("http://localhost:8000"),
            parseServerUrl("localhost:8000"),
        )
    }

    @Test
    fun `https is kept`() {
        assertEquals(
            ServerUrlResult.Valid("https://dcp.example.org"),
            parseServerUrl("https://dcp.example.org"),
        )
    }

    @Test
    fun `a trailing slash is dropped`() {
        // Kept, it produces `//api/v1` on every request — routed by some
        // servers and 404ed by others, which is the worst kind of bug to own.
        assertEquals(
            ServerUrlResult.Valid("http://host:8000"),
            parseServerUrl("http://host:8000/"),
        )
        assertEquals(
            ServerUrlResult.Valid("http://host:8000"),
            parseServerUrl("http://host:8000///"),
        )
    }

    @Test
    fun `surrounding whitespace is trimmed`() {
        // A pasted address arrives with a newline more often than not.
        assertEquals(
            ServerUrlResult.Valid("http://host:8000"),
            parseServerUrl("  http://host:8000\n"),
        )
    }

    @Test
    fun `the scheme and host are lowercased and the path is not`() {
        // Host names are case-insensitive; a proxy path is not.
        assertEquals(
            ServerUrlResult.Valid("https://dcp.example.org/DCP"),
            parseServerUrl("HTTPS://DCP.Example.ORG/DCP"),
        )
    }

    @Test
    fun `a reverse-proxy path prefix is kept`() {
        // A self-hosted install behind a proxy really is served from one, and
        // stripping it would leave the address unusable and looking correct.
        assertEquals(
            ServerUrlResult.Valid("https://example.org/dcp"),
            parseServerUrl("https://example.org/dcp/"),
        )
    }

    @Test
    fun `an address ending in api v1 is refused, with the address to use instead`() {
        // The paste-from-the-docs mistake, and the one with the worst symptom:
        // the server is reachable, the network is fine, and every request 404s.
        val result = parseServerUrl("http://host:8000/api/v1")
        assertTrue(result is ServerUrlResult.Invalid, "expected a refusal, got $result")
        assertTrue(
            "http://host:8000" in result.reason,
            "the message should hand back the corrected address: ${result.reason}",
        )
    }

    @Test
    fun `a scheme that is not http is refused by name`() {
        val result = parseServerUrl("ftp://host")
        assertTrue(result is ServerUrlResult.Invalid)
        assertTrue("ftp" in result.reason, result.reason)
    }

    @Test
    fun `an empty address asks for one and shows the shape`() {
        val result = parseServerUrl("   ")
        assertTrue(result is ServerUrlResult.Invalid)
        // A person who has cleared the field needs an example, not "required".
        assertTrue("http://" in result.reason, result.reason)
    }

    @Test
    fun `a port that is not a number is refused`() {
        val result = parseServerUrl("http://host:80o0")
        assertTrue(result is ServerUrlResult.Invalid)
        assertTrue("80o0" in result.reason, result.reason)
    }

    @Test
    fun `a port outside the valid range is refused`() {
        assertTrue(parseServerUrl("http://host:0") is ServerUrlResult.Invalid)
        assertTrue(parseServerUrl("http://host:99999") is ServerUrlResult.Invalid)
    }

    @Test
    fun `an address with a space in it is refused`() {
        val result = parseServerUrl("http://my server:8000")
        assertTrue(result is ServerUrlResult.Invalid)
        assertTrue("space" in result.reason, result.reason)
    }

    @Test
    fun `an ipv6 literal keeps its brackets and its port`() {
        // The colons inside the brackets are not the port separator.
        assertEquals(
            ServerUrlResult.Valid("http://[fe80::1]:8000"),
            parseServerUrl("[fe80::1]:8000"),
        )
    }

    // ---------------------------------------------------------------- storage

    @Test
    fun `a fresh device answers with the platform default and says it is the default`() {
        val config = ServerConfig(freshDatabase(), "http://10.0.2.2:8000")

        assertEquals("http://10.0.2.2:8000", config.baseUrl())
        assertNull(config.stored(), "nothing was saved, so nothing should be stored")
        assertTrue(config.isPlatformDefault)
    }

    @Test
    fun `a saved address is used and is not the default`() {
        val config = ServerConfig(freshDatabase(), "http://10.0.2.2:8000")

        val result = config.setBaseUrl("192.168.1.20:8000")

        assertEquals(ServerUrlResult.Valid("http://192.168.1.20:8000"), result)
        assertEquals("http://192.168.1.20:8000", config.baseUrl())
        assertTrue(!config.isPlatformDefault)
    }

    @Test
    fun `an address that cannot be used is not stored`() {
        // The whole reason setBaseUrl refuses rather than stores: a device
        // pointed at an unusable address is indistinguishable, from the field,
        // from a device with no signal.
        val config = ServerConfig(freshDatabase(), "http://10.0.2.2:8000")
        config.setBaseUrl("192.168.1.20:8000")

        val result = config.setBaseUrl("ftp://nope")

        assertTrue(result is ServerUrlResult.Invalid)
        assertEquals(
            "http://192.168.1.20:8000",
            config.baseUrl(),
            "a refused address must leave the working one alone",
        )
    }

    @Test
    fun `reset goes back to the platform default rather than to an empty address`() {
        // Deleting the row, not writing "": an address of no characters is a
        // different and unusable answer from "none chosen".
        val config = ServerConfig(freshDatabase(), "http://10.0.2.2:8000")
        config.setBaseUrl("https://prod.example.org")

        config.reset()

        assertNull(config.stored())
        assertEquals("http://10.0.2.2:8000", config.baseUrl())
        assertTrue(config.isPlatformDefault)
    }

    @Test
    fun `a saved address survives a second ServerConfig over the same database`() {
        // The point of storing it at all. An address that has to be retyped
        // after every launch is not a configured device.
        val db = freshDatabase()
        ServerConfig(db, "http://10.0.2.2:8000").setBaseUrl("http://192.168.1.20:8000")

        val reopened = ServerConfig(db, "http://10.0.2.2:8000")

        assertEquals("http://192.168.1.20:8000", reopened.baseUrl())
    }

    private fun freshDatabase(): DcpDatabase =
        DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema))
}
