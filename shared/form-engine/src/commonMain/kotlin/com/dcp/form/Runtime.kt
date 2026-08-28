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
    val path: String,
    val node: QuestionNode,
    val dataType: String,
    val dependsOn: Set<String>,
    /** ids of enclosing groups/repeats, for relevance inheritance */
    val ancestors: List<String>,
)

/** A validated form with its dependency graph resolved. */
class CompiledForm(val ir: FormIr) {
    val formId: String = ir.formId
    val version: Int = ir.version
    val fields = LinkedHashMap<String, CompiledField>()
    val containers = LinkedHashMap<String, ContainerNode>()
    val warnings = mutableListOf<String>()
    val order = mutableListOf<String>()
    val topoOrder: List<String>

    init {
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

            fields[node.id] = CompiledField(
                path = node.id,
                node = question,
                dataType = question.dataType,
                dependsOn = deps,
                ancestors = ancestors,
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
                    throw CompileException("unresolvable reference '$dep' in field '${f.path}'")
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
                warnings.add("${f.path}: missing translation for ${missing.sorted().joinToString(", ")}")
            }
            if (f.dataType == "decimal" && (f.node.constraint as? Expr.Op)?.op == "eq") {
                warnings.add("${f.path}: direct equality comparison on a decimal field")
            }
        }
    }
}

/** A live answer state for one compiled form. */
class FormInstance(
    val form: CompiledForm,
    private val today: String,
    private val now: String = "${today}T00:00:00",
    private val metadata: Map<String, FormValue> = emptyMap(),
) {
    val values: MutableMap<String, FormValue> =
        form.fields.keys.associateWithTo(LinkedHashMap()) { FormValue.Null }
    val states: Map<String, FieldState> =
        form.fields.entries.associate { (p, f) -> p to FieldState(p, f.dataType) }

    init {
        recalculate()
    }

    // -- answering ---------------------------------------------------------

    fun set(path: String, value: FormValue) {
        if (path !in form.fields) throw CompileException("unknown field: $path")
        values[path] = value
        recalculate()
    }

    fun setMany(answers: Map<String, FormValue>) {
        for ((path, value) in answers) {
            if (path !in form.fields) throw CompileException("unknown field: $path")
            values[path] = value
        }
        recalculate()
    }

    // -- evaluation --------------------------------------------------------

    /**
     * Full deterministic pass in topological order (spec 5.2), mirroring the
     * reference implementation's full pass exactly.
     */
    fun recalculate() {
        val ctx = EvalContext(values = values, today = today, now = now, metadata = metadata)

        for (path in form.topoOrder) {
            val cf = form.fields.getValue(path)
            val node = cf.node
            val state = states.getValue(path)
            val errors = mutableListOf<FieldError>()

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
                out.add(path.replace("[]", "").replace("[.]", ""))
            }
        }
        is Expr.Op -> expr.args.forEach { collectRefs(it, out) }
        is Expr.Call -> expr.args.forEach { collectRefs(it, out) }
    }
}
