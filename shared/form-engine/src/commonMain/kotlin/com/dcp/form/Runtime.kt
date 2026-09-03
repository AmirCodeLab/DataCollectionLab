package com.dcp.form

/**
 * Form runtime: dependency graph construction and deterministic recalculation.
 *
 * This MUST produce results identical to the Python reference implementation in
 * backend/app/modules/form_engine/runtime.py for every conformance vector.
 * Spec: specs/form-ir-v0.1.md section 5.
 */

private val ID_PATTERN = Regex("^[a-z][a-z0-9_]*$")

data class FieldError(
    val kind: String,
    val message: Map<String, String>? = null,
    val severity: String = "error",
)

class FieldState(
    val path: String,
    val dataType: String,
) {
    var relevant: Boolean = true
    var required: Boolean = false
    var readOnly: Boolean = false
    var value: FormValue = FormValue.Null
    var valid: Boolean = true
    var errors: List<FieldError> = emptyList()
}

class CompiledField(
    val fieldId: String,
    val node: QuestionNode,
    val dataType: String,
    val dependsOn: Set<String>,
    /** ids of enclosing groups/repeats, for relevance inheritance */
    val ancestors: List<String>,
    /** innermost enclosing repeat id, if any */
    val repeat: String?,
    /**
     * A dataset-backed `choices` block, decomposed (§3.2). Null for an inline
     * list or no list at all. Computed at compile time because it is a pure
     * function of the IR: the same document must decompose the same way on
     * every engine, and a vector asserts that it did.
     */
    val choiceQuery: ChoiceQuery? = null,
)

/** A validated form with its dependency graph resolved. */
class CompiledForm(val ir: FormIr) {
    val formId: String = ir.formId
    val version: Int = ir.version
    val fields = LinkedHashMap<String, CompiledField>()
    val containers = LinkedHashMap<String, ContainerNode>()
    val repeats = LinkedHashMap<String, RepeatNode>()
    val warnings = mutableListOf<String>()
    val order = mutableListOf<String>()
    val topoOrder: List<String>

    /** Static screen partition (spec 11.1). */
    val screens: List<FormScreen> by lazy { buildScreenPlan(ir) }

    init {
        // Spec §10.1, before anything semantic — and here rather than in
        // FormIr.parse so it fires however the document arrived, including a
        // FormIr built in code. This is the Python engine's placement too
        // (CompiledForm.__init__ calls check_document); the rest of §10.1 is
        // the deserialiser's job on this side, which is why only this one
        // check is spelled out.
        checkIrVersion(ir.irVersion)

        compile()
        checkReferences()
        topoOrder = topologicalOrder()
        lint()
    }

    // -- compilation -------------------------------------------------------

    private fun walk(
        nodes: List<FormNode>,
        ancestors: List<String>,
        visit: (FormNode, List<String>) -> Unit,
    ) {
        for (node in nodes) {
            visit(node, ancestors)
            if (node is ContainerNode) walk(node.children, ancestors + node.id, visit)
        }
    }

