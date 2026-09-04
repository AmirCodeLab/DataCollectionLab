package com.dcp.form

/**
 * Expression AST and evaluator.
 *
 * This MUST produce results identical to the Python reference implementation in
 * backend/app/modules/form_engine/expression.py for every conformance vector.
 * Spec: specs/form-ir-v0.1.md sections 4 and 5.
 */

class EvaluationException(message: String) : Exception(message)

/** Open so [DocumentException] can be one — see Document.kt. */
open class CompileException(message: String) : Exception(message)

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

    /**
     * A point, per the spec's `{lat, lon, alt?, accuracy?}` (§2.1).
     *
     * [accuracy] is metres of horizontal uncertainty as the device reported it,
     * and it is carried rather than checked-and-discarded on purpose: a project
     * can tighten its threshold later, and a point collected under the old one
     * has to keep saying how good it actually was. A point with no accuracy is
     * a point from a source that did not say — a manual entry, an import — not
     * a perfect one.
     */
    data class GeoPoint(
        val lat: Double,
        val lon: Double,
        val alt: Double? = null,
        val accuracy: Double? = null,
    ) : FormValue

    /**
     * A media reference, per the spec's `{id, filename, hash, size}` (§2.1) —
     * the value of an `image`, `audio`, `video`, `file`, `signature` or
     * `drawing` question.
     *
     * The file itself never travels in the operation stream (sync §9): this is
     * the whole of what an answer holds, and the bytes arrive separately.
     * [hash] addresses the CIPHERTEXT (encryption envelope §6) while [size] is
     * the plaintext size — they describe different things, and conflating them
     * would either break content addressing or tell a reader the wrong size.
     */
    data class MediaRef(
        val id: String,
        val filename: String,
        val hash: String,
        val size: Long,
    ) : FormValue
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
    /** (repeatId, instanceId) when evaluating inside a repeat instance. */
    val scope: Pair<String, String>? = null,
    /** repeat id -> ordered instance ids, for positional addressing. */
    val instances: Map<String, List<String>>? = null,
    /**
     * Where `pulldata` reads reference data from (§4.3). Null when the caller
     * built no source — `pulldata` is then null, like every other argument that
     * is not what §4.3 declares (§4.7), rather than an exception on a device
     * that has not finished syncing.
     */
    val datasets: DatasetSource? = null,
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

        val instances = ctx.instances.orEmpty()

        // members[].age -> sequence across every instance, in order (spec 4.2)
        if ("[]." in path) {
            val repeatId = path.substringBefore("[].")
            val suffix = path.substringAfter("[].")
            return FormValue.Sequence(
                instances[repeatId].orEmpty().map {
                    ctx.values["$repeatId[$it].$suffix"] ?: FormValue.Null
                }
            )
        }

        // members[0].age -> a specific instance by position
        if ("[" in path && "]." in path) {
            val repeatId = path.substringBefore("[")
            val rest = path.substringAfter("[")
            val indexText = rest.substringBefore("].")
            val suffix = rest.substringAfter("].")
            if (indexText == ".") {
                // members[.].age -> the current instance
                val scope = ctx.scope
                if (scope == null || scope.first != repeatId) {
                    throw CompileException("[.] reference outside its repeat: $path")
                }
                return ctx.values["$repeatId[${scope.second}].$suffix"] ?: FormValue.Null
            }
            val ordered = instances[repeatId].orEmpty()
            val index = indexText.toIntOrNull()
                ?: throw CompileException("malformed positional reference: $path")
            if (index < 0 || index >= ordered.size) {
                return FormValue.Null // out-of-range instance reads as null, not an error
            }
            return ctx.values["$repeatId[${ordered[index]}].$suffix"] ?: FormValue.Null
        }

        // bare reference: current instance first, then outward to the form root
        ctx.scope?.let { (repeatId, instanceId) ->
            ctx.values["$repeatId[$instanceId].$path"]?.let { return it }
        }

        return ctx.values[path] ?: throw CompileException("unresolvable reference: $path")
    }

    private fun evalOp(expr: Expr.Op, ctx: EvalContext): FormValue {
        // `if` is lazy in both branches (spec 4.3)
        if (expr.op == "if") {
            // The condition takes a boolean; anything else is null (§4.7), so
            // `if("yes", a, b)` is null rather than an exception mid-interview.
            val takeThen = (evaluate(expr.args[0], ctx) as? FormValue.Bool)?.value
                ?: return FormValue.Null
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

    /**
     * false dominates null; otherwise null propagates (spec 4.4.5, 4.7).
     *
     * A non-boolean operand is null, so it neither makes the result false nor
     * is quietly treated as true.
     */
    private fun and(args: List<FormValue>): FormValue {
        val values = args.map { it as? FormValue.Bool }
        if (values.any { it?.value == false }) return FormValue.Bool(false)
        if (values.any { it == null }) return FormValue.Null
        return FormValue.Bool(true)
    }

    /** true dominates null; otherwise null propagates (spec 4.4.6, 4.7). */
    private fun or(args: List<FormValue>): FormValue {
        val values = args.map { it as? FormValue.Bool }
        if (values.any { it?.value == true }) return FormValue.Bool(true)
        if (values.any { it == null }) return FormValue.Null
        return FormValue.Bool(false)
    }

    /** `not` takes a boolean; anything else is null (4.4.4, 4.7). */
    private fun not(a: FormValue): FormValue =
        (a as? FormValue.Bool)?.let { FormValue.Bool(!it.value) } ?: FormValue.Null

    private fun asDouble(v: FormValue): Double? = when (v) {
        is FormValue.Integer -> v.value.toDouble()
        is FormValue.Decimal -> v.value
        else -> null
    }

    /**
     * Arithmetic over two numbers, or null (spec 4.4.2, 4.7).
     *
     * A null operand yields null; so does one that is not a number. `"800" + 1`
     * is null, not "8001" and not an exception — `add` is arithmetic and `+`
     * never concatenates in this IR.
     */
    private fun arithmetic(op: String, a: FormValue, b: FormValue): FormValue {
        if (a.isNull || b.isNull) return FormValue.Null
        if (asDouble(a) == null || asDouble(b) == null) return FormValue.Null
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
        val x = asDouble(a) ?: return FormValue.Null
        val y = asDouble(b) ?: return FormValue.Null
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

    /**
     * Comparison (spec 4.4.3, 4.7).
     *
     * `eq`/`ne` are **total across types**: two non-null values of different
     * types are simply not equal. That is the one place "no implicit coercion"
     * (§4.5) produces an answer rather than an absence, and it has to —
     * `"800" == 800` is a question with a correct answer under a no-coercion
     * rule, and the answer is no.
     *
     * Ordering is different. There is no ordering *between* types to appeal to,
     * so `<` on a text and a number is null rather than an exception. Booleans
     * and structured values have no ordering at all.
     */
    private fun compare(op: String, a: FormValue, b: FormValue): FormValue {
        if (a.isNull || b.isNull) return FormValue.Null

        if (op == "eq" || op == "ne") {
            val same = equalValues(a, b)
            return FormValue.Bool(if (op == "eq") same else !same)
        }

        if (a is FormValue.Text && b is FormValue.Text) {
            return FormValue.Bool(
                when (op) {
                    "lt" -> a.value < b.value
                    "lte" -> a.value <= b.value
                    "gt" -> a.value > b.value
                    "gte" -> a.value >= b.value
                    else -> throw CompileException("unknown comparison: $op")
                }
            )
        }

        val x = asDouble(a) ?: return FormValue.Null
        val y = asDouble(b) ?: return FormValue.Null
        return FormValue.Bool(
            when (op) {
                "lt" -> x < y
                "lte" -> x <= y
                "gt" -> x > y
                "gte" -> x >= y
                else -> throw CompileException("unknown comparison: $op")
            }
        )
    }

    /**
     * `eq`'s rule, as a predicate (§4.7). Both sides are known non-null.
     *
     * A number equals a number by value, so `1` and `1.0` are the same answer
     * however each engine typed them. Everything else is equal only to its own
     * kind: a text is never equal to a number, which is what makes a dataset
     * filter over a text column need `str()` (§3.2).
     *
     * Structured values compare by content — `photo = other_photo` asks whether
     * two answers name the same file, which is a real question, and the Python
     * engine gets it from dict equality.
     */
    internal fun equalValues(a: FormValue, b: FormValue): Boolean {
        val x = asDouble(a)
        val y = asDouble(b)
        if (x != null && y != null) return x == y
        if (x != null || y != null) return false
        return a == b
    }

    private fun selected(haystack: FormValue, needle: FormValue): FormValue {
        if (haystack.isNull || needle.isNull) return FormValue.Null
        val items = when (haystack) {
            is FormValue.Sequence -> haystack.items
            else -> listOf(haystack)
        }
        // Membership by `eq`'s rule, not structural equality: `selected(["1"], 1)`
        // must be false on both engines rather than depending on how each
        // language happens to compare a string with a number.
        return FormValue.Bool(items.any { equalValues(it, needle) })
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
