package com.dcp.core.security

import kotlinx.cinterop.CPointer
import kotlinx.cinterop.ExperimentalForeignApi
import kotlinx.cinterop.addressOf
import kotlinx.cinterop.alloc
import kotlinx.cinterop.memScoped
import kotlinx.cinterop.ptr
import kotlinx.cinterop.usePinned
import kotlinx.cinterop.value
import platform.CoreFoundation.CFDictionaryCreateMutable
import platform.CoreFoundation.CFDictionarySetValue
import platform.CoreFoundation.CFErrorRefVar
import platform.CoreFoundation.CFMutableDictionaryRef
import platform.CoreFoundation.CFRelease
import platform.CoreFoundation.CFTypeRefVar
import platform.CoreFoundation.kCFAllocatorDefault
import platform.CoreFoundation.kCFBooleanTrue
import platform.CoreFoundation.kCFTypeDictionaryKeyCallBacks
import platform.CoreFoundation.kCFTypeDictionaryValueCallBacks
import platform.Foundation.CFBridgingRelease
import platform.Foundation.CFBridgingRetain
import platform.Foundation.NSData
import platform.Foundation.create
import platform.Security.SecAccessControlCreateWithFlags
import platform.Security.SecItemAdd
import platform.Security.SecItemCopyMatching
import platform.Security.SecItemDelete
import platform.Security.SecRandomCopyBytes
import platform.Security.errSecItemNotFound
import platform.Security.errSecSuccess
import platform.Security.kSecAttrAccessControl
import platform.Security.kSecAttrAccessible
import platform.Security.kSecAttrAccessibleWhenUnlockedThisDeviceOnly
import platform.Security.kSecAttrAccount
import platform.Security.kSecAttrService
import platform.Security.kSecClass
import platform.Security.kSecAccessControlUserPresence
import platform.Security.kSecClassGenericPassword
import platform.Security.kSecRandomDefault
import platform.Security.kSecReturnData
import platform.Security.kSecValueData
import platform.posix.memcpy

/**
 * iOS: the local database key is 32 random bytes in the Keychain
 * (encryption envelope §14.4).
 *
 * Stored rather than derived — unlike Android's, this keystore hands the bytes
 * back, so there is no reason to build a derivation on top of it.
 *
 * `kSecAttrAccessibleWhenUnlockedThisDeviceOnly` is doing two jobs. *WhenUnlocked*
 * keeps the key sealed while the device is locked, which is the state a seized
 * phone is usually in. *ThisDeviceOnly* keeps it out of iCloud Keychain and out
 * of encrypted iTunes/Finder backups: a key that synchronises to a second
 * device is a key that can be seized on the second device, and a key inside a
 * backup outlives the phone it was meant to be locked to.
 *
 * @param requireUserPresence the app lock of §14.7. Adds Face ID / Touch ID /
 *   passcode to the item itself, so the key cannot be read without it — the
 *   lock gates the key, not a screen.
 */
