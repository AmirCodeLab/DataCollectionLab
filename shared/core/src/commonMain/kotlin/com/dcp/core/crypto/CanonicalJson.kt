package com.dcp.core.crypto

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

/**
 * Canonical JSON serialisation (encryption envelope spec 5.1).
 *
 * MUST produce the same bytes as `canonical_json` in
 * backend/app/modules/crypto/envelope.py — Python's
 * `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
 * encoded as UTF-8. The same answer must encrypt to the same ciphertext on
 * every platform, or cross-platform conformance vectors cannot exist.
 *
 * The three places Python and Kotlin disagree by default, all handled here:
 * - float formatting (Python repr vs Double.toString exponent thresholds)
 * - object key order (Python sorts by code point; Kotlin strings compare by
 *   UTF-16 unit, which differs for keys beyond the BMP)
 * - string escaping (Python escapes only `"`, `\` and control characters)
 */
object CanonicalJson {

    fun encode(value: JsonElement): ByteArray =
        buildString { write(this, value) }.encodeToByteArray()

    private fun write(sb: StringBuilder, value: JsonElement) {
        when (value) {
            is JsonNull -> sb.append("null")
            is JsonPrimitive -> writePrimitive(sb, value)
            is JsonArray -> {
                sb.append('[')
                value.forEachIndexed { i, item ->
                    if (i > 0) sb.append(',')
                    write(sb, item)
                }
                sb.append(']')
            }
            is JsonObject -> {
                sb.append('{')
                value.keys.sortedWith(::compareCodePoints).forEachIndexed { i, key ->
                    if (i > 0) sb.append(',')
                    writeString(sb, key)
                    sb.append(':')
                    write(sb, value.getValue(key))
                }
                sb.append('}')
            }
        }
    }

    private fun writePrimitive(sb: StringBuilder, value: JsonPrimitive) {
        val content = value.content
        when {
            value.isString -> writeString(sb, content)
            content == "true" || content == "false" -> sb.append(content)
            // Integers pass through verbatim: Python ints are arbitrary
            // precision, so re-parsing through Long could corrupt them.
            INT_PATTERN.matches(content) -> sb.append(content)
            else -> sb.append(formatDouble(content.toDouble()))
        }
    }

    private val INT_PATTERN = Regex("^-?[0-9]+$")

    private fun writeString(sb: StringBuilder, s: String) {
        sb.append('"')
        for (ch in s) {
            when {
                ch == '"' -> sb.append("\\\"")
                ch == '\\' -> sb.append("\\\\")
                ch == '\n' -> sb.append("\\n")
                ch == '\t' -> sb.append("\\t")
                ch == '\r' -> sb.append("\\r")
                ch == '\b' -> sb.append("\\b")
                ch == '\u000C' -> sb.append("\\f")
                ch < ' ' -> {
                    sb.append("\\u")
                    sb.append(ch.code.toString(16).padStart(4, '0'))
                }
                else -> sb.append(ch)
            }
        }
        sb.append('"')
    }

    /**
     * Format a double exactly as Python's `repr` does: shortest round-tripping
     * digits, fixed notation for decimal exponents in [-4, 16), otherwise
     * scientific with a signed, two-digit-minimum exponent.
     *
     * Double.toString already yields shortest round-tripping digits; only the
     * presentation (exponent thresholds and style) differs, so the digits are
     * extracted and re-styled.
     */
    internal fun formatDouble(d: Double): String {
        require(!d.isNaN() && !d.isInfinite()) { "NaN and Infinity are not valid JSON" }
        if (d == 0.0) return if (1.0 / d < 0.0) "-0.0" else "0.0"

        val sign = if (d < 0.0) "-" else ""
        val raw = kotlin.math.abs(d).toString()

        val eIndex = raw.indexOfFirst { it == 'e' || it == 'E' }
        val mantissa = if (eIndex >= 0) raw.substring(0, eIndex) else raw
        val exp10 = if (eIndex >= 0) raw.substring(eIndex + 1).toInt() else 0

        val dot = mantissa.indexOf('.')
        val allDigits = if (dot >= 0) mantissa.removeRange(dot, dot + 1) else mantissa
        val pointPos = if (dot >= 0) dot else mantissa.length

        val firstSignificant = allDigits.indexOfFirst { it != '0' }
        // d != 0 was handled above, so a significant digit exists.
        val digits = allDigits.substring(firstSignificant).trimEnd('0').ifEmpty { "0" }
        // Scientific exponent: value == digits[0] "." digits[1..] × 10^e
        val e = pointPos - 1 - firstSignificant + exp10

        val formatted = if (e in -4..15) {
            when {
                e >= digits.length - 1 -> digits + "0".repeat(e - digits.length + 1) + ".0"
                e >= 0 -> digits.substring(0, e + 1) + "." + digits.substring(e + 1)
                else -> "0." + "0".repeat(-e - 1) + digits
            }
        } else {
            val m = if (digits.length > 1) digits[0] + "." + digits.substring(1) else digits
            val expDigits = kotlin.math.abs(e).toString().padStart(2, '0')
            m + "e" + (if (e < 0) "-" else "+") + expDigits
        }
        return sign + formatted
    }

    /** Python string comparison is by Unicode code point, not UTF-16 unit. */
    private fun compareCodePoints(a: String, b: String): Int {
        var i = 0
        var j = 0
        while (i < a.length && j < b.length) {
            val ca = codePointAt(a, i)
            val cb = codePointAt(b, j)
            if (ca != cb) return ca.compareTo(cb)
            i += if (ca > 0xFFFF) 2 else 1
            j += if (cb > 0xFFFF) 2 else 1
        }
        return (a.length - i).compareTo(b.length - j)
    }

    private fun codePointAt(s: String, index: Int): Int {
        val high = s[index]
        if (high.isHighSurrogate() && index + 1 < s.length && s[index + 1].isLowSurrogate()) {
            return (high.code - 0xD800 shl 10) + (s[index + 1].code - 0xDC00) + 0x10000
        }
        return high.code
    }
}
