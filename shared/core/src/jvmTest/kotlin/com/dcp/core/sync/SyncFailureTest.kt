package com.dcp.core.sync

/**
 * What a person is told when a sync cannot reach the server.
 *
 * Every assertion here is about a sentence rather than about a value, which is
 * unusual and is the point: the failure this guards against is not a wrong
 * result, it is a correct result nobody can act on. `Connect timeout has
 * expired` is a true statement that does not say which server was tried, does
 * not distinguish a wrong address from a stopped server, and leaves a field
 * engineer with nothing to check.
 *
 * So the properties under test are: **the URL appears**, **the original text is
 * never thrown away**, and **the causes that need different fixes get different
 * sentences**. The exact wording is free to change; a test that pinned it would
 * have to be edited every time the wording improved, which is how a test starts
 * being edited to match the code.
 *
 * Kotlin-only, above the line the conformance vectors reach (docs/project-conventions.md).
 * Break 32 in docs/known-breaks.md.
 */

import io.ktor.client.plugins.HttpRequestTimeoutException
import java.net.ConnectException
import java.net.UnknownHostException
import java.nio.channels.UnresolvedAddressException
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class SyncFailureTest {

    private val url = "http://192.168.1.20:8000"

    @Test
    fun `every failure names the address that was tried`() {
        // The one property that matters on every path. A device can be pointed
        // anywhere now, so "sync failed" without an address does not even say
        // which server to go and look at.
        val causes = listOf<Throwable>(
            ConnectException("Connection refused"),
            UnknownHostException("dcp.example.org"),
            UnresolvedAddressException(),
            HttpRequestTimeoutException(url, 15_000),
            IllegalStateException("something nobody has seen before"),
        )
        causes.forEach { cause ->
            val message = SyncFailure.describe(url, cause)
            assertTrue(
                url in message || "192.168.1.20:8000" in message,
                "no address in the message for ${cause::class.simpleName}: $message",
            )
        }
    }

    @Test
    fun `a refused connection is not reported as a missing address`() {
        // These two have different fixes — start the server, versus correct
        // what you typed — and telling somebody the wrong one costs them the
        // morning.
        val refused = SyncFailure.describe(url, ConnectException("Connection refused"))
        val unresolved = SyncFailure.describe(url, UnresolvedAddressException())

        assertTrue("listening" in refused, refused)
        assertTrue("resolve" in unresolved, unresolved)
        assertFalse("resolve" in refused, "a refused port is not a name lookup: $refused")
    }

    @Test
    fun `a timeout does not claim to know whether anything is there`() {
        // A connect timeout is silence, and silence has two causes this client
        // cannot tell apart: nothing at that address, or a firewall dropping
        // the packets. An earlier version asserted "something is at that
        // address but it is not replying", and the case that found it was a
        // handset on 192.168.2.0/24 pointed at 10.77.77.5 — where there is
        // nothing at all. A message that sends somebody to check a server that
        // does not exist is worse than one that says it does not know.
        val message = SyncFailure.describe(url, HttpRequestTimeoutException(url, 15_000))

        assertTrue("did not answer" in message, message)
        assertTrue("same network" in message, "the likelier cause must be named: $message")
        assertFalse(
            "Something is at that address" in message,
            "a timeout cannot establish that anything is listening: $message",
        )
    }

    @Test
    fun `the platform's own message is kept, never replaced`() {
        // The sentence is a guess about a class of failure. The original text
        // is the fact, and it is what makes a wrong guess recoverable instead
        // of misleading.
        val message = SyncFailure.describe(url, ConnectException("Connection refused (os error 61)"))
        assertTrue("os error 61" in message, message)
    }

    @Test
    fun `a cause buried in the chain is still recognised`() {
        // Ktor wraps. The exception that says UnresolvedAddressException is
        // routinely two or three `cause`s below the one that reaches the caller,
        // and matching only the outermost would fall through to the generic
        // sentence on the commonest failure there is.
        val wrapped = RuntimeException("request failed", RuntimeException(UnresolvedAddressException()))

        val message = SyncFailure.describe(url, wrapped)

        assertTrue("resolve" in message, message)
    }

    @Test
    fun `an exception with no message still says something useful`() {
        // UnresolvedAddressException carries a null message and a name that
        // says everything. Falling back to the class name is what stops the
        // parenthetical being empty on the failure it would help most.
        val message = SyncFailure.describe(url, UnresolvedAddressException())

        assertTrue(message.isNotBlank())
        assertTrue("UnresolvedAddressException" in message, message)
    }

    @Test
    fun `an unrecognised failure still names the address and quotes the original`() {
        // The fall-through has to be useful, because it is what runs on iOS,
        // where none of the JVM exception names apply.
        val message = SyncFailure.describe(url, IllegalStateException("a novel disaster"))

        assertTrue(url in message, message)
        assertTrue("a novel disaster" in message, message)
    }

    @Test
    fun `the emulator address is explained, because the app is what chose it`() {
        // 10.0.2.2 is the Android emulator's alias for its host and means
        // nothing on a handset. It is the built-in default, so a real phone
        // fails on an address the app supplied — which makes the explanation
        // the app's job rather than the enumerator's problem.
        val message = SyncFailure.describe(
            "http://10.0.2.2:8000",
            ConnectException("Connection refused"),
        )

        assertTrue("emulator" in message, message)
        assertTrue("192.168" in message, "the hint should show the shape of the fix: $message")
    }

    @Test
    fun `localhost on a phone is explained too`() {
        val message = SyncFailure.describe(
            "http://localhost:8000",
            ConnectException("Connection refused"),
        )

        assertTrue("the phone itself" in message, message)
    }

    @Test
    fun `an ordinary address gets no emulator hint`() {
        // The hints are for two specific wrong answers. Attaching them to every
        // failure would make them noise and they would stop being read.
        val message = SyncFailure.describe(url, ConnectException("Connection refused"))

        assertFalse("emulator" in message, message)
        assertFalse("the phone itself" in message, message)
    }
}
