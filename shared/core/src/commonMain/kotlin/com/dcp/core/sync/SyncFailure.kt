package com.dcp.core.sync

/**
 * Turns a network failure into a sentence naming the address that failed and
 * what to do about it.
 *
 * ## Why this file exists
 *
 * The address is now something a person types (see [ServerConfig]), so the
 * commonest failure in this product is no longer a flat network — it is a
 * device pointed somewhere it cannot reach, and every one of those looks the
 * same from the enumerator's side. What they had to work from was the platform
 * exception's own message: `Connect timeout has expired [url=..., ...]`, or on
 * a good day `java.net.ConnectException`. Neither says which server was tried,
 * neither distinguishes "wrong address" from "server is down" from "wrong
 * network", and the three have completely different fixes.
 *
 * So: **name the URL, name the likely cause, name the next step**, and never
 * discard the original text — it is appended, because the sentence here is a
 * best guess about a class of failure and the underlying message is the fact.
 *
 * ## Why it matches on strings
 *
 * There is no common exception type to match on. Ktor's CIO engine surfaces
 * `java.net.ConnectException` on the JVM and Android, a `PosixException` or an
 * NSError-backed failure on Kotlin/Native, and its own
 * `HttpRequestTimeoutException` on all of them; `UnresolvedAddressException`
 * carries no message at all. Matching on class names and message text across
 * the whole cause chain is what works on every target, and it fails safe: an
 * unrecognised failure falls through to a sentence that still names the URL and
 * still quotes the original.
 *
 * `SyncFailureTest` is what watches this — it is Kotlin-only client code that
 * no conformance vector can reach (docs/project-conventions.md, "Where the conformance
 * architecture stops protecting you").
 */
object SyncFailure {

    /**
     * A sentence for [cause], naming [baseUrl].
     *
     * [baseUrl] is the address actually used for the request, not the one
     * currently in settings — a sync that failed against the old address must
     * not report the new one, which would send somebody to check a server that
     * was never contacted.
     */
    fun describe(baseUrl: String, cause: Throwable): String {
        val signature = signatureOf(cause)
        val original = originalMessage(cause)
        val explanation = explain(baseUrl, signature)
        // The guess, then the fact. Keeping the original text is what makes a
        // wrong guess recoverable rather than misleading.
        return if (original.isNullOrBlank()) explanation else "$explanation ($original)"
    }

    private fun explain(baseUrl: String, signature: String): String {
        val host = hostOf(baseUrl)
        val hint = addressHint(host)

        return when {
            // Name resolution. The address is syntactically fine and there is
            // nothing at that name on this network.
            "unresolvedaddress" in signature ||
                "unknownhost" in signature ||
                "nodename nor servname" in signature ||
                "hostname could not be found" in signature ->
                "Could not find $host. The name does not resolve on this network — " +
                    "check the spelling, or use the server's IP address instead." + hint

            // Something answered the network and refused the port. This is the
            // "server is not running" case and it is worth saying plainly,
            // because the address is right.
            "connectionrefused" in signature || "connection refused" in signature ->
                "Nothing is listening at $baseUrl. The address was reached, so this is " +
                    "usually the server not running, or running on a different port." + hint

            "noroutetohost" in signature ||
                "network is unreachable" in signature ||
                "nonetwork" in signature ->
                "$baseUrl could not be reached. This device is probably not on the same " +
                    "network as the server — check Wi-Fi." + hint

            // Android's own refusal, and it is a build setting rather than
            // anything about the server, so no amount of checking the server
            // helps.
            "cleartext" in signature ->
                "$baseUrl was blocked before it was tried: this build does not allow " +
                    "plain http. Use an https address, or a build that permits http."

            // A connect timeout is silence, and silence has two causes this
            // client cannot tell apart: nothing is at that address (the device
            // is on a different network from the server, or the address is
            // simply wrong), or something is and a firewall is dropping the
            // packets rather than refusing them. Naming one of them would be
            // guessing — an earlier version of this message asserted "something
            // is at that address but it is not replying", and the case that
            // found it was a device on 192.168.2.0/24 pointed at 10.77.77.5,
            // where nothing is at that address at all. Both are named, the
            // network first, because in the field it is the commoner of the two.
            "timeout" in signature || "timedout" in signature ->
                "$baseUrl did not answer. Nothing refused the connection either — it was " +
                    "simply silence, which usually means this device is not on the same " +
                    "network as the server, and sometimes means a firewall is dropping " +
                    "the connection." + hint

            "ssl" in signature || "certificate" in signature || "handshake" in signature ->
                "The secure connection to $baseUrl could not be set up. If this server " +
                    "uses a self-signed certificate, this build will not accept it."

            "socketexception" in signature || "closedchannel" in signature ->
                "The connection to $baseUrl was cut before the sync finished. Nothing was " +
                    "lost — everything not yet acknowledged is still on this device."

            // Reached a server, and it said no. Not a connectivity problem, and
            // saying "could not connect" here would send somebody to the network.
            "clientrequestexception" in signature || " 404 " in signature ->
                "$baseUrl answered, but not as this server's API. Check the address " +
                    "points at the DCP server and not at something else on that host."

            else ->
                "Could not sync with $baseUrl." + hint
        }
    }

