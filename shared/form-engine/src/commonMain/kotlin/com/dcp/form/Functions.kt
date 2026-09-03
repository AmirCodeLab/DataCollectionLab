package com.dcp.form

/**
 * Function library (spec 4.3).
 *
 * Every function here must match the Python reference implementation exactly,
 * including null handling and rounding mode.
 */
object Functions {

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
                val a = parseDateOrNull(args[0])
                val b = parseDateOrNull(args[1])
                if (a == null || b == null) FormValue.Null
                else FormValue.Integer(epochDays(a) - epochDays(b))
            }
            "date_add_days" -> {
                val a = parseDateOrNull(args[0])
                val days = args[1]
                if (a == null || days.isNull) FormValue.Null
                else FormValue.Text(
                    fromEpochDays(
                        epochDays(a) + (numberOf(days)?.toLong()
                            ?: throw EvaluationException("date_add_days expects a number of days"))
                    )
                )
            }
            "age_years" -> ageYears(args, ctx)
            "len" -> textOrNull(args[0])?.let { FormValue.Integer(it.length.toLong()) }
                ?: FormValue.Null
            "upper" -> textOrNull(args[0])?.let { FormValue.Text(it.uppercase()) } ?: FormValue.Null
            "lower" -> textOrNull(args[0])?.let { FormValue.Text(it.lowercase()) } ?: FormValue.Null
            "trim" -> textOrNull(args[0])?.let { FormValue.Text(it.trim()) } ?: FormValue.Null
            "concat" -> FormValue.Text(args.joinToString("") { textOrNull(it) ?: "" })
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

    private fun binaryText(args: List<FormValue>, op: (String, String) -> Boolean): FormValue {
        val a = textOrNull(args[0]) ?: return FormValue.Null
        val b = textOrNull(args[1]) ?: return FormValue.Null
        return FormValue.Bool(op(a, b))
    }

    /** Half away from zero, NOT banker's rounding (spec 4.5). */
    private fun round(args: List<FormValue>): FormValue {
        val x = numberOf(args[0]) ?: return FormValue.Null
        val digits = if (args.size > 1) numberOf(args[1])?.toInt() ?: 0 else 0
        var factor = 1.0
        repeat(digits) { factor *= 10 }
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
        val ref = if (args.size > 1 && !args[1].isNull) isoDate(args[1])!! else parse(ctx.today)
        var years = ref.year - born.year
        if (ref.month < born.month || (ref.month == born.month && ref.day < born.day)) years -= 1
        return FormValue.Integer(years.toLong())
    }

    private data class Ymd(val year: Int, val month: Int, val day: Int)

    private fun parse(iso: String): Ymd {
        val parts = if (iso.length >= 10) iso.substring(0, 10).split("-") else emptyList()
        if (parts.size != 3) throw EvaluationException("invalid date: '$iso'")
        return Ymd(
            parts[0].toIntOrNull() ?: throw EvaluationException("invalid date: '$iso'"),
            parts[1].toIntOrNull() ?: throw EvaluationException("invalid date: '$iso'"),
            parts[2].toIntOrNull() ?: throw EvaluationException("invalid date: '$iso'"),
        )
    }

    private fun isoDate(v: FormValue): Ymd? = when (v) {
        is FormValue.DateValue -> parse(v.iso)
        is FormValue.Text -> parse(v.value)
        else -> null
    }

    /** Mirrors the reference `_parse_date`: null passes through, a non-date
     * operand is an evaluation error. */
    private fun parseDateOrNull(v: FormValue): Ymd? = when (v) {
        is FormValue.Null -> null
        is FormValue.DateValue -> parse(v.iso)
        is FormValue.Text -> parse(v.value)
        else -> throw EvaluationException("expected date, got $v")
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
