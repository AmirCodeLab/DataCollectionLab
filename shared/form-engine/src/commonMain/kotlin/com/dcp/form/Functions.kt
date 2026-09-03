package com.dcp.form

import kotlin.math.PI
import kotlin.math.pow

/**
 * Function library (spec 4.3).
 *
 * Every function here must match the Python reference implementation exactly,
 * including null handling (§4.4) and type mismatch (§4.7): an argument that is
 * not of its declared type is null, and evaluation raises for exactly one
 * reason — integer overflow.
 */
object Functions {

    /**
     * Regex features §4.6 forbids, because RE2 cannot express them and the
     * reason RE2 is the rule is that backtracking on a respondent's answer is a
     * way to hang a phone.
     */
    private val FORBIDDEN_REGEX_FEATURES =
        listOf("(?=", "(?!", "(?<=", "(?<!", "\\1", "\\2")

    private data class Sig(val minArity: Int, val maxArity: Int)

    private val signatures = mapOf(
        "count" to Sig(1, 1),
        "sum" to Sig(1, 1),
        "min" to Sig(1, 1),
        "max" to Sig(1, 1),
        "count_selected" to Sig(1, 1),
        "coalesce" to Sig(1, 99),
        "today" to Sig(0, 0),
        "now" to Sig(0, 0),
        "age_years" to Sig(1, 2),
        "date_diff_days" to Sig(2, 2),
        "date_add_days" to Sig(2, 2),
        "len" to Sig(1, 1),
        "upper" to Sig(1, 1),
        "lower" to Sig(1, 1),
        "trim" to Sig(1, 1),
        "concat" to Sig(1, 99),
        "substr" to Sig(2, 3),
        "contains" to Sig(2, 2),
        "starts_with" to Sig(2, 2),
        "ends_with" to Sig(2, 2),
        "regex" to Sig(2, 2),
        "round" to Sig(1, 2),
        "int" to Sig(1, 1),
        "dec" to Sig(1, 1),
        "str" to Sig(1, 1),
        "distance" to Sig(2, 2),
        "is_null" to Sig(1, 1),
        "is_not_null" to Sig(1, 1),
    )

    fun call(fn: String, args: List<FormValue>, ctx: EvalContext): FormValue {
        val sig = signatures[fn] ?: throw CompileException("unknown function: $fn")
        if (args.size < sig.minArity || args.size > sig.maxArity) {
            throw CompileException(
                "function $fn expects ${sig.minArity}..${sig.maxArity} args, got ${args.size}"
            )
        }
        return when (fn) {
            "is_null" -> FormValue.Bool(args[0].isNull)
            "is_not_null" -> FormValue.Bool(!args[0].isNull)
            "count" -> FormValue.Integer(sequenceOf(args[0]).count { !it.isNull }.toLong())
            "count_selected" -> FormValue.Integer(
                if (args[0].isNull) 0L else sequenceOf(args[0]).size.toLong()
            )
            "sum" -> {
                val nums = sequenceOf(args[0]).mapNotNull { numberOf(it) }
                FormValue.Decimal(nums.sum()).simplify()
            }
            "min" -> sequenceOf(args[0]).mapNotNull { numberOf(it) }.minOrNull()
                ?.let { FormValue.Decimal(it).simplify() } ?: FormValue.Null
            "max" -> sequenceOf(args[0]).mapNotNull { numberOf(it) }.maxOrNull()
                ?.let { FormValue.Decimal(it).simplify() } ?: FormValue.Null
            "coalesce" -> args.firstOrNull { !it.isNull } ?: FormValue.Null
            // Dates are ISO text at runtime (spec 2.1); the reference's today()
            // returns a string, so returning DateValue here made comparisons
            // like `d <= today()` throw on this engine only.
            "today" -> FormValue.Text(ctx.today)
            "now" -> FormValue.Text(ctx.now)
            "date_diff_days" -> {
                val a = isoDate(args[0])
                val b = isoDate(args[1])
                if (a == null || b == null) FormValue.Null
                else FormValue.Integer(epochDays(a) - epochDays(b))
            }
            "date_add_days" -> {
                val a = isoDate(args[0])
                val days = integerOf(args[1])
                if (a == null || days == null) FormValue.Null
                else FormValue.Text(fromEpochDays(epochDays(a) + days))
            }
            "age_years" -> ageYears(args, ctx)
            "len" -> textOrNull(args[0])?.let { FormValue.Integer(it.length.toLong()) }
                ?: FormValue.Null
            "upper" -> textOrNull(args[0])?.let { FormValue.Text(it.uppercase()) } ?: FormValue.Null
            "lower" -> textOrNull(args[0])?.let { FormValue.Text(it.lowercase()) } ?: FormValue.Null
            "trim" -> textOrNull(args[0])?.let { FormValue.Text(it.trim()) } ?: FormValue.Null
            // The one function that renders rather than refuses (§4.7): its
            // job is to build text, so each argument is rendered the way `str`
            // renders it and a null contributes the empty string.
            "concat" -> FormValue.Text(
                args.joinToString("") { if (it.isNull) "" else castText(it)?.value ?: "" }
            )
            "contains" -> binaryText(args) { a, b -> a.contains(b) }
            "starts_with" -> binaryText(args) { a, b -> a.startsWith(b) }
            "ends_with" -> binaryText(args) { a, b -> a.endsWith(b) }
            "round" -> round(args)
            // §4.3.1. `castNumber`, not `numberOf`: a cast is the only way this
            // IR gets from text to a number, and a dataset column is always
            // text — a CSV holds nothing else — so `int($row.population)` is
            // the ordinary case. `numberOf` returns null for text and stays
            // that way, because it is what arithmetic uses and §4.5 has no
            // implicit coercion.
            "int" -> castNumber(args[0])?.let { FormValue.Integer(it.toLong()) } ?: FormValue.Null
            "dec" -> castNumber(args[0])?.let { FormValue.Decimal(it) } ?: FormValue.Null
            "str" -> if (args[0].isNull) FormValue.Null else castText(args[0]) ?: FormValue.Null
            "substr" -> substr(args)
            "regex" -> regex(args)
            "distance" -> distance(args[0], args[1])
            else -> throw CompileException("function not implemented: $fn")
        }
    }