    /**
     * The one wrong address this product creates itself.
     *
     * `10.0.2.2` is the Android emulator's alias for the machine it runs on. It
     * is the built-in default on Android because that is where development
     * happens, and it is meaningless on a physical phone — which is exactly the
     * device this hint exists for. An enumerator with a real handset and the
     * factory setting gets a failure that is the app's fault, so the app should
     * be the one to say so.
     *
     * `localhost` earns the same treatment for the same reason: on a phone it
     * means the phone.
     */
    private fun addressHint(host: String): String = when {
        host.startsWith("10.0.2.2") ->
            " Note: 10.0.2.2 only works in the Android emulator, where it means the " +
                "computer running it. A real phone needs that computer's address on the " +
                "network, such as 192.168.1.20."

        host.startsWith("localhost") || host.startsWith("127.0.0.1") || host.startsWith("[::1]") ->
            " Note: on a phone, localhost means the phone itself. To reach a server on " +
                "your computer, use that computer's address on the network."

        else -> ""
    }

    /** Scheme and path stripped: the part a person recognises as "the server". */
    private fun hostOf(baseUrl: String): String {
        val afterScheme = baseUrl.substringAfter("://", baseUrl)
        return afterScheme.substringBefore('/')
    }

    /**
     * Class names and messages from the whole cause chain, lowercased and with
     * spaces removed from the class names.
     *
     * The chain matters: Ktor wraps, and the exception that says
     * `UnresolvedAddressException` is routinely three `cause`s down from the one
     * that reaches the caller.
     */
    private fun signatureOf(cause: Throwable): String = buildString {
        var current: Throwable? = cause
        var depth = 0
        while (current != null && depth < 8) {
            append(current::class.simpleName?.lowercase().orEmpty())
            append(' ')
            append(current.message?.lowercase().orEmpty())
            append(' ')
            current = current.cause.takeIf { it !== current }
            depth++
        }
    }

    /**
     * The first message in the chain with any text in it.
     *
     * `UnresolvedAddressException` has a null message and a name that says
     * everything, so walking the chain is what stops the parenthetical being
     * empty on the one failure it would help most.
     */
    private fun originalMessage(cause: Throwable): String? {
        var current: Throwable? = cause
        var depth = 0
        while (current != null && depth < 8) {
            current.message?.takeIf { it.isNotBlank() }?.let { return it }
            current = current.cause.takeIf { it !== current }
            depth++
        }
        return cause::class.simpleName
    }
}

/**
 * What came back from asking whether there is a server at an address.
 *
 * [Reached] carries the deployment's own name for itself rather than just
 * saying yes, because "connected" is not the reassurance it looks like: a phone
 * that reaches staging when it should reach production connects perfectly,
 * syncs perfectly, and files a morning's interviews where nobody will look for
 * them. Showing `production` or `staging` beside the tick is the only part of
 * this check that can catch that, and it costs nothing — the server already
 * says so.
 */
sealed interface ConnectionCheck {
    val url: String

    data class Reached(override val url: String, val environment: String) : ConnectionCheck

    /** [reason] is a sentence from [SyncFailure.describe], ready to display. */
    data class Failed(override val url: String, val reason: String) : ConnectionCheck
}