    private fun compile() {
        val seen = mutableSetOf<String>()

        walk(ir.children, emptyList()) { node, ancestors ->
            if (!ID_PATTERN.matches(node.id)) {
                throw CompileException("invalid id format: '${node.id}'")
            }
            if (!seen.add(node.id)) {
                throw CompileException("duplicate id: ${node.id}")
            }

            val enclosingRepeats = ancestors.filter { it in repeats }
            if (enclosingRepeats.size > 1) {
                throw CompileException(
                    "nested repeats are not supported in IR v0.1 (field '${node.id}')"
                )
            }

            if (node is RepeatNode) {
                if (enclosingRepeats.isNotEmpty()) {
                    throw CompileException(
                        "nested repeats are not supported in IR v0.1 (repeat '${node.id}')"
                    )
                }
                repeats[node.id] = node
                containers[node.id] = node
                return@walk
            }

            if (node is ContainerNode) {
                containers[node.id] = node
                return@walk
            }

            val question = node as QuestionNode
            val deps = mutableSetOf<String>()
            for (expr in listOf(
                question.relevant, question.constraint, question.calculate,
                question.required, question.readOnly, question.default,
            )) {
                if (expr != null) collectRefs(expr, deps)
            }

            // a field inherits relevance from every enclosing container
            for (anc in ancestors) {
                containers[anc]?.relevant?.let { collectRefs(it, deps) }
            }

            val query = compileChoices(question.choices)
            if (query != null) {
                // A selector expression reads answers, so the field depends on
                // them: changing the district must re-resolve the village list
                // and re-check the village already chosen. `collectRefs`
                // deliberately ignores `$row.` — those are columns, not fields —
                // and the selector's right-hand sides are exactly the part that
                // is not `$row`, which is why they are collected from here
                // rather than from the filter as a whole.
                query.selector.values.forEach { collectRefs(it, deps) }
                query.residual?.let { collectRefs(it, deps) }
            }

            fields[node.id] = CompiledField(
                fieldId = node.id,
                node = question,
                dataType = question.dataType,
                dependsOn = deps,
                ancestors = ancestors,
                repeat = enclosingRepeats.firstOrNull(),
                choiceQuery = query,
            )
            order.add(node.id)
        }
    }

    private fun checkReferences() {
        val known = fields.keys + containers.keys
        for (f in fields.values) {
            for (dep in f.dependsOn) {
                val base = dep.substringBefore("[").substringBefore(".")
                if (base !in known) {
                    throw CompileException("unresolvable reference '$dep' in field '${f.fieldId}'")
                }
            }
        }
    }

    /** Kahn's algorithm, tie-broken by document order for determinism. */
    private fun topologicalOrder(): List<String> {
        val indegree = fields.keys.associateWithTo(mutableMapOf()) { 0 }
        val dependents = fields.keys.associateWithTo(mutableMapOf()) { mutableListOf<String>() }

        for ((path, f) in fields) {
            for (dep in f.dependsOn) {
                val base = dep.substringBefore("[").substringBefore(".")
                if (base in fields && base != path) {
                    dependents.getValue(base).add(path)
                    indegree[path] = indegree.getValue(path) + 1
                }
            }
        }

        val documentIndex = order.withIndex().associate { (i, p) -> p to i }
        val ready = order.filter { indegree.getValue(it) == 0 }.toMutableList()
        val result = mutableListOf<String>()
        while (ready.isNotEmpty()) {
            ready.sortBy { documentIndex.getValue(it) }
            val current = ready.removeAt(0)
            result.add(current)
            for (dep in dependents.getValue(current)) {
                indegree[dep] = indegree.getValue(dep) - 1
                if (indegree.getValue(dep) == 0) ready.add(dep)
            }
        }

        if (result.size != fields.size) {
            val cyclic = (fields.keys - result.toSet()).sorted()
            throw CompileException("dependency cycle involving: ${cyclic.joinToString(", ")}")
        }
        return result
    }

    private fun lint() {
        val languages = ir.languages.toSet()
        for (f in fields.values) {
            val label = f.node.label ?: emptyMap()
            val missing = languages - label.keys
            if (missing.isNotEmpty()) {
                warnings.add("${f.fieldId}: missing translation for ${missing.sorted().joinToString(", ")}")
            }
            if (f.dataType == "decimal" && (f.node.constraint as? Expr.Op)?.op == "eq") {
                warnings.add("${f.fieldId}: direct equality comparison on a decimal field")
            }
        }
    }
}

/**
 * A live answer state for one compiled form.
 *
 * Canonical value paths:
 *   top-level field   `age`
 *   repeat field      `members[i3].age`   (`i3` is a stable instance id)
 *
 * Instance ids are stable: deleting an instance never renumbers the others in
 * storage (spec 5.4). Positional addressing (`members[0].age`) resolves against
 * the current ordered list at evaluation time.
 */
