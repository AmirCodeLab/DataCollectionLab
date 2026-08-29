package com.dcp.core.crypto

/**
 * Lowercase hex, the encoding every binary field of the envelope crosses a wire
 * in (sync protocol §2.1, §4).
 *
 * Hand-rolled rather than platform-specific: this has to produce identical
 * bytes on the JVM, Android, iOS and Wasm, and it is small enough that a
 * per-platform expect/actual would cost more than it saves.
 */
object Hex {

    private const val DIGITS = "0123456789abcdef"

    fun encode(bytes: ByteArray): String = buildString(bytes.size * 2) {
        for (byte in bytes) {
            val value = byte.toInt() and 0xFF
            append(DIGITS[value ushr 4])
            append(DIGITS[value and 0x0F])
        }
    }

    /** @throws IllegalArgumentException on odd length or a non-hex character. */
    fun decode(text: String): ByteArray {
        require(text.length % 2 == 0) { "hex string must have an even length" }
        return ByteArray(text.length / 2) { i ->
            ((digit(text[i * 2]) shl 4) or digit(text[i * 2 + 1])).toByte()
        }
    }

    private fun digit(char: Char): Int {
        val value = when (char) {
            in '0'..'9' -> char - '0'
            in 'a'..'f' -> char - 'a' + 10
            // Accepted on the way in but never produced: a hand-written fixture
            // or a curl transcript should not fail for its letter case.
            in 'A'..'F' -> char - 'A' + 10
            else -> -1
        }
        require(value >= 0) { "not a hex character: '$char'" }
        return value
    }
}
