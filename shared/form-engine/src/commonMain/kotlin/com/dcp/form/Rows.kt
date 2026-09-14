package com.dcp.form

/**
 * Choice lists made of a repeat's instances: Form IR §3.3.
 *
 * The twin of `backend/app/modules/form_engine/rows.py`, and the two must agree
 * — `conformance/vectors/repeat-016` and `repeat-017` compare them.
 *
 * The identity half of the roster problem. A position is not stable, so
 * deleting a row renumbers every row below it and an answer that was correct
 * becomes wrong retroactively, naming a different person, with nothing in an
 * error state. An instance id does not renumber, which is why the value stored
 * here is an id (`docs/proposal-answer-indexed-rows.md` §3).
 *
 * ## Why this is not [ChoiceQuery] with a different source
 *
 * A dataset-backed list decomposes into a **selector** a store answers from an
 * index and a **residual** evaluated per candidate row (§3.2), because the
 * alternative is a scan over 37,852 villages on a handset. Neither half applies
 * here: the candidates are `instances[repeat]`, a list the engine is already
 * holding, and `${'$'}row.field` is an *answer* of a candidate instance, which
 * no source could look up. So the filter stays whole and is evaluated per
 * candidate, and this file is small on purpose.
 */

/**
 * A `choices.kind = "rows"` block, compiled (§3.3).
 *
 * Immutable and computed once per field, for the same reason [ChoiceQuery] is:
 * the same document must mean the same thing on every engine.
 */
data class RowsQuery(
    /** The repeat whose instances are the options. */
    val repeat: String,
    /**
     * Omit the instance the field is being answered in.
     *
     * A §10.2 semantic error on a field that is not inside [repeat] — there is
     * nothing to exclude there, and a flag that silently did nothing would be a
     * control that does nothing. `docs/decision-rows-self-exclusion.md` is why
     * it is a flag and not an identity comparison an author writes: the
     * expression form is one somebody eventually writes as
     * `${'$'}row.name != name`, which is wrong for two members who share a name
     * and produces a list with one wrong option in it that nothing renders
     * differently.
     */
    val excludeSelf: Boolean = false,
    /**
     * Evaluated per candidate instance, whole. `${'$'}row.field` is that
     * instance's value of that field; every other reference resolves from the
     * scope the field is being answered in, which is what lets a filter compare
     * the two.
     */
    val filter: Expr? = null,
)

/** Compile a `choices.kind = "rows"` block, or null if it is another kind. */
fun compileRowsChoices(choices: Choices?): RowsQuery? {
    if (choices == null || choices.kind != "rows") return null
    return RowsQuery(
        repeat = choices.repeat.orEmpty(),
        excludeSelf = choices.excludeSelf,
        filter = choices.filter,
    )
}