    private fun sequenceOf(v: FormValue): List<FormValue> = when (v) {
        is FormValue.Null -> emptyList()
        is FormValue.Sequence -> v.items
        else -> listOf(v)
    }

    private fun numberOf(v: FormValue): Double? = when (v) {
        is FormValue.Integer -> v.value.toDouble()
        is FormValue.Decimal -> v.value
        else -> null
    }

    /**
     * A value as a number for `int`/`dec` (§4.3.1), or null if it is not one.
     *
     * Text is parsed after trimming surrounding whitespace and nothing else: a
     * thousands separator or a currency symbol makes it unparseable rather than
     * being stripped, because stripping one would be a coercion this IR does
     * not have (§4.5).
     *
     * Unparseable text is null, never an error — a cast is evaluated on every
     * keystroke over whatever has been typed so far, and `int("8a")` on the way
     * to `int("81")` must not stop the form.
     *
     * Booleans are deliberately not numbers: §4.4 keeps booleans and numbers
     * apart everywhere else, and a dynamically typed engine's `int(true) == 1`
     * would be a divergence no vector had ever asked about. Break 44.
     */
    private fun castNumber(v: FormValue): Double? = when (v) {
        is FormValue.Integer -> v.value.toDouble()
        is FormValue.Decimal -> v.value
        is FormValue.Text -> v.value.trim().toDoubleOrNull()
        else -> null
    }

    /**
     * A value rendered by `str` (§4.3.1), or null where §4.3.1 gives no text.
     *
     * A geopoint, a media reference and a sequence have no rendering the two
     * engines could be held to, so they are null rather than each engine's
     * `toString`.
     */
    private fun castText(v: FormValue): FormValue.Text? = when (v) {
        is FormValue.Text -> v
        is FormValue.Integer -> FormValue.Text(v.value.toString())
        // `str(dec("800"))` is "800", so it can be compared against a text
        // column. A trailing `.0` is an artefact of the double, not the value.
        is FormValue.Decimal -> FormValue.Text(
            if (v.value % 1.0 == 0.0) v.value.toLong().toString() else v.value.toString()
        )
        is FormValue.Bool -> FormValue.Text(if (v.value) "true" else "false")
        else -> null
    }

    private fun textOrNull(v: FormValue): String? = (v as? FormValue.Text)?.value

    private fun render(v: FormValue): String = when (v) {
        is FormValue.Text -> v.value
        is FormValue.Integer -> v.value.toString()
        is FormValue.Decimal -> v.value.toString()
        is FormValue.Bool -> v.value.toString()
        is FormValue.DateValue -> v.iso
        else -> v.toString()
    }

