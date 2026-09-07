package com.dcp.form

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

/**
 * An expression annotated with what each of its nodes evaluated to, against
 * the current answers — the answer to "why is this hidden?" that Form IR §4.4
 * makes hard to read off a screen: a `relevant` that is null hides a question
 * exactly as a false one does, and the null arrived from a reference three
 * screens back.
 *
 * **The trace reports evaluation; it does not define it** (builder scope §4).
 * Every `result` here is [Evaluator.evaluate] called on that node with the same
 * context the field is evaluated under. Nothing is computed differently, nothing
 * is short-circuited differently, and no rule lives here: both engines already
 * agree on every value this shows (`conformance/vectors`, the function matrix),
 * so a trace adds no semantics and needs no vectors of its own. If a second
 * engine ever emits one, this shape must stay a view of an answer and never
 * become a second place evaluation is written down.
 */
data class TraceNode(
    val op: String,
    val fn: String? = null,
    val path: String? = null,
    val literal: FormValue? = null,
    val args: List<TraceNode> = emptyList(),
    val result: FormValue,
)

fun traceExpression(expr: Expr, ctx: EvalContext): TraceNode {
    val result = Evaluator.evaluate(expr, ctx)
    return when (expr) {
        is Expr.Lit -> TraceNode(op = "lit", literal = expr.value, result = result)
        is Expr.Ref -> TraceNode(op = "ref", path = expr.path, result = result)
        is Expr.Op -> TraceNode(
            op = expr.op,
            args = expr.args.map { traceExpression(it, ctx) },
            result = result,
        )
        is Expr.Call -> TraceNode(
            op = "call",
            fn = expr.fn,
            args = expr.args.map { traceExpression(it, ctx) },
            result = result,
        )
    }
}

/** The shape `web/src/builder/engine/facade.ts` reads as `TraceNode`. */
fun TraceNode.toJson(): JsonElement = buildJsonObject {
    put("op", JsonPrimitive(op))
    fn?.let { put("fn", JsonPrimitive(it)) }
    path?.let { put("path", JsonPrimitive(it)) }
    literal?.let { put("literal", formValueToJson(it)) }
    put("args", JsonArray(args.map { it.toJson() }))
    put("result", formValueToJson(result))
}
