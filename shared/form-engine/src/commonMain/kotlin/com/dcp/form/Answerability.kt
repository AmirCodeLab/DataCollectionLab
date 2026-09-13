package com.dcp.form

/**
 * Questions a form shows and nobody can answer, decided from the document alone
 * (Form IR §10.2).
 *
 * The Python reference is `backend/app/modules/form_engine/answerability.py`.
 * Both must produce the same violations, in the same order, for the same IR:
 * this decides whether a form publishes, and a form the server refuses but a
 * builder accepts is a bug that only shows up as a failed publish in the field.
 * `conformance/answerability` pins the text.
 *
 * The sibling of [checkReachability], and the distinction is worth holding:
 * reachability asks whether a question reaches a **screen**, this asks whether
 * a question that reached one can be **answered**. A form can pass the first
 * and fail the second, which is exactly what happened.
 *
 * One finding today: a `note` carrying `required`. §2.1 gives a note no value
 * and nothing can give it one, so `required` on one is permanently blocking
 * under §6.2 — the submission can never be finalised, and `firstBlockingScreen`
 * sends the enumerator to a screen holding a sentence and nothing to answer.
 *
 * `required` **present at all** is the refusal, not `required` evaluating true:
 * a statically-false one is merely pointless, and distinguishing the two would
 * leave an author one edit away from a form that cannot be finished. A
 * `constraint` or `readOnly` on a note is equally meaningless and deliberately
 * not refused — both are inert over null (§4.4.7).
 */

/**
 * Every §2.1 dataType that holds no value. `note` is the whole list, and the
 * set exists rather than a literal so that a second valueless type arrives here
 * rather than in a second copy of this rule somewhere else.
 */
val VALUELESS_TYPES: Set<String> = setOf("note")

private fun questions(nodes: List<FormNode>): List<QuestionNode> {
    val found = mutableListOf<QuestionNode>()
    for (node in nodes) {
        when (node) {
            is QuestionNode -> found.add(node)
            is ContainerNode -> found.addAll(questions(node.children))
        }
    }
    return found
}

/** The one sentence both engines and the importer say. */
fun requiredValuelessMessage(nodeId: String, dataType: String): String =
    "'$nodeId' is a `$dataType`, which holds no value (Form IR §2.1), and it is marked " +
        "`required`. Nothing can ever answer it, so this submission could never be " +
        "finalised and the enumerator would be sent to a screen with nothing on it " +
        "(Form IR §10.2, §6.2)."

/** Violations that block publish, in document order. Empty when none. */
fun checkAnswerability(ir: FormIr): List<String> =
    questions(ir.children)
        .filter { it.dataType in VALUELESS_TYPES && it.required != null }
        .map { requiredValuelessMessage(it.id, it.dataType) }
