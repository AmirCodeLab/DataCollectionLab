package com.dcp.form

/**
 * Which questions a form can never ask, decided from the document alone
 * (Form IR §10.2, §10.3).
 *
 * The Python reference is `backend/app/modules/form_engine/reachability.py`.
 * Both must produce the same violations, the same warnings and the same
 * "never shown" list, in the same order, for the same IR: this decides whether
 * a form publishes, and a form the server refuses but a builder accepts is a
 * bug that only shows up as a failed publish in the field.
 * `conformance/reachability` pins the text.
 *
 * Two findings:
 * - reachability — an answerable question on no screen of §11.1's partition
 *   (defect 14's shape);
 * - liveness — a container that provably never appears: a statically-false
 *   `relevant`, or a repeat that can never hold an instance (§10.3's three
 *   shapes). The engine is right to skip it at runtime; that is why the
 *   document must not ship.
 *
 * Everything here is static. An expression that reads an answer is not
 * decided however plainly it fails (§10.3).
 */

private fun hasRef(expr: Expr): Boolean = when (expr) {
    is Expr.Ref -> true
    is Expr.Lit -> false
    is Expr.Op -> expr.args.any(::hasRef)
    is Expr.Call -> expr.args.any(::hasRef)
}

private fun callsClock(expr: Expr): Boolean = when (expr) {
    is Expr.Call -> expr.fn == "today" || expr.fn == "now" || expr.args.any(::callsClock)
    is Expr.Op -> expr.args.any(::callsClock)
    else -> false
}

/** §10.3: decidable without answers and without a clock. */
fun isStatic(expr: Expr?): Boolean = expr != null && !hasRef(expr) && !callsClock(expr)

/** The value of a static expression by §4.7 over an empty context. */
fun staticValue(expr: Expr): FormValue =
    Evaluator.evaluate(expr, EvalContext(values = emptyMap(), today = "2000-01-01", now = "2000-01-01T00:00:00Z"))

/**
 * §10.3's "statically false": static, and evaluating to exactly `false`.
 * Null is not false — §4.4 coerces it to true at the relevance boundary —
 * and neither is `0` under §4.7's no-coercion rule.
 */
fun staticallyFalse(expr: Expr?): Boolean =
    isStatic(expr) && staticValue(expr!!) == FormValue.Bool(false)

private fun answerable(nodes: List<FormNode>): List<String> {
    val out = mutableListOf<String>()
    for (node in nodes) {
        if (node is QuestionNode && node.calculate == null) out.add(node.id)
        if (node is ContainerNode) out.addAll(answerable(node.children))
    }
    return out
}

/** Why this container can never show a screen, or null (§10.3). */
fun deadReason(node: FormNode): String? {
    if (node !is ContainerNode) return null
    if (staticallyFalse(node.relevant)) return "is never shown: its relevant is statically false"
    if (node !is RepeatNode) return null
    val count = node.countExpr
    if (count != null && isStatic(count)) {
        val value = staticValue(count)
        val number = when (value) {
            is FormValue.Integer -> value.value.toDouble()
            is FormValue.Decimal -> value.value
            else -> null
        }
        if (number != null && number <= 0.0) {
            // Spelled as the Python reference spells the value: an integer
            // without a fraction, a decimal with one.
            val spelled = if (value is FormValue.Integer) value.value.toString() else formatDecimal(number)
            return "never holds an instance: its countExpr is statically $spelled"
        }
    }
    if (node.maxInstances == 0) return "never holds an instance: maxInstances is 0"
    val source = node.rowSource
    if (source != null && source.kind == "inline" && source.items.isEmpty() && !source.allowAdd) {
        return "never holds an instance: its fixed list is empty and rows cannot be added"
    }
    return null
}

private fun formatDecimal(value: Double): String =
    if (value == value.toLong().toDouble()) "${value.toLong()}.0" else value.toString()

data class DeadContainer(val id: String, val reason: String, val questions: List<String>)

/** Unreachable containers holding answerable questions, outermost only. */
fun deadContainers(ir: FormIr): List<DeadContainer> {
    val found = mutableListOf<DeadContainer>()
    fun walk(nodes: List<FormNode>) {
        for (node in nodes) {
            val reason = deadReason(node)
            if (reason != null) {
                val questions = answerable((node as ContainerNode).children)
                if (questions.isNotEmpty()) found.add(DeadContainer(node.id, reason, questions))
                continue // reported once, by the outermost
            }
            if (node is ContainerNode) walk(node.children)
        }
    }
    walk(ir.children)
    return found
}

private fun named(ids: List<String>): String {
    var shown = ids.take(5).joinToString(", ") { "'$it'" }
    if (ids.size > 5) shown += " and ${ids.size - 5} more"
    return shown
}

/** Violations that block publish, in document order. Empty when none. */
fun checkReachability(ir: FormIr): List<String> {
    val violations = mutableListOf<String>()

    val onScreen = buildScreenPlan(ir).askableQuestionIds()
    val unreachable = answerable(ir.children).filter { it !in onScreen }
    if (unreachable.isNotEmpty()) {
        violations.add(
            "${unreachable.size} question(s) in this form cannot be asked by any client, " +
                "so they would be silently skipped in the field: ${named(unreachable)}. " +
                "Nothing in the screen plan reaches them (Form IR §11.1)."
        )
    }

    for (dead in deadContainers(ir)) {
        violations.add(
            "'${dead.id}' ${dead.reason}, so ${dead.questions.size} question(s) inside it " +
                "would never be asked: ${named(dead.questions)} (Form IR §10.3)."
        )
    }
    return violations
}

/**
 * Every answerable question the document itself says is never shown: inside
 * an unreachable container, or carrying a statically-false `relevant` of its
 * own. Document order. The field a builder's "never shown" badge reads.
 */
fun neverShownQuestions(ir: FormIr): List<String> {
    val out = mutableListOf<String>()
    fun walk(nodes: List<FormNode>) {
        for (node in nodes) {
            if (deadReason(node) != null) {
                out.addAll(answerable((node as ContainerNode).children))
                continue
            }
            if (node is QuestionNode && node.calculate == null && staticallyFalse(node.relevant)) {
                out.add(node.id)
            }
            if (node is ContainerNode) walk(node.children)
        }
    }
    walk(ir.children)
    return out
}