    /** `(text, integer, integer?) → text`, 0-based (spec 4.3). */
    private fun substr(args: List<FormValue>): FormValue {
        val text = textOrNull(args[0]) ?: return FormValue.Null
        val start = (integerOf(args[1]) ?: return FormValue.Null).toInt()
        val from = start.coerceIn(0, text.length)
        if (args.size > 2 && !args[2].isNull) {
            val length = (integerOf(args[2]) ?: return FormValue.Null).toInt()
            val to = (from + length).coerceIn(from, text.length)
            return FormValue.Text(text.substring(from, to))
        }
        return FormValue.Text(text.substring(from))
    }

    /**
     * `(text, pattern) → boolean`, RE2 syntax only (spec 4.6).
     *
     * Matches anywhere in the subject, like the reference's `re.search`.
     *
     * A pattern using a feature §4.6 forbids is **null**, not an exception —
     * §4.7 permits evaluation to raise only on integer overflow, and the
     * pattern is not executed either way. Refusing such a form is the publish
     * gate's job (`forms.service.check_publishable`), where somebody is reading.
     */
    private fun regex(args: List<FormValue>): FormValue {
        val subject = textOrNull(args[0]) ?: return FormValue.Null
        val pattern = textOrNull(args[1]) ?: return FormValue.Null
        if (FORBIDDEN_REGEX_FEATURES.any { it in pattern }) return FormValue.Null
        val compiled = try {
            Regex(pattern)
        } catch (_: IllegalArgumentException) {
            // A pattern that is not a pattern is not something to match
            // against, and a half-typed one is the ordinary state of a form
            // being authored.
            return FormValue.Null
        }
        return FormValue.Bool(compiled.containsMatchIn(subject))
    }

    /** `(geopoint, geopoint) → decimal` — metres, haversine, WGS-84 (spec 4.3). */
    private fun distance(a: FormValue, b: FormValue): FormValue {
        val p = a as? FormValue.GeoPoint ?: return FormValue.Null
        val q = b as? FormValue.GeoPoint ?: return FormValue.Null
        val radius = 6371008.8 // WGS-84 mean radius, metres — the reference's constant
        val lat1 = p.lat * PI / 180.0
        val lon1 = p.lon * PI / 180.0
        val lat2 = q.lat * PI / 180.0
        val lon2 = q.lon * PI / 180.0
        val dLat = lat2 - lat1
        val dLon = lon2 - lon1
        val h = kotlin.math.sin(dLat / 2).pow(2) +
            kotlin.math.cos(lat1) * kotlin.math.cos(lat2) * kotlin.math.sin(dLon / 2).pow(2)
        return FormValue.Decimal(2 * radius * kotlin.math.asin(kotlin.math.sqrt(h)))
    }

    private fun binaryText(args: List<FormValue>, op: (String, String) -> Boolean): FormValue {
        val a = textOrNull(args[0]) ?: return FormValue.Null
        val b = textOrNull(args[1]) ?: return FormValue.Null
        return FormValue.Bool(op(a, b))
    }

    /**
     * Beyond this many digits a decimal has no more information to give, so a
     * request for them is not a question about this number. Bounded rather than
     * clamped, because §4.7 does not permit evaluation to produce a non-finite
     * result any more than it permits an exception.
     */
    private const val MAX_ROUND_DIGITS = 15

    /** Half away from zero, NOT banker's rounding (spec 4.5). */
    private fun round(args: List<FormValue>): FormValue {
        val x = numberOf(args[0]) ?: return FormValue.Null
        val digits = if (args.size > 1 && !args[1].isNull) {
            (integerOf(args[1]) ?: return FormValue.Null).toInt()
        } else 0
        if (digits < -MAX_ROUND_DIGITS || digits > MAX_ROUND_DIGITS) return FormValue.Null
        // Negative digits round to tens, hundreds and so on, so the factor has
        // to divide rather than be skipped: `repeat(-2)` does nothing at all,
        // and `round(1234, -2)` came back 1234 on this engine and 1200 on the
        // reference.
        var factor = 1.0
        repeat(kotlin.math.abs(digits)) { factor *= 10 }
        if (digits < 0) factor = 1.0 / factor
        val scaled = x * factor
        val rounded = if (scaled >= 0) {
            kotlin.math.floor(scaled + 0.5)
        } else {
            kotlin.math.ceil(scaled - 0.5)
        }
        return if (digits > 0) FormValue.Decimal(rounded / factor)
        else FormValue.Integer(rounded.toLong())
    }

