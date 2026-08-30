package com.dcp.core.security

/**
 * The 256-bit key that encrypts this device's local SQLite database
 * (encryption envelope §14.3).
 *
 * Not one of the envelope's keys and never usable as one. A content key (§4.2)
 * hides a submission from the server; this key hides the whole local store from
 * whoever is holding the phone. The two protect against different people and
 * neither substitutes for the other, so this type deliberately lives outside
 * `com.dcp.core.crypto` and shares no code with it.
 *
 * The bytes come from a platform keystore via [DatabaseKeyStore] and never
 * leave the device: not synced, not wrapped, not backed up, not logged.
 */
class DatabaseKey(bytes: ByteArray) {

    init {
        require(bytes.size == SIZE_BYTES) {
            // Deliberately does not print the wrong-sized material.
            "a database key is $SIZE_BYTES bytes, got ${bytes.size}"
        }
    }

    private var material: ByteArray? = bytes.copyOf()

    /**
     * The raw key. Copied on read so a caller that zeroes what it was given
     * cannot zero the key itself — SQLCipher bindings routinely wipe the
     * passphrase array they are handed.
     */
    val bytes: ByteArray
        get() = requireNotNull(material) { "database key already destroyed" }.copyOf()

    /**
     * SQLCipher's raw-key literal, `x'<64 hex>'`.
     *
     * The `x'...'` form is what tells SQLCipher to use these bytes directly
     * rather than to run 256,000 PBKDF2 iterations over them as if they were a
     * password (§14.2). The key already carries 256 bits of entropy out of the
     * platform CSPRNG, so the KDF would add none — it would only cost roughly a
     * second of startup on the low-end hardware this platform targets.
     */
    fun rawKeyLiteral(): String = buildString(SIZE_BYTES * 2 + 3) {
        append("x'")
        appendHex(this@DatabaseKey.bytes)
        append('\'')
    }

    /** Lowercase hex, for bindings that take the key without the `x'...'` wrapper. */
    fun hex(): String = buildString(SIZE_BYTES * 2) { appendHex(bytes) }

    /**
     * Zeroes the copy held here. The platform binding that opened the database
     * keeps its own copy for the life of the connection — §14.8 is explicit
     * that a running, unlocked device is out of scope — so this narrows the
     * window rather than closing it.
     */
    fun destroy() {
        material?.fill(0)
        material = null
    }

    /**
     * Never renders the key. Overridden because the default `toString` would be
     * harmless and a data class's would not, and someone will eventually log
     * this object.
     */
    override fun toString(): String =
        "DatabaseKey(${if (material == null) "destroyed" else "$SIZE_BYTES bytes, redacted"})"

    companion object {
        const val SIZE_BYTES: Int = 32
    }
}

private const val HEX_DIGITS = "0123456789abcdef"

private fun StringBuilder.appendHex(bytes: ByteArray) {
    bytes.forEach { b ->
        val v = b.toInt() and 0xFF
        append(HEX_DIGITS[v ushr 4])
        append(HEX_DIGITS[v and 0x0F])
    }
}
