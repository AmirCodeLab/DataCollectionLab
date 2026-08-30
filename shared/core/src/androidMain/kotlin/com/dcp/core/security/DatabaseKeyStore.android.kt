package com.dcp.core.security

import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.UserNotAuthenticatedException
import java.security.KeyStore
import javax.crypto.KeyGenerator
import javax.crypto.Mac
import javax.crypto.SecretKey

/**
 * Android: the local database key is **derived** from a non-exportable key in
 * the Android Keystore, not stored anywhere (encryption envelope §14.4).
 *
 * ```
 * db_key = HMAC-SHA256(K_keystore, "dcp/v1/local-db-key")
 * ```
 *
 * The usual pattern would be to generate a random database key, seal it with a
 * keystore key and write the sealed blob into `SharedPreferences` — which is
 * what `EncryptedSharedPreferences` does under the covers. §14.4 rules that out
 * on purpose. The sealed blob is an extra artifact to attack, it rides along in
 * cloud backups and `adb backup` unless separately excluded, and it makes "no
 * key material is in any file this app owns" an argument about a file rather
 * than a fact about its absence.
 *
 * Deriving instead leaves nothing outside the TEE. `K_keystore` cannot be
 * exported — `SecretKey.getEncoded()` returns null for an AndroidKeyStore key —
 * so an attacker holding the flash has nothing to work with, and the derivation
 * is deterministic, so the same database opens on every run.
 *
 * @param requireUserAuthentication the app lock of §14.7. When true the
 *   keystore releases `K_keystore` only after a device credential or strong
 *   biometric, so an unauthenticated process cannot derive the key at all —
 *   the lock gates the key, not a screen.
 */
actual class DatabaseKeyStore(
    private val requireUserAuthentication: Boolean = false,
    private val authenticationValiditySeconds: Int = DEFAULT_AUTH_VALIDITY_SECONDS,
) {

    actual fun loadOrCreate(): DatabaseKey {
        val secret = existingKeystoreKey() ?: generateKeystoreKey()
        val mac = try {
            Mac.getInstance(MAC_ALGORITHM).apply { init(secret) }
        } catch (e: UserNotAuthenticatedException) {
            throw DatabaseKeyUnavailable(
                "the app lock has not been satisfied, so the Android Keystore will not release " +
                    "the local database key. Authenticate and try again.",
                e,
            )
        } catch (e: Exception) {
            throw DatabaseKeyUnavailable("the Android Keystore refused the local database key", e)
        }

        val derived = mac.doFinal(DERIVATION_INFO.toByteArray(Charsets.UTF_8))
        return try {
            DatabaseKey(derived)
        } finally {
            derived.fill(0)
        }
    }

    actual fun exists(): Boolean = existingKeystoreKey() != null

    actual fun destroy() {
        androidKeyStore().deleteEntry(KEY_ALIAS)
    }

    private fun androidKeyStore(): KeyStore =
        KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }

    private fun existingKeystoreKey(): SecretKey? = try {
        (androidKeyStore().getEntry(KEY_ALIAS, null) as? KeyStore.SecretKeyEntry)?.secretKey
    } catch (e: UserNotAuthenticatedException) {
        throw DatabaseKeyUnavailable("the app lock has not been satisfied", e)
    } catch (e: Exception) {
        // A key the keystore can no longer load — the usual cause is the user
        // removing their lock screen, which permanently invalidates every
        // auth-bound key. Reporting it is the only honest move: silently
        // generating a replacement would mint a key that opens nothing and
        // leave the database unreadable with no explanation (§14.7).
        throw DatabaseKeyUnavailable(
            "the Android Keystore holds \"$KEY_ALIAS\" but will not load it. If the device's " +
                "lock screen was removed, the key is permanently invalidated and the local " +
                "database cannot be recovered (§14.3).",
            e,
        )
    }

    private fun generateKeystoreKey(): SecretKey {
        // StrongBox first: a separate secure element, so the key survives a
        // kernel compromise. Not every device has one, and the ones that do not
        // only say so by throwing at generateKey().
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            try {
                return generateKeystoreKey(strongBox = true)
            } catch (e: Exception) {
                if (!isStrongBoxUnavailable(e)) throw e
                // Fall through to the TEE-backed keystore.
            }
        }
        return generateKeystoreKey(strongBox = false)
    }

    /**
     * Matched by name rather than by type. `StrongBoxUnavailableException` did
     * not exist before API 28, and naming it in a `catch` puts a class
     * reference in the bytecode that an API 24 device has to resolve to enter
     * the block at all.
     */
    private fun isStrongBoxUnavailable(error: Throwable): Boolean =
        generateSequence(error) { it.cause }
            .any { it.javaClass.name.endsWith("StrongBoxUnavailableException") }

    private fun generateKeystoreKey(strongBox: Boolean): SecretKey {
        val spec = KeyGenParameterSpec.Builder(KEY_ALIAS, KeyProperties.PURPOSE_SIGN)
            .setKeySize(KEY_SIZE_BITS)
            .setDigests(KeyProperties.DIGEST_SHA256)
            .apply {
                // Only ever true on API 28+ — see generateKeystoreKey() above.
                @Suppress("NewApi")
                if (strongBox) setIsStrongBoxBacked(true)
                if (requireUserAuthentication) {
                    setUserAuthenticationRequired(true)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                        setUserAuthenticationParameters(
                            authenticationValiditySeconds,
                            KeyProperties.AUTH_DEVICE_CREDENTIAL or
                                KeyProperties.AUTH_BIOMETRIC_STRONG,
                        )
                    } else {
                        @Suppress("DEPRECATION")
                        setUserAuthenticationValidityDurationSeconds(authenticationValiditySeconds)
                    }
                }
                // Not setUnlockedDeviceRequired: background sync runs with the
                // screen off, and a key that needs an unlocked screen would
                // stop a device syncing until someone picked it up. The app
                // lock above is the setting that trades that away deliberately.
            }
            .build()

        return try {
            KeyGenerator.getInstance(MAC_ALGORITHM, ANDROID_KEYSTORE)
                .apply { init(spec) }
                .generateKey()
        } catch (e: Exception) {
            if (isStrongBoxUnavailable(e)) throw e
            throw DatabaseKeyUnavailable(
                "could not generate the local database key in the Android Keystore" +
                    if (requireUserAuthentication) {
                        ". The app lock needs a device credential to be set; there is none."
                    } else {
                        ""
                    },
                e,
            )
        }
    }

    companion object {
        /**
         * Versioned. A future change to the derivation gets a new alias rather
         * than a new meaning for this one, so an old database stays openable
         * long enough to be migrated.
         */
        const val KEY_ALIAS: String = "dcp_local_db_key_v1"

        /** Domain separation, so this keystore key can safely derive others. */
        const val DERIVATION_INFO: String = "dcp/v1/local-db-key"

        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val MAC_ALGORITHM = "HmacSHA256"
        private const val KEY_SIZE_BITS = 256

        /**
         * How long one authentication covers. Long enough that an enumerator
         * filling in a 52-question form is not re-prompted mid-form; short
         * enough that a phone put down on a table stops being usable quickly.
         */
        const val DEFAULT_AUTH_VALIDITY_SECONDS: Int = 300
    }
}
