package com.dcp.form

/**
 * Dataset-backed choice lists: decomposing a filter, and asking for rows.
 *
 * Form IR §3.2, and this MUST behave identically to the Python reference in
 * `backend/app/modules/form_engine/datasets.py` — `conformance/vectors/dataset-*`
 * compares the decomposition itself, not only its effect, because two engines
 * that both got the right list while one of them scanned 38,000 rows are not
 * interchangeable on a handset.
 *
 * **The engine never materialises a dataset.** `choices.filter` is decomposed
 * once, at compile time, into the part a store can answer from an index and the
 * part it cannot:
 *
 * ```
 * filter:   $row.district_id = ${district} and $row.population > 1000
 * selector: {district_id: <expr for ${district}>}   <- indexed lookup
 * residual: $row.population > 1000                  <- evaluated per row
 * ```
 *
 * Everything that decides *what the list is* stays in the engine, where a
 * vector can compare two implementations. A [DatasetSource] decides only how
 * quickly it finds rows — never which rows exist. §3.2 spells out why: which
 * rows are candidates is a which-artifact decision, and a vector fixes its
 * inputs, so it cannot see a caller choosing them.
 */

private const val ROW_PREFIX = "\$row."

/** The column name when [expr] is exactly `${'$'}row.something`, else null. */
private fun rowColumn(expr: Expr): String? {
    val ref = expr as? Expr.Ref ?: return null
    return if (ref.path.startsWith(ROW_PREFIX)) ref.path.removePrefix(ROW_PREFIX) else null
}

/**
 * Whether `${'$'}row` appears anywhere in this subtree.
 *
 * Over the whole subtree rather than at the top: `${'$'}row.a = 1 + ${'$'}row.b`
 * has no `${'$'}row` at either end of the `eq` and is still not a selector term.
 */
private fun mentionsRow(expr: Expr): Boolean = when (expr) {
    is Expr.Ref -> expr.path.startsWith(ROW_PREFIX)
    is Expr.Op -> expr.args.any { mentionsRow(it) }
    is Expr.Call -> expr.args.any { mentionsRow(it) }
    else -> false
}

/** Top-level `and` flattened, fully. Nothing else decomposes (§3.2). */
private fun conjuncts(expr: Expr): List<Expr> =
    if (expr is Expr.Op && expr.op == "and") expr.args.flatMap { conjuncts(it) } else listOf(expr)

/** `(column, expression)` when this conjunct is `${'$'}row.col = <no ${'$'}row>`. */
private fun selectorTerm(conjunct: Expr): Pair<String, Expr>? {
    val op = conjunct as? Expr.Op ?: return null
    if (op.op != "eq" || op.args.size != 2) return null
    for (index in 0..1) {
        val column = rowColumn(op.args[index])
        val other = op.args[1 - index]
        if (column != null && !mentionsRow(other)) return column to other
    }
    return null
}

/**
 * A dataset-backed `choices` block, compiled (§3.2).
 *
 * Computed once per field at compile time, because it is a pure function of the
 * IR: the same document must decompose the same way on every engine, and a
 * vector asserts that it did.
 */
data class ChoiceQuery(
    val dataset: String,
    val valueColumn: String,
    val labelColumns: Map<String, String>,
    /**
     * Column -> the expression whose value that column must equal. Ordered by
     * column name so two engines emit it identically.
     */
    val selector: Map<String, Expr>,
    /** What the selector could not absorb, as one expression, or null. */
    val residual: Expr?,
) {
    /**
     * True when nothing narrows and resolution is O(dataset).
     *
     * Named rather than inferred, because §3.2's contract is that an engine
     * *says* a filter is a full scan instead of quietly performing one.
     */
    val scans: Boolean get() = selector.isEmpty()
}