@OptIn(ExperimentalForeignApi::class)
actual class DatabaseKeyStore(
    private val requireUserPresence: Boolean = false,
    private val service: String = SERVICE,
    private val account: String = ACCOUNT,
) {

    actual fun loadOrCreate(): DatabaseKey {
        existing()?.let { return it }

        val fresh = ByteArray(DatabaseKey.SIZE_BYTES)
        val generated = fresh.usePinned { pinned ->
            SecRandomCopyBytes(kSecRandomDefault, DatabaseKey.SIZE_BYTES.toULong(), pinned.addressOf(0))
        }
        if (generated != errSecSuccess) {
            fresh.fill(0)
            throw DatabaseKeyUnavailable("SecRandomCopyBytes failed with OSStatus $generated")
        }

        try {
            store(fresh)
        } finally {
            fresh.fill(0)
        }

        // Read back rather than returning what was generated. A write the
        // Keychain silently dropped would otherwise give one working session
        // and then a database that never opens again.
        return existing() ?: throw DatabaseKeyUnavailable(
            "wrote the local database key to the Keychain but could not read it back. " +
                "Refusing to open an unencrypted database (encryption envelope §14.5).",
        )
    }

    actual fun exists(): Boolean = existing() != null

    actual fun destroy() {
        val query = baseQuery()
        try {
            SecItemDelete(query)
        } finally {
            CFRelease(query)
        }
    }

    private fun existing(): DatabaseKey? {
        val query = baseQuery()
        CFDictionarySetValue(query, kSecReturnData, kCFBooleanTrue)

        memScoped {
            val result = alloc<CFTypeRefVar>()
            val status = try {
                SecItemCopyMatching(query, result.ptr)
            } finally {
                CFRelease(query)
            }

            if (status == errSecItemNotFound) return null
            if (status != errSecSuccess) {
                throw DatabaseKeyUnavailable(
                    "the Keychain refused the local database key (OSStatus $status)." +
                        if (requireUserPresence) {
                            " With the app lock on, this is what an unsatisfied Face ID / " +
                                "passcode prompt looks like."
                        } else {
                            ""
                        },
                )
            }

            val data = CFBridgingRelease(result.value) as? NSData
                ?: throw DatabaseKeyUnavailable("the Keychain item holds no data")
            val bytes = data.toByteArray()
            if (bytes.size != DatabaseKey.SIZE_BYTES) {
                bytes.fill(0)
                throw DatabaseKeyUnavailable(
                    "the local database key in the Keychain is the wrong size. Refusing to " +
                        "guess: replacing it would make the existing database permanently " +
                        "unreadable (§14.3).",
                )
            }
            return try {
                DatabaseKey(bytes)
            } finally {
                bytes.fill(0)
            }
        }
    }

    private fun store(secret: ByteArray) {
        val query = baseQuery()
        val data = CFBridgingRetain(secret.toNSData())
        CFDictionarySetValue(query, kSecValueData, data)

        // Not kSecAttrAccessible: an item carrying an access control object
        // takes its accessibility from that object, and setting both is an
        // errSecParam. The two branches below say the same thing about when the
        // key is readable, and the locked one adds who has to be present.
        val accessControl = if (requireUserPresence) {
            memScoped {
                val error = alloc<CFErrorRefVar>()
                SecAccessControlCreateWithFlags(
                    kCFAllocatorDefault,
                    kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
                    kSecAccessControlUserPresence,
                    error.ptr,
                ) ?: throw DatabaseKeyUnavailable(
                    "could not build a Keychain access control for the app lock. The device " +
                        "may have no passcode set, which leaves nothing to gate the key with.",
                )
            }
        } else {
            null
        }

        try {
            if (accessControl != null) {
                CFDictionarySetValue(query, kSecAttrAccessControl, accessControl)
            } else {
                CFDictionarySetValue(
                    query,
                    kSecAttrAccessible,
                    kSecAttrAccessibleWhenUnlockedThisDeviceOnly,
                )
            }

            // Replace rather than update: SecItemAdd fails with
            // errSecDuplicateItem otherwise, and this only runs when the lookup
            // above found nothing.
            SecItemDelete(query)
            val status = SecItemAdd(query, null)
            if (status != errSecSuccess) {
                throw DatabaseKeyUnavailable(
                    "the Keychain would not store the local database key (OSStatus $status)",
                )
            }
        } finally {
            accessControl?.let { CFRelease(it) }
            CFRelease(data)
            CFRelease(query)
        }
    }

    /** Caller owns the returned dictionary and must [CFRelease] it. */
    private fun baseQuery(): CFMutableDictionaryRef {
        val query = CFDictionaryCreateMutable(
            kCFAllocatorDefault,
            5,
            kCFTypeDictionaryKeyCallBacks.ptr,
            kCFTypeDictionaryValueCallBacks.ptr,
        ) ?: throw DatabaseKeyUnavailable("could not allocate a Keychain query")

        CFDictionarySetValue(query, kSecClass, kSecClassGenericPassword)
        setString(query, kSecAttrService, service)
        setString(query, kSecAttrAccount, account)
        return query
    }

    /**
     * A Kotlin [String] goes in directly: `CFBridgingRetain` takes `Any?` and
     * Kotlin/Native bridges the string to an `NSString` on the way. Casting it
     * to `NSString` first compiles but warns that the cast can never succeed,
     * because the Kotlin type is not the Objective-C one.
     */
    private fun setString(dictionary: CFMutableDictionaryRef, key: CPointer<*>?, value: String) {
        val cf = CFBridgingRetain(value)
        try {
            CFDictionarySetValue(dictionary, key, cf)
        } finally {
            CFRelease(cf)
        }
    }

    companion object {
        const val SERVICE: String = "com.dcp.local-database"
        const val ACCOUNT: String = "default"
    }
}

@OptIn(ExperimentalForeignApi::class)
private fun NSData.toByteArray(): ByteArray {
    val size = length.toInt()
    val out = ByteArray(size)
    if (size > 0) {
        out.usePinned { memcpy(it.addressOf(0), bytes, length) }
    }
    return out
}

@OptIn(ExperimentalForeignApi::class, kotlinx.cinterop.BetaInteropApi::class)
private fun ByteArray.toNSData(): NSData = usePinned { pinned ->
    NSData.create(bytes = pinned.addressOf(0), length = size.toULong())
}