/**
 * Values not present in the question's choice list (spec 6.3).
 *
 * Empty when the question has no choices, when the list is dataset-backed (not
 * resolvable here yet), or when everything matches.
 *
 * Matching is **exact** — no trimming, no case folding, no normalisation. That
 * is §6.3's decision rather than an accident of `==`: a device that accepted
 * "Male" for "male" would store "Male", and every later comparison — a
 * `selected()` call, a choice filter, an export column — would have to make the
 * same allowance or disagree with it.
 */
internal fun inlineValuesOutsideChoices(node: QuestionNode, value: FormValue): List<String> {
    val choices = node.choices ?: return emptyList()
    if (choices.kind != "inline") return emptyList()
    val permitted = choices.items.map { it.value }.toSet()

    return when (value) {
        // An empty sequence is an unanswered question, not a list in which
        // nothing matched. Iterating it and concluding failure is the mistake
        // §6.3 names.
        is FormValue.Sequence ->
            value.items.mapNotNull { (it as? FormValue.Text)?.value }
                .filter { it !in permitted }
        is FormValue.Text -> if (value.value in permitted) emptyList() else listOf(value.value)
        else -> emptyList()
    }
}


class FormInstance(
    val form: CompiledForm,
    private val today: String,
    private val now: String = "${today}T00:00:00",
    private val metadata: Map<String, FormValue> = emptyMap(),
    /**
     * Where dataset-backed lists come from (§3.2). A form with none never
     * touches it; one that has them and is given no source resolves every list
     * to empty, which shows up as a select with nothing to choose from rather
     * than as an exception during recalculation. That is the honest state for a
     * device that has not yet synced its reference data.
     */
    val datasets: DatasetSource = InMemoryDatasetSource(emptyMap()),
) {
    /** repeat id -> ordered stable instance ids */
    val instances: Map<String, MutableList<String>> =
        form.repeats.keys.associateWithTo(LinkedHashMap()) { mutableListOf() }
    private var instanceCounter = 0

    val values: MutableMap<String, FormValue> = LinkedHashMap()
    private val mutableStates = LinkedHashMap<String, FieldState>()
    val states: Map<String, FieldState> get() = mutableStates

    init {
        for ((fid, f) in form.fields) {
            if (f.repeat == null) {
                values[fid] = FormValue.Null
                mutableStates[fid] = FieldState(fid, f.dataType)
            }
        }
        for ((rid, node) in form.repeats) {
            repeat(node.minInstances ?: 0) { createInstance(rid) }
        }
        recalculate()
    }

    // -- repeat instances --------------------------------------------------

    private fun fieldsOf(repeatId: String): List<String> =
        form.fields.entries.filter { it.value.repeat == repeatId }.map { it.key }

    private fun createInstance(repeatId: String): String {
        val instanceId = "i${++instanceCounter}"
        instances.getValue(repeatId).add(instanceId)
        for (fid in fieldsOf(repeatId)) {
            val path = "$repeatId[$instanceId].$fid"
            values[path] = FormValue.Null
            mutableStates[path] = FieldState(path, form.fields.getValue(fid).dataType)
        }
        return instanceId
    }

    private fun destroyInstance(repeatId: String, instanceId: String) {
        for (fid in fieldsOf(repeatId)) {
            val path = "$repeatId[$instanceId].$fid"
            values.remove(path)
            mutableStates.remove(path)
        }
    }

    fun addInstance(repeatId: String): String {
        val node = form.repeats[repeatId] ?: throw CompileException("unknown repeat: $repeatId")
        if (node.countExpr != null) {
            throw CompileException(
                "repeat $repeatId is controlled by countExpr; instances cannot be added"
            )
        }
        val maximum = node.maxInstances
        if (maximum != null && instances.getValue(repeatId).size >= maximum) {
            throw CompileException("repeat $repeatId is at its maximum of $maximum")
        }
        val instanceId = createInstance(repeatId)
        recalculate()
        return instanceId
    }

    /** Deletes by position. Remaining instances keep their stable ids. */
    fun deleteInstance(repeatId: String, index: Int) {
        val ordered = instances[repeatId] ?: throw CompileException("unknown repeat: $repeatId")
        if (index < 0 || index >= ordered.size) {
            throw CompileException("no instance at $repeatId[$index]")
        }
        val instanceId = ordered.removeAt(index)
        destroyInstance(repeatId, instanceId)
        recalculate()
    }

    fun instanceCount(repeatId: String): Int = instances[repeatId]?.size ?: 0

    // -- answering ---------------------------------------------------------

    /** Translates positional addressing into a stable-id path. */
    fun canonical(path: String): String {
        if ("[" in path && "]." in path) {
            val repeatId = path.substringBefore("[")
            val rest = path.substringAfter("[")
            val indexText = rest.substringBefore("].")
            val suffix = rest.substringAfter("].")
            val ordered = instances[repeatId] ?: throw CompileException("unknown repeat: $repeatId")
            if (indexText.isNotEmpty() && indexText.all { it.isDigit() }) {
                val index = indexText.toInt()
                if (index >= ordered.size) {
                    throw CompileException("no instance at $repeatId[$index]")
                }
                return "$repeatId[${ordered[index]}].$suffix"
            }
            return path // already a stable id
        }
        return path
    }

    fun set(path: String, value: FormValue) = setMany(mapOf(path to value))

    fun setMany(answers: Map<String, FormValue>) {
        for ((path, value) in answers) {
            val canonicalPath = canonical(path)
            if (canonicalPath !in values) throw CompileException("unknown field: $path")
            values[canonicalPath] = value
        }
        recalculate()
    }

    // -- evaluation --------------------------------------------------------

    private fun context(scope: Pair<String, String>? = null): EvalContext = EvalContext(
        values = values,
        today = today,
        now = now,
        metadata = metadata,
        scope = scope,
        instances = instances,
        // `pulldata` reads through the same source the choice filters do, so a
        // client's form-version binding covers both (§3.2).
        datasets = datasets,
    )

    // -- dataset-backed choice lists (§3.2) --------------------------------

    /**
     * The selector, evaluated against the current answers.
     *
     * A term evaluating to null selects on null and matches no row unless the
     * column holds one. It is deliberately not dropped: an unanswered district
     * must narrow the village list to nothing, not widen it to everything
     * (§3.2, §4.4).
     */
    private fun selectorValues(query: ChoiceQuery, ctx: EvalContext): Map<String, FormValue> =
        query.selector.mapValues { Evaluator.evaluate(it.value, ctx) }

    /**
     * This field's selector, evaluated against the current answers (§3.2).
     *
     * Public because a vector compares the decomposition itself and not only
     * its effect: two engines that resolve the same list while one of them
     * narrowed and the other scanned are not interchangeable on a handset.
     */
    fun selectorFor(fieldId: String): Map<String, FormValue> {
        val query = form.fields.getValue(fieldId).choiceQuery ?: return emptyMap()
        return selectorValues(query, context(scopeOf(fieldId)))
    }

    /**
     * Rows the source returns for this field's selector, before the residual.
     *
     * Public because it is what the performance contract is measured in: it is
     * O(rows matching the selector) and never O(dataset), and a vector asserts
     * its size so that "did the engine narrow" is comparable between
     * implementations rather than only visible in a profiler.
     */
    fun candidateRows(
        fieldId: String,
        equals: FormValue? = null,
        scope: Pair<String, String>? = scopeOf(fieldId),
    ): List<Map<String, FormValue>> {
        val query = form.fields.getValue(fieldId).choiceQuery ?: return emptyList()
        val ctx = context(scope)
        return datasets.rows(
            query.dataset,
            selectorValues(query, ctx),
            equals?.let { query.valueColumn to it },
        )
    }

    private fun rowsAfterResidual(
        fieldId: String,
        rows: List<Map<String, FormValue>>,
        scope: Pair<String, String>?,
    ): List<Map<String, FormValue>> {
        val query = form.fields.getValue(fieldId).choiceQuery ?: return rows
        val residual = query.residual ?: return rows
        val base = context(scope)
        // `nullIs = false` because a filter that cannot be decided must not
        // offer the row — §4.4's boundary rule for `constraint` coerces the
        // other way, and this is not a constraint: an undecidable row is not a
        // permitted answer.
        return rows.filter {
            Evaluator.coerceBoolean(
                Evaluator.evaluate(residual, base.copy(row = it)),
                nullIs = false,
            )
        }
    }

    /**
     * The resolved option list for a field, in dataset order (§3.2).
     *
     * Inline lists are returned as they stand; a dataset-backed list is the
     * selector's rows with the residual applied. A client renders both kinds
     * the same way and so cannot end up implementing one of them itself.
     */
    fun choices(fieldId: String): List<ChoiceItem> {
        val cf = form.fields.getValue(fieldId)
        val query = cf.choiceQuery ?: return cf.node.choices?.items ?: emptyList()
        val scope = scopeOf(fieldId)
        return rowsAfterResidual(fieldId, candidateRows(fieldId, scope = scope), scope).map { row ->
            ChoiceItem(
                value = (row[query.valueColumn] as? FormValue.Text)?.value
                    ?: formValueAsText(row[query.valueColumn]),
                label = query.labelColumns.mapValues { (_, column) ->
                    formValueAsText(row[column])
                },
            )
        }
    }

    /**
     * Values not present in this question's choice list (spec 6.3).
     *
     * For a dataset-backed list this is a **lookup, not a scan** (§3.2): the
     * answer is pushed into the source alongside the selector, so with no
     * residual it is one indexed question whatever the dataset's size. It is
     * never "fetch the list, then search it" — that is the difference between a
     * village select that works on a handset and one that does not.
     */
    private fun valuesOutsideChoices(
        cf: CompiledField,
        value: FormValue,
        scope: Pair<String, String>?,
    ): List<String> {
        cf.choiceQuery ?: return inlineValuesOutsideChoices(cf.node, value)

        val wanted =
            if (cf.dataType == "select_multiple" && value is FormValue.Sequence) value.items
            else listOf(value)
        return wanted.filter { one ->
            rowsAfterResidual(cf.fieldId, candidateRows(cf.fieldId, one, scope), scope).isEmpty()
        }.map { formValueAsText(it) }
    }

    /** The repeat instance a field id belongs to, for building a context. */
    private fun scopeOf(fieldId: String): Pair<String, String>? {
        val repeat = form.fields.getValue(fieldId).repeat ?: return null
        // Resolution inside a repeat is the instance currently being evaluated;
        // `choices()` called from outside one uses the first instance. Repeats
        // with dataset-backed lists are not exercised until v0.2's repeat
        // screen flow, so this is deliberately the simple reading.
        return instances[repeat]?.firstOrNull()?.let { repeat to it }
    }

    private fun evaluateField(fid: String, path: String, scope: Pair<String, String>?) {
        val cf = form.fields.getValue(fid)
        val node = cf.node
        val state = mutableStates.getValue(path)
        val errors = mutableListOf<FieldError>()
        val ctx = context(scope)

        // 1. relevance, including inheritance from enclosing containers
        var relevant = true
        for (anc in cf.ancestors) {
            val ancRelevant = form.containers[anc]?.relevant ?: continue
            if (!Evaluator.coerceBoolean(Evaluator.evaluate(ancRelevant, ctx), nullIs = true)) {
                relevant = false
                break
            }
        }
        if (relevant && node.relevant != null) {
            relevant = Evaluator.coerceBoolean(Evaluator.evaluate(node.relevant, ctx), nullIs = true)
        }
        state.relevant = relevant

        // 2. calculate
        if (node.calculate != null && relevant) {
            values[path] = Evaluator.evaluate(node.calculate, ctx)
        }

        state.value = values.getValue(path)

        // 3. required
        state.required = node.required?.let {
            Evaluator.coerceBoolean(Evaluator.evaluate(it, ctx), nullIs = false)
        } ?: false

        // 4. readOnly
        state.readOnly = node.readOnly?.let {
            Evaluator.coerceBoolean(Evaluator.evaluate(it, ctx), nullIs = false)
        } ?: false

        // 5. constraint — only meaningful for relevant, answered fields
        state.valid = true
        if (relevant) {
            if (state.required && state.value.isNull) {
                state.valid = false
                errors.add(FieldError(kind = "required"))
            }
            // Choice membership (spec 6.3), before the constraint.
            //
            // Neither engine read `choices` at all before this: a select_one
            // could hold "purple" and both engines called the form valid and
            // finalisable. Thirty-nine vectors never saw it, because not one
            // of them ever set a value outside its list.
            //
            // `null` is deliberately excluded — an unanswered question is not
            // a membership failure, it is `required`'s business (§4.4, §6.3).
            if (!state.value.isNull &&
                valuesOutsideChoices(cf, state.value, scope).isNotEmpty()
            ) {
                state.valid = false
                // One error on the field, not one per offending value: the
                // field is what is invalid, and two engines that disagreed
                // about the count would both look correct.
                errors.add(FieldError(kind = "choice"))
            }
            if (!state.value.isNull && node.constraint != null) {
                val ok = Evaluator.coerceBoolean(Evaluator.evaluate(node.constraint, ctx), nullIs = true)
                if (!ok) {
                    state.valid = false
                    errors.add(
                        FieldError(
                            kind = "constraint",
                            message = node.constraintMessage,
                            severity = node.severity ?: "error",
                        )
                    )
                }
            }
        }
        state.errors = errors
    }

    /**
     * Full deterministic pass in topological order (spec 5.2), mirroring the
     * reference implementation's full pass exactly. A repeat field is evaluated
     * once per instance, in instance order, before the pass moves to the next
     * field, so a field outside a repeat that aggregates over one always sees
     * fully-evaluated instances (spec 5.4).
     */
    fun recalculate() {
        // countExpr governs instance count before anything inside is evaluated
        for ((rid, node) in form.repeats) {
            val countExpr = node.countExpr ?: continue
            val counted = Evaluator.evaluate(countExpr, context())
            val wanted = maxOf(
                0,
                when (counted) {
                    is FormValue.Null -> 0
                    is FormValue.Integer -> counted.value.toInt()
                    is FormValue.Decimal -> counted.value.toInt()
                    else -> throw EvaluationException("countExpr must be numeric, got $counted")
                },
            )
            val ordered = instances.getValue(rid)
            while (ordered.size < wanted) createInstance(rid)
            while (ordered.size > wanted) {
                destroyInstance(rid, ordered.removeAt(ordered.size - 1))
            }
        }

        for (fid in form.topoOrder) {
            val cf = form.fields.getValue(fid)
            if (cf.repeat == null) {
                evaluateField(fid, fid, null)
            } else {
                for (instanceId in instances.getValue(cf.repeat).toList()) {
                    evaluateField(fid, "${cf.repeat}[$instanceId].$fid", cf.repeat to instanceId)
                }
            }
        }
    }

    // -- output ------------------------------------------------------------

    val isValid: Boolean
        get() = states.values.filter { it.relevant }.all { it.valid }

    /**
     * Relevant answers only by default — non-relevant values are retained in
     * storage but excluded from export (spec 5.3).
     */
    fun answers(includeIrrelevant: Boolean = false): Map<String, FormValue> =
        states.entries
            .filter { includeIrrelevant || it.value.relevant }
            .associate { (p, s) -> p to s.value }

    fun snapshot(): Map<String, FieldState> = states
}

/**
 * Collects every field path an expression depends on. Used to build the
 * dependency graph (spec 5.1).
 */
fun collectRefs(expr: Expr, out: MutableSet<String>) {
    when (expr) {
        is Expr.Lit -> Unit
        is Expr.Ref -> {
            val path = expr.path
            if (!path.startsWith("\$row.") && !path.startsWith("_metadata.")) {
                // members[].age / members[0].age / members[.].age all depend on `age`
                if ("]." in path) out.add(path.substringAfter("]."))
                else out.add(path)
            }
        }
        is Expr.Op -> expr.args.forEach { collectRefs(it, out) }
        is Expr.Call -> expr.args.forEach { collectRefs(it, out) }
    }
}
