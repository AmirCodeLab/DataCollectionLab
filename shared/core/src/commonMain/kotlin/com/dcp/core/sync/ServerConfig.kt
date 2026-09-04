package com.dcp.core.sync

import app.cash.sqldelight.coroutines.asFlow
import app.cash.sqldelight.coroutines.mapToList
import com.dcp.core.db.DcpDatabase
import kotlin.coroutines.CoroutineContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

/**
 * The result of reading a server address a person typed.
 *
 * Two cases and no third: either there is an address to store, or there is a
 * sentence to show the person who typed it. A nullable String would collapse
 * the second into "something was wrong", and the whole reason this exists is
 * that "invalid URL" is not a thing anybody can act on.
 */
sealed interface ServerUrlResult {
    /** The normalised address to store — scheme present, no trailing slash. */
    data class Valid(val url: String) : ServerUrlResult

    /** [reason] is written to be shown verbatim under the text field. */
    data class Invalid(val reason: String) : ServerUrlResult
}

/**
 * Read a server address the way a person types one.
 *
 * The input is not a URL, it is what somebody entered into a phone with one
 * thumb in a field: `192.168.1.20:8000`, or a pasted
 * `http://dcp.example.org/api/v1`, or an address with a trailing slash that
 * would make every request path contain `//`. What comes back is either an
 * address the client can use or a sentence explaining what to change.
 *
 * What is corrected silently, because there is only one thing it could have
 * meant:
 *
 * - **a missing scheme** becomes `http://`. A field engineer typing a LAN
 *   address is not typing `http://`, and refusing them for it would be a
 *   spelling test rather than a check
 * - **trailing slashes** go. Every request path in this client begins with
 *   `/api/v1`, so a stored trailing slash produces `//api/v1` — which some
 *   servers route and some 404, making it the sort of bug that reproduces on
 *   one deployment out of three
 * - **case in the scheme and host**, which are case-insensitive by definition
 *
 * What is refused rather than corrected, because a guess would be a guess about
 * intent: a scheme that is not http or https, an address with a space in it, a
 * port that is not a port, and — the one worth naming on its own — an address
 * ending in `/api/v1`. That last one is what a person gets by copying a URL out
 * of the API docs or a browser tab, and it is the failure with the worst
 * symptom: it is a perfectly reachable server on which every single request
 * 404s, so the address looks right, the network is fine and nothing works. The
 * message hands back the address with the suffix removed rather than leaving
 * them to work it out.
 *
 * A path prefix that is *not* `/api` is kept, because a self-hosted install
 * behind a reverse proxy is genuinely served from one — `https://example.org/dcp`
 * is a real base address.
 */
fun parseServerUrl(raw: String): ServerUrlResult {
    val trimmed = raw.trim()
    if (trimmed.isEmpty()) {
        return ServerUrlResult.Invalid(
            "Enter the address of your server, for example http://192.168.1.20:8000",
        )
    }
    if (trimmed.any { it.isWhitespace() }) {
        return ServerUrlResult.Invalid("A server address cannot contain a space.")
    }

    // "://" and not ":" — `localhost:8000` has a colon and no scheme, and
    // reading its host as a scheme is how a port becomes an error message.
    val separator = trimmed.indexOf("://")
    val scheme: String
    val remainder: String
    if (separator >= 0) {
        scheme = trimmed.substring(0, separator).lowercase()
        remainder = trimmed.substring(separator + 3)
        if (scheme != "http" && scheme != "https") {
            return ServerUrlResult.Invalid(
                "A server address has to start with http:// or https://. " +
                    "This one starts with $scheme://",
            )
        }
    } else {
        scheme = "http"
        remainder = trimmed
    }

    val authorityEnd = remainder.indexOf('/').let { if (it < 0) remainder.length else it }
    val authority = remainder.substring(0, authorityEnd)
    val path = remainder.substring(authorityEnd).trimEnd('/')

    if (authority.isEmpty()) {
        return ServerUrlResult.Invalid("That address has no server name in it.")
    }

    // A bracketed IPv6 literal carries colons that are not the port separator.
    val hostAndPort = if (authority.startsWith("[")) {
        val close = authority.indexOf(']')
        if (close < 0) return ServerUrlResult.Invalid("That address is missing a closing ']'.")
        authority.substring(0, close + 1) to authority.substring(close + 1).removePrefix(":")
    } else {
        val colon = authority.indexOf(':')
        if (colon < 0) authority to "" else {
            authority.substring(0, colon) to authority.substring(colon + 1)
        }
    }
    val (host, port) = hostAndPort

    if (host.isEmpty() || host == "[]") {
        return ServerUrlResult.Invalid("That address has no server name in it.")
    }
    if (host.any { it !in HOST_CHARACTERS }) {
        val offender = host.first { it !in HOST_CHARACTERS }
        return ServerUrlResult.Invalid("'$offender' cannot appear in a server name.")
    }
    if (port.isNotEmpty()) {
        val number = port.toIntOrNull()
        if (number == null || number !in 1..65535) {
            return ServerUrlResult.Invalid(
                "'$port' is not a port number. A port is a number from 1 to 65535 — " +
                    "this server usually runs on 8000.",
            )
        }
    }

    // The paste-from-the-docs mistake. Reachable server, every request 404s.
    val lowerPath = path.lowercase()
    if (lowerPath == "/api" || lowerPath == "/api/v1" || lowerPath.endsWith("/api/v1")) {
        val corrected = "$scheme://${authority.lowercase()}" + path.dropLast(
            if (lowerPath.endsWith("/api/v1")) "/api/v1".length else "/api".length,
        )
        return ServerUrlResult.Invalid(
            "Leave off the /api/v1 — the app adds it. Try $corrected",
        )
    }

    return ServerUrlResult.Valid("$scheme://${authority.lowercase()}$path")
}

