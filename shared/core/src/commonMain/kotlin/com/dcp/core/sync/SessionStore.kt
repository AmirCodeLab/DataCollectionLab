package com.dcp.core.sync

import app.cash.sqldelight.coroutines.asFlow
import app.cash.sqldelight.coroutines.mapToList
import com.dcp.core.db.DcpDatabase
import io.ktor.client.plugins.cookies.CookiesStorage
import io.ktor.http.Cookie
import io.ktor.http.Url
import io.ktor.util.date.GMTDate
import io.ktor.util.date.getTimeMillis
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlin.coroutines.CoroutineContext

/**
 * The app's session: the cookies the server set, kept across restarts.
 *
 * Ktor's cookie plugin carries cookies back to the host that set them, and its
 * own storage is in memory — a restart forgets the session and the enumerator
 * signs in every morning (proposal §3.3). This is the one class that is ours
 * to write: a [CookiesStorage] over the `app_setting` table, which lives in
 * the SQLCipher database with everything else, so the session token is
 * encrypted at rest under the same key as the answers it authorises
 * (envelope §14). `SameSite` means nothing here — there is no site — and the
 * server's `HttpOnly` is about browsers; a native client simply stores the
 * value and sends it back.
 *
 * Only the cookies for the host that set them are ever sent: a device whose
 * address is changed to another server starts there with no session.
 *
 * Beside the cookies, who signed in ([signedIn]), for the settings screen.
 * That is display, not authority — the server decides every request from the
 * cookie, and a person shown as signed in whose membership was deactivated
 * finds out on the next sync, which says so.
 */
class SessionStore(db: DcpDatabase) {
    private val queries = db.settingsQueries
    private val mutex = Mutex()

    /**
     * The store as Ktor's cookie plugin sees it. Internal, so that the app
     * module — which wires this into its graph — never sees a Ktor type:
     * the HTTP library is the shared module's business.
     */
    internal val cookies: CookiesStorage = object : CookiesStorage {
        override suspend fun get(requestUrl: Url): List<Cookie> = read(requestUrl)
        override suspend fun addCookie(requestUrl: Url, cookie: Cookie) = write(requestUrl, cookie)
        override fun close() {}
    }

    private suspend fun read(requestUrl: Url): List<Cookie> = mutex.withLock {
        val now = getTimeMillis()
        val live = stored().filter { it.expiresAtMillis == null || it.expiresAtMillis > now }
        if (live.size != stored().size) persist(live)
        live.filter { it.matches(requestUrl) }.map { it.toCookie() }
    }

    private suspend fun write(requestUrl: Url, cookie: Cookie) = mutex.withLock {
        val domain = cookie.domain?.lowercase() ?: requestUrl.host.lowercase()
        val path = cookie.path ?: "/"
        val incoming = StoredCookie(
            name = cookie.name,
            value = cookie.value,
            domain = domain,
            path = path,
            expiresAtMillis = cookie.expires?.timestamp
                ?: cookie.maxAge?.let { getTimeMillis() + it * 1000L },
            secure = cookie.secure,
        )
        val others = stored().filterNot {
            it.name == cookie.name && it.domain == domain && it.path == path
        }
        // A cookie with a past expiry is how a server deletes one (logout).
        val kept = if (incoming.expiresAtMillis != null && incoming.expiresAtMillis <= getTimeMillis()) {
            others
        } else {
            others + incoming
        }
        persist(kept)
    }

    /** Who is signed in on this device, as last told by the server. */
    fun signedIn(): SignedIn? =
        queries.getSetting(KEY_SIGNED_IN).executeAsOneOrNull()?.let {
            runCatching { SyncJson.decodeFromString(SignedIn.serializer(), it) }.getOrNull()
        }

    fun observeSignedIn(context: CoroutineContext = Dispatchers.Default): Flow<SignedIn?> =
        queries.allSettings().asFlow().mapToList(context).map { rows ->
            rows.firstOrNull { it.key == KEY_SIGNED_IN }?.setting_value?.let {
                runCatching { SyncJson.decodeFromString(SignedIn.serializer(), it) }.getOrNull()
            }
        }

    fun remember(who: SignedIn) {
        queries.putSetting(KEY_SIGNED_IN, SyncJson.encodeToString(who))
    }

    /** Forget the session: the cookies and the name. What the server holds is
     * the server's to revoke (`POST /auth/logout`); this is the device's half. */
    suspend fun forget() = mutex.withLock {
        queries.clearSetting(KEY_COOKIES)
        queries.clearSetting(KEY_SIGNED_IN)
    }

    private fun stored(): List<StoredCookie> =
        queries.getSetting(KEY_COOKIES).executeAsOneOrNull()?.let {
            runCatching { SyncJson.decodeFromString<List<StoredCookie>>(it) }.getOrNull()
        } ?: emptyList()

    private fun persist(cookies: List<StoredCookie>) {
        if (cookies.isEmpty()) queries.clearSetting(KEY_COOKIES)
        else queries.putSetting(KEY_COOKIES, SyncJson.encodeToString(cookies))
    }

    @Serializable
    private data class StoredCookie(
        val name: String,
        val value: String,
        val domain: String,
        val path: String,
        val expiresAtMillis: Long?,
        val secure: Boolean,
    ) {
        fun matches(url: Url): Boolean {
            val host = url.host.lowercase()
            val hostMatches = host == domain || host.endsWith(".$domain")
            val pathMatches = url.encodedPath.startsWith(path)
            val schemeMatches = !secure || url.protocol.name == "https"
            return hostMatches && pathMatches && schemeMatches
        }

        fun toCookie() = Cookie(
            name = name,
            value = value,
            domain = domain,
            path = path,
            expires = expiresAtMillis?.let { GMTDate(it) },
            secure = secure,
        )
    }

    private companion object {
        const val KEY_COOKIES = "auth.cookies"
        const val KEY_SIGNED_IN = "auth.signed_in"
    }
}

/** Who this device is signed in as, as the server described them at login. */
@Serializable
data class SignedIn(
    val userId: String,
    val username: String?,
    val displayName: String,
    val expiresAt: String,
)