    private fun ageYears(args: List<FormValue>, ctx: EvalContext): FormValue {
        val born = isoDate(args[0]) ?: return FormValue.Null
        val ref =
            if (args.size > 1 && !args[1].isNull) isoDate(args[1]) ?: return FormValue.Null
            else parseOrNull(ctx.today) ?: return FormValue.Null
        var years = ref.year - born.year
        if (ref.month < born.month || (ref.month == born.month && ref.day < born.day)) years -= 1
        return FormValue.Integer(years.toLong())
    }

    private data class Ymd(val year: Int, val month: Int, val day: Int)

    /**
     * An ISO date, or null when the text is not one (§4.7).
     *
     * Never raises. A half-typed date is the ordinary state of a date field
     * mid-interview, and `date_diff_days("2026-01", today())` must not stop a
     * form — the Python reference raised ValueError here and it reached the API
     * as a 500.
     */
    private fun parseOrNull(iso: String): Ymd? {
        val parts = if (iso.length >= 10) iso.substring(0, 10).split("-") else return null
        if (parts.size != 3) return null
        val y = parts[0].toIntOrNull() ?: return null
        val m = parts[1].toIntOrNull() ?: return null
        val d = parts[2].toIntOrNull() ?: return null
        // A well-shaped string that is not a date on any calendar is not a date.
        if (m !in 1..12 || d !in 1..daysInMonth(y, m)) return null
        return Ymd(y, m, d)
    }

    private fun daysInMonth(year: Int, month: Int): Int = when (month) {
        1, 3, 5, 7, 8, 10, 12 -> 31
        4, 6, 9, 11 -> 30
        else -> if ((year % 4 == 0 && year % 100 != 0) || year % 400 == 0) 29 else 28
    }

    /** The value as a date (§4.3), or null when it is not one (§4.7). */
    private fun isoDate(v: FormValue): Ymd? = when (v) {
        is FormValue.DateValue -> parseOrNull(v.iso)
        is FormValue.Text -> parseOrNull(v.value)
        else -> null
    }

    /**
     * The value as an integer, for arguments §4.3 declares `integer` (§4.7).
     *
     * A whole-valued decimal counts: `date_add_days(d, 3.0)` is the same
     * question as `date_add_days(d, 3)`, and refusing one would make the answer
     * depend on how the number was arrived at.
     */
    private fun integerOf(v: FormValue): Long? = when (v) {
        is FormValue.Integer -> v.value
        is FormValue.Decimal -> if (v.value % 1.0 == 0.0) v.value.toLong() else null
        else -> null
    }

    // Civil-date <-> epoch-day conversion (Howard Hinnant's algorithms), so day
    // arithmetic works identically on JVM, Native and Wasm.

    private fun epochDays(d: Ymd): Long {
        val y = (if (d.month <= 2) d.year - 1 else d.year).toLong()
        val era = (if (y >= 0) y else y - 399).floorDiv(400)
        val yoe = y - era * 400
        val mp = if (d.month > 2) d.month - 3 else d.month + 9
        val doy = (153 * mp + 2) / 5 + d.day - 1
        val doe = yoe * 365 + yoe / 4 - yoe / 100 + doy
        return era * 146_097 + doe - 719_468
    }

    private fun fromEpochDays(days: Long): String {
        val z = days + 719_468
        val era = (if (z >= 0) z else z - 146_096).floorDiv(146_097)
        val doe = z - era * 146_097
        val yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365
        val y = yoe + era * 400
        val doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
        val mp = (5 * doy + 2) / 153
        val day = doy - (153 * mp + 2) / 5 + 1
        val month = if (mp < 10) mp + 3 else mp - 9
        val year = if (month <= 2) y + 1 else y
        return "${year.toString().padStart(4, '0')}-" +
            "${month.toString().padStart(2, '0')}-" +
            day.toString().padStart(2, '0')
    }

    /** Integral decimals render as integers so results match the reference. */
    private fun FormValue.Decimal.simplify(): FormValue =
        if (value == kotlin.math.floor(value) && kotlin.math.abs(value) < 1e15) {
            FormValue.Integer(value.toLong())
        } else this
}
