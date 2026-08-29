package com.dcp.form

/**
 * Sensitivity propagation over the dependency graph (Form IR spec §10,
 * encryption envelope §5.2).
 *
 * The Python reference is `check_sensitivity_propagation` in
 * backend/app/modules/crypto/envelope.py. Both must produce the same
 * violations, in the same order, for the same IR: this decides whether a form
 * can be published, and a form the server refuses but a desktop builder accepts
 * is a bug that only shows up as a failed publish in the field.
 */

/**
 * The field id a reference reads.
 *
 * `members[0].name` reads `name`; the repeat is a scope, not a field (spec
 * §4.2). Reading the leading segment instead would resolve to `members`, which
 * is not a field at all, and would make the check silently blind to every
 * reference that crosses into a repeat.
 */
fun referencedField(dep: String): String =
    if (dep.contains("].")) dep.substringAfterLast("].") else dep

/**
 * Fields that must be treated as sensitive, and are not.
 *
 * A field reading a sensitive field leaks it: a `calculate` reproduces the
 * value outright, and a `relevant` or `constraint` discloses it a bit at a time
 * through which fields turn out to be relevant or valid. Inherited container
 * relevance counts — it is in [CompiledField.dependsOn] for the same reason.
 *
 * Returns violation messages in document order, empty when the form is safe to
 * publish. The fix is always to mark the reading field sensitive, never to
 * unmark the source.
 */
fun checkSensitivityPropagation(form: CompiledForm): List<String> {
    val violations = mutableListOf<String>()
    for (fieldId in form.order) {
        val field = form.fields.getValue(fieldId)
        if (field.node.sensitive) continue
        // By field, not by reference: `members[0].age` and `members[].age` read
        // the same field and are one violation, not two.
        for (base in field.dependsOn.map(::referencedField).distinct().sorted()) {
            if (form.fields[base]?.node?.sensitive == true) {
                violations.add(
                    "'$fieldId' is not sensitive but depends on sensitive field '$base'"
                )
            }
        }
    }
    return violations
}

/** Ids of every field marked `sensitive` — what field_level mode encrypts. */
fun CompiledForm.sensitiveFields(): Set<String> =
    fields.values.filter { it.node.sensitive }.map { it.fieldId }.toSet()
