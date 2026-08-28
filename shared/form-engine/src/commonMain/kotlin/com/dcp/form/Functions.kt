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
            "today" -> FormValue.DateValue(ctx.today)
            "now" -> FormValue.Text(ctx.now)
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
            "int" -> numberOf(args[0])?.let { FormValue.Integer(it.toLong()) } ?: FormValue.Null
            "dec" -> numberOf(args[0])?.let { FormValue.Decimal(it) } ?: FormValue.Null
            "str" -> if (args[0].isNull) FormValue.Null else FormValue.Text(render(args[0]))
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
        val parts = iso.substring(0, 10).split("-")
        return Ymd(parts[0].toInt(), parts[1].toInt(), parts[2].toInt())
    }

    private fun isoDate(v: FormValue): Ymd? = when (v) {
        is FormValue.DateValue -> parse(v.iso)
        is FormValue.Text -> parse(v.value)
        else -> null
    }

    /** Integral decimals render as integers so results match the reference. */
    private fun FormValue.Decimal.simplify(): FormValue =
        if (value == kotlin.math.floor(value) && kotlin.math.abs(value) < 1e15) {
            FormValue.Integer(value.toLong())
        } else this
}