private val HOST_CHARACTERS: Set<Char> =
    (('a'..'z') + ('A'..'Z') + ('0'..'9') + listOf('.', '-', '_', '[', ']', ':')).toSet()

/**
 * Which server this device talks to.
 *
 * Until this existed the address was a compile-time constant per platform
 * ([com.dcp.core.sync] has no say in it — see `defaultSyncBaseUrl` in the
 * clients), which meant that putting a phone in front of a real server required
 * rebuilding the app. That is fine for an emulator, whose host is always
 * `10.0.2.2`, and it is the reason a physical device had never once reached a
 * server: there is no constant that is right for one.
 *
 * ## Why the default is a fallback and not a stored row
 *
 * A fresh install stores nothing. [baseUrl] answers with [platformDefault]
 * until somebody saves an address, and [isPlatformDefault] says which of the
 * two is in effect so the settings screen can show it. The alternative — seed
 * the row with the default at first launch — makes an upgrade that changes the
 * default silently keep the old one, and leaves no way to tell a deliberate
 * choice from an inherited one.
 *
 * Clearing writes no empty string ([reset] deletes the row), because "" is a
 * server address of no characters, which is a different and unusable answer
 * from "none chosen".
 */
class ServerConfig(
    db: DcpDatabase,
    /**
     * What this platform talks to when nobody has said otherwise:
     * `10.0.2.2:8000` on Android, where that is the emulator's alias for the
     * host machine, `localhost:8000` on desktop and the iOS simulator.
     */
    val platformDefault: String,
) {
    private val queries = db.settingsQueries

    fun baseUrl(): String = stored() ?: platformDefault

    /** The address somebody saved, or null while the platform default stands. */
    fun stored(): String? = queries.getSetting(KEY_SERVER_URL).executeAsOneOrNull()

    val isPlatformDefault: Boolean get() = stored() == null

    /**
     * Store an address a person entered, normalised by [parseServerUrl].
     *
     * Refuses rather than stores when the address cannot be used, and hands
     * back the reason: a device pointed at an address that cannot work is
     * indistinguishable, from the field, from a device with no signal.
     */
    fun setBaseUrl(raw: String): ServerUrlResult =
        parseServerUrl(raw).also {
            if (it is ServerUrlResult.Valid) queries.putSetting(KEY_SERVER_URL, it.url)
        }

    /** Back to the platform default. Deletes the row; see the class comment. */
    fun reset() = queries.clearSetting(KEY_SERVER_URL)

    fun observeBaseUrl(context: CoroutineContext = Dispatchers.Default): Flow<String> =
        queries.allSettings().asFlow().mapToList(context).map { rows ->
            rows.firstOrNull { it.key == KEY_SERVER_URL }?.setting_value ?: platformDefault
        }

    private companion object {
        /**
         * Namespaced from the first row rather than from the second. Renaming a
         * settings key later means every device that stored one loses it, and
         * `server_url` is precisely the name a future unrelated setting would
         * also want.
         */
        const val KEY_SERVER_URL = "sync.server_url"
    }
}
