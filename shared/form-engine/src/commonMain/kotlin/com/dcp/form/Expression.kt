package com.dcp.form

/**
 * Expression AST and evaluator.
 *
 * This MUST produce results identical to the Python reference implementation in
 * backend/app/modules/form_engine/expression.py for every conformance vector.
 * Spec: specs/form-ir-v0.1.md sections 4 and 5.
 */

class EvaluationException(message: String) : Exception(message)
class CompileException(message: String) : Exception(message)

/**
 * A form value. [Null] is a first-class value, not an absence, because the
 * spec's null semantics (4.4) depend on propagating it explicitly.
 */
sealed interface FormValue {
    data object Null : FormValue
    data class Text(val value: String) : FormValue
    data class Integer(val value: Long) : FormValue
    data class Decimal(val value: Double) : FormValue
    data class Bool(val value: Boolean) : FormValue
    data class DateValue(val iso: String) : FormValue
    data class Sequence(val items: List<FormValue>) : FormValue
    data class GeoPoint(val lat: Double, val lon: Double) : FormValue
}

val FormValue.isNull: Boolean get() = this is FormValue.Null

sealed interface Expr {
    data class Lit(val value: FormValue) : Expr
    data class Ref(val path: String) : Expr
    data class Op(val op: String, val args: List<Expr>) : Expr
    data class Call(val fn: String, val args: List<Expr>) : Expr
}

data class EvalContext(
    val values: Map<String, FormValue>,
    val today: String,
    val now: String,
    val row: Map<String, FormValue>? = null,
    val metadata: Map<String, FormValue> = emptyMap(),
)

object Evaluator {

    fun evaluate(expr: Expr, ctx: EvalContext): FormValue = when (expr) {
        is Expr.Lit -> expr.value
        is Expr.Ref -> resolve(expr.path, ctx)
        is Expr.Op -> evalOp(expr, ctx)
        is Expr.Call -> Functions.call(expr.fn, expr.args.map { evaluate(it, ctx) }, ctx)
    }

    private fun resolve(path: String, ctx: EvalContext): FormValue {
        if (path.startsWith("\$row.")) {
            val row = ctx.row ?: throw CompileException("\$row reference outside a choice filter: $path")
            return row[path.removePrefix("\$row.")] ?: FormValue.Null
        }
        if (path.startsWith("_metadata.")) {
            return ctx.metadata[path.removePrefix("_metadata.")] ?: FormValue.Null
        }
        if (path.endsWith("[]") || path.contains("[].")) {
            val prefix = path.substringBefore("[]")
            val suffix = if (path.contains("[].")) path.substringAfter("[].") else null
            val items = ctx.values.entries
                .filter { it.key.startsWith("$prefix[") }
                .filter { suffix == null || it.key.endsWith(".$suffix") }
                .map { it.value }
            return FormValue.Sequence(items)
        }
        return ctx.values[path] ?: throw CompileException("unresolvable reference: $path")
    }

    private fun evalOp(expr: Expr.Op, ctx: EvalContext): FormValue {
        // `if` is lazy in both branches (spec 4.3)
        if (expr.op == "if") {
            val cond = evaluate(expr.args[0], ctx)
            if (cond.isNull) return FormValue.Null
            val takeThen = (cond as? FormValue.Bool)?.value
                ?: throw EvaluationException("if() condition must be boolean")
            return evaluate(if (takeThen) expr.args[1] else expr.args[2], ctx)
        }

        val args = expr.args.map { evaluate(it, ctx) }

        return when (expr.op) {
            "and" -> and(args)
            "or" -> or(args)
            "not" -> not(args[0])
            "neg" -> when (val a = args[0]) {
                is FormValue.Integer -> FormValue.Integer(-a.value)
                is FormValue.Decimal -> FormValue.Decimal(-a.value)
                else -> FormValue.Null
            }
            "add", "sub", "mul", "mod" -> arithmetic(expr.op, args[0], args[1])
            "div" -> divide(args[0], args[1])
            "idiv" -> integerDivide(args[0], args[1])
            "eq", "ne", "lt", "lte", "gt", "gte" -> compare(expr.op, args[0], args[1])
            "selected" -> selected(args[0], args[1])
            "in" -> selected(args[1], args[0])
            else -> throw CompileException("unknown operator: ${expr.op}")
        }
    }

    // -- null-aware primitives (spec 4.4) ---------------------------------

    /** false dominates null; otherwise null propagates (spec 4.4.5). */
    private fun and(args: List<FormValue>): FormValue {
        if (args.any { it is FormValue.Bool && !it.value }) return FormValue.Bool(false)
        if (args.any { it.isNull }) return FormValue.Null
        return FormValue.Bool(true)
    }

    /** true dominates null; otherwise null propagates (spec 4.4.6). */
    private fun or(args: List<FormValue>): FormValue {
        if (args.any { it is FormValue.Bool && it.value }) return FormValue.Bool(true)
        if (args.any { it.isNull }) return FormValue.Null
        return FormValue.Bool(false)
    }

    private fun not(a: FormValue): FormValue = when (a) {
        is FormValue.Null -> FormValue.Null
        is FormValue.Bool -> FormValue.Bool(!a.value)
        else -> throw EvaluationException("not() expects a boolean")
    }

    private fun asDouble(v: FormValue): Double? = when (v) {
        is FormValue.Integer -> v.value.toDouble()
        is FormValue.Decimal -> v.value
        else -> null
    }

