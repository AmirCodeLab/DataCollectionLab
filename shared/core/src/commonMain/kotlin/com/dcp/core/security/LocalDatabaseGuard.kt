package com.dcp.core.security

/**
 * The runtime check that stands between "we call PRAGMA key" and "the database
 * is actually encrypted" (encryption envelope §14.5).
 *
 * These are not the same claim. SQLite treats an unrecognised pragma as a no-op
 * and returns no error, so a build linked against plain SQLite instead of
 * SQLCipher runs perfectly, passes every functional test, and writes the whole
 * op log to disk in the clear. Nothing about that failure is visible from
 * inside the application — which is exactly why it has to be checked from
 * outside, against the bytes on disk.
 *
 * The check is one string comparison: every cleartext SQLite file begins with
 * the header below, and no SQLCipher file can, because SQLCipher puts its
 * 16-byte random salt in those same bytes.
 */
object LocalDatabaseGuard {

    /**
     * The first 16 bytes of every unencrypted SQLite 3 database file: the
     * ASCII text "SQLite format 3" and a NUL.
     */
    val CLEARTEXT_HEADER: ByteArray = "SQLite format 3\u0000".encodeToByteArray()

    /**
     * True when [header] — the first bytes of a database file — says the file is
     * an unencrypted SQLite database.
     *
     * A file shorter than the header, or one that does not exist, is not
     * cleartext: SQLDelight has not written a page yet.
     */
    fun isCleartext(header: ByteArray?): Boolean {
        if (header == null || header.size < CLEARTEXT_HEADER.size) return false
        return CLEARTEXT_HEADER.indices.all { header[it] == CLEARTEXT_HEADER[it] }
    }

    /**
     * Throws unless the file the header came from is encrypted.
     *
     * Deliberately fatal. There is no "encryption unavailable, continuing"
     * branch anywhere in this file and there must not be one added: an
     * enumerator whose app refuses to start files a support ticket, and an
     * enumerator whose app quietly stopped encrypting files nothing.
     */
    fun requireEncrypted(path: String, header: ByteArray?) {
        if (isCleartext(header)) {
            throw LocalDatabaseNotEncrypted(
                "the local database at $path is a cleartext SQLite file. The build is " +
                    "linked against plain SQLite, not SQLCipher, so PRAGMA key was " +
                    "silently ignored (encryption envelope §14.5). Refusing to use it.",
            )
        }
    }
}

/**
 * The local database is not encrypted and the application must not carry on.
 * Separate from a generic failure so a launcher can tell "this device is
 * misbuilt" from "this device's keystore said no".
 */
class LocalDatabaseNotEncrypted(message: String) : IllegalStateException(message)

/**
 * The platform keystore would not produce the database key: no keystore, a
 * keystore that refused, or an app lock the user did not satisfy.
 *
 * §14.5 forbids falling back to an unencrypted database, so every caller of
 * [DatabaseKeyStore] has exactly two outcomes — a key, or this.
 */
class DatabaseKeyUnavailable(message: String, cause: Throwable? = null) :
    IllegalStateException(message, cause)