/** Decompose a `choices.kind = "dataset"` block, or null if it is inline. */
fun compileChoices(choices: Choices?): ChoiceQuery? {
    if (choices == null || choices.kind != "dataset") return null

    val selector = LinkedHashMap<String, Expr>()
    val residuals = mutableListOf<Expr>()
    for (conjunct in choices.filter?.let { conjuncts(it) } ?: emptyList()) {
        val term = selectorTerm(conjunct)
        // First binding wins; a column bound twice sends its later bindings to
        // the residual. Nothing is merged and nothing is called contradictory —
        // `$row.a = 1 and $row.a = 2` selects on 1 and finds nothing, which is
        // the right answer and not an error.
        if (term != null && term.first !in selector) {
            selector[term.first] = term.second
        } else {
            residuals.add(conjunct)
        }
    }

    val residual = when (residuals.size) {
        0 -> null
        1 -> residuals[0]
        else -> Expr.Op("and", residuals)
    }

    return ChoiceQuery(
        dataset = choices.dataset.orEmpty(),
        valueColumn = choices.valueColumn.orEmpty(),
        labelColumns = choices.labelColumn ?: emptyMap(),
        // Sorted, so the selector two engines produce is comparable as data
        // rather than only in its effect.
        selector = selector.toSortedMap(),
        residual = residual,
    )
}

/**
 * Where an engine gets dataset rows from.
 *
 * One method on purpose. [equals] is the additional equality a membership check
 * needs (§6.3), passed through rather than applied afterwards so that a store
 * can answer the whole question from one index: with no residual, "is this
 * answer in the list" is a single lookup whatever the dataset's size.
 *
 * An implementation may be as fast as it likes and must not be selective — it
 * answers exactly the rows matching what it was asked, in dataset order.
 */
interface DatasetSource {
    fun rows(
        dataset: String,
        selector: Map<String, FormValue>,
        equals: Pair<String, FormValue>? = null,
    ): List<Map<String, FormValue>>
}

/**
 * Every row in memory. The conformance harness, and small lists.
 *
 * Exact rather than fast, deliberately: this is the implementation the vectors
 * compare against, so it must be the plainest possible reading of §3.2. A
 * device-side source backed by SQLCipher answers the same questions from an
 * index and must agree with it row for row.
 */
class InMemoryDatasetSource(
    private val datasets: Map<String, List<Map<String, FormValue>>>,
) : DatasetSource {

    override fun rows(
        dataset: String,
        selector: Map<String, FormValue>,
        equals: Pair<String, FormValue>?,
    ): List<Map<String, FormValue>> {
        // An unknown key is an empty list, not a crash. A device that has not
        // yet synced a dataset holds no rows for it, and the question must
        // still answer — as a select with nothing to choose from, which is
        // visible, rather than as an exception in recalculation.
        val found = datasets[dataset] ?: return emptyList()
        var matched = found.filter { row -> selector.all { same(row[it.key], it.value) } }
        if (equals != null) {
            matched = matched.filter { same(it[equals.first], equals.second) }
        }
        return matched
    }

    companion object {
        /**
         * Exact match, the same rule as §6.3 — no trimming, no case folding.
         *
         * A number is also compared to its string form, because a CSV holds
         * text and an answer set by a `calculate` may be a number. A narrow
         * accommodation, not a coercion: `1` matches the cell `"1"` and nothing
         * else about §4.4 changes.
         */
        fun same(cell: FormValue?, value: FormValue): Boolean {
            val actual = cell ?: FormValue.Null
            if (actual == value) return true
            if (actual.isNull || value.isNull) return false
            val asText = (actual as? FormValue.Text)?.value
            val otherText = (value as? FormValue.Text)?.value
            if (asText != null && otherText == null) return asText == plain(value)
            if (otherText != null && asText == null) return otherText == plain(actual)
            return false
        }

        /** `1` not `1.0`, so an integer-valued number matches an integer cell. */
        private fun plain(value: FormValue): String? = when (value) {
            is FormValue.Integer -> value.value.toString()
            is FormValue.Decimal ->
                if (value.value % 1.0 == 0.0) value.value.toLong().toString()
                else value.value.toString()
            else -> null
        }
    }
}


/**
 * A dataset cell as the text a choice value or label is.
 *
 * A CSV holds text and this is almost always a no-op; a source that hands back
 * a typed cell still has to render one, and rendering it here rather than at
 * each call site is what keeps the two engines' output identical.
 */
internal fun formValueAsText(value: FormValue?): String = when (value) {
    null, is FormValue.Null -> ""
    is FormValue.Text -> value.value
    is FormValue.Integer -> value.value.toString()
    is FormValue.Decimal ->
        if (value.value % 1.0 == 0.0) value.value.toLong().toString() else value.value.toString()
    is FormValue.Bool -> if (value.value) "true" else "false"
    else -> value.toString()
}