    /** Any arithmetic with a null operand yields null (spec 4.4.2). */
    private fun arithmetic(op: String, a: FormValue, b: FormValue): FormValue {
        if (a.isNull || b.isNull) return FormValue.Null
        if (a is FormValue.Integer && b is FormValue.Integer) {
            val result = when (op) {
                "add" -> addExact(a.value, b.value)
                "sub" -> subtractExact(a.value, b.value)
                "mul" -> multiplyExact(a.value, b.value)
                "mod" -> if (b.value == 0L) return FormValue.Null else a.value % b.value
                else -> throw CompileException("unknown arithmetic op: $op")
            }
            return FormValue.Integer(result)
        }
        val x = asDouble(a) ?: throw EvaluationException("non-numeric operand")
        val y = asDouble(b) ?: throw EvaluationException("non-numeric operand")
        return when (op) {
            "add" -> FormValue.Decimal(x + y)
            "sub" -> FormValue.Decimal(x - y)
            "mul" -> FormValue.Decimal(x * y)
            "mod" -> if (y == 0.0) FormValue.Null else FormValue.Decimal(x % y)
            else -> throw CompileException("unknown arithmetic op: $op")
        }
    }

    // Overflow-checked 64-bit arithmetic without java.lang.Math, so the same
    // code compiles on JVM, Native and Wasm. Overflow is an evaluation error,
    // not a wrap (spec 4.5).

    private fun addExact(a: Long, b: Long): Long {
        val r = a + b
        if (((a xor r) and (b xor r)) < 0) throw EvaluationException("integer overflow")
        return r
    }

    private fun subtractExact(a: Long, b: Long): Long {
        val r = a - b
        if (((a xor b) and (a xor r)) < 0) throw EvaluationException("integer overflow")
        return r
    }

    private fun multiplyExact(a: Long, b: Long): Long {
        if (a == 0L || b == 0L) return 0L
        if (a == -1L) {
            if (b == Long.MIN_VALUE) throw EvaluationException("integer overflow")
            return -b
        }
        if (b == -1L) {
            if (a == Long.MIN_VALUE) throw EvaluationException("integer overflow")
            return -a
        }
        val r = a * b
        if (r / b != a) throw EvaluationException("integer overflow")
        return r
    }

    /** Division by zero yields null, never an error or infinity (spec 4.4.8). */
    private fun divide(a: FormValue, b: FormValue): FormValue {
        if (a.isNull || b.isNull) return FormValue.Null
        val x = asDouble(a) ?: return FormValue.Null
        val y = asDouble(b) ?: return FormValue.Null
        if (y == 0.0) return FormValue.Null
        return FormValue.Decimal(x / y)
    }

    private fun integerDivide(a: FormValue, b: FormValue): FormValue {
        if (a.isNull || b.isNull) return FormValue.Null
        val x = asDouble(a) ?: return FormValue.Null
        val y = asDouble(b) ?: return FormValue.Null
        if (y == 0.0) return FormValue.Null
        return FormValue.Integer(kotlin.math.floor(x / y).toLong())
    }

    /** Any comparison with a null operand yields null, not false (spec 4.4.3). */
    private fun compare(op: String, a: FormValue, b: FormValue): FormValue {
        if (a.isNull || b.isNull) return FormValue.Null

        if (a is FormValue.Text && b is FormValue.Text) {
            return FormValue.Bool(
                when (op) {
                    "eq" -> a.value == b.value
                    "ne" -> a.value != b.value
                    "lt" -> a.value < b.value
                    "lte" -> a.value <= b.value
                    "gt" -> a.value > b.value
                    "gte" -> a.value >= b.value
                    else -> throw CompileException("unknown comparison: $op")
                }
            )
        }

        if (a is FormValue.Bool && b is FormValue.Bool) {
            return when (op) {
                "eq" -> FormValue.Bool(a.value == b.value)
                "ne" -> FormValue.Bool(a.value != b.value)
                else -> throw EvaluationException("cannot order booleans")
            }
        }

        if (a is FormValue.Text != b is FormValue.Text) {
            throw EvaluationException("cannot compare text with non-text")
        }

        val x = asDouble(a) ?: throw EvaluationException("non-comparable operand")
        val y = asDouble(b) ?: throw EvaluationException("non-comparable operand")
        return FormValue.Bool(
            when (op) {
                "eq" -> x == y
                "ne" -> x != y
                "lt" -> x < y
                "lte" -> x <= y
                "gt" -> x > y
                "gte" -> x >= y
                else -> throw CompileException("unknown comparison: $op")
            }
        )
    }

    private fun selected(haystack: FormValue, needle: FormValue): FormValue {
        if (haystack.isNull || needle.isNull) return FormValue.Null
        val items = when (haystack) {
            is FormValue.Sequence -> haystack.items
            else -> listOf(haystack)
        }
        return FormValue.Bool(items.any { it == needle })
    }

    /**
     * Boundary coercion (spec 4.4.7). Null becomes [nullIs].
     * This is the ONLY place a null becomes a boolean.
     */
    fun coerceBoolean(value: FormValue, nullIs: Boolean): Boolean = when (value) {
        is FormValue.Null -> nullIs
        is FormValue.Bool -> value.value
        else -> throw EvaluationException("expected boolean at boundary, got $value")
    }
}
