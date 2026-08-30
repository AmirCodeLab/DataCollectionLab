package com.dcp.form

/**
 * Screen partition and navigation. Spec: specs/form-ir-v0.1.md section 11.
 *
 * This MUST produce results identical to the Python reference implementation in
 * backend/app/modules/form_engine/screens.py for every conformance vector.
 * Clients render what this module says — they never compute screen flow
 * themselves, so Android, iOS, desktop and web page through a form identically.
 */

data class FormScreen(
    /** Stable zero-based position in the plan; relevance never renumbers it. */
    val index: Int,
    /** The field-list group that produced this screen, or null. */
    val groupId: String?,
    /** Nearest enclosing group, for header/context display. */
    val sectionId: String?,
    val questionIds: List<String>,
)

/** Computes the static screen plan from the IR alone (spec 11.1). */
fun buildScreenPlan(ir: FormIr): List<FormScreen> {
    val screens = mutableListOf<FormScreen>()

    fun collectQuestions(nodes: List<FormNode>, out: MutableList<String>) {
        for (node in nodes) when (node) {
            is QuestionNode -> out.add(node.id)
            is GroupNode -> collectQuestions(node.children, out)
            is RepeatNode -> Unit // excluded from the screen plan (spec 11.1)
        }
    }

    fun walk(nodes: List<FormNode>, sectionId: String?) {
        for (node in nodes) when (node) {
            is QuestionNode -> screens.add(
                FormScreen(screens.size, groupId = null, sectionId = sectionId,
                    questionIds = listOf(node.id))
            )
            is GroupNode ->
                if (node.appearance == "field-list") {
                    val questions = mutableListOf<String>()
                    collectQuestions(node.children, questions)
                    if (questions.isNotEmpty()) screens.add(
                        FormScreen(screens.size, groupId = node.id, sectionId = sectionId,
                            questionIds = questions)
                    )
                } else {
                    walk(node.children, node.id)
                }
            is RepeatNode -> Unit // excluded from the screen plan (spec 11.1)
        }
    }
    walk(ir.children, null)
    return screens
}

/** A screen is relevant while at least one of its questions is (spec 11.2). */
fun screenRelevant(screen: FormScreen, instance: FormInstance): Boolean =
    screen.questionIds.any { instance.states[it]?.relevant == true }

/** Lowest-index relevant screen after [from]; `from = -1` gives the first. */
fun nextScreen(plan: List<FormScreen>, instance: FormInstance, from: Int): Int? =
    plan.firstOrNull { it.index > from && screenRelevant(it, instance) }?.index

/** Highest-index relevant screen before [from]. */
fun previousScreen(plan: List<FormScreen>, instance: FormInstance, from: Int): Int? =
    plan.lastOrNull { it.index < from && screenRelevant(it, instance) }?.index

/** Indices of every currently relevant screen, in order. */
fun relevantScreens(plan: List<FormScreen>, instance: FormInstance): List<Int> =
    plan.filter { screenRelevant(it, instance) }.map { it.index }

/**
 * Fields that block finalisation (spec 6.2): relevant, and carrying at least
 * one error of severity `error`. A soft constraint (`warning`) makes a field
 * invalid without blocking, so this is deliberately not `!isValid`.
 *
 * Order is field-state order — fields outside a repeat in document order, then
 * each repeat instance's fields in instance order — which is the same on both
 * engines.
 */
fun blockingFields(instance: FormInstance): List<String> =
    instance.states.entries
        .filter { (_, s) -> s.relevant && s.errors.any { it.severity == "error" } }
        .map { it.key }

/** True when nothing blocks finalisation (spec 6.2). */
fun canFinalize(instance: FormInstance): Boolean = blockingFields(instance).isEmpty()

/**
 * Lowest-index screen holding a blocking field, or null (spec 6.2) — where a
 * runtime should send the enumerator when it refuses to finalise.
 *
 * Null does NOT mean finalisation is allowed: a blocking field inside a repeat
 * has no screen at all, because repeats are excluded from the plan (spec 11.1).
 * [canFinalize] is the question about finalising; this one is about navigating.
 */
fun firstBlockingScreen(plan: List<FormScreen>, instance: FormInstance): Int? {
    val blocking = blockingFields(instance).toSet()
    return plan.firstOrNull { screen -> screen.questionIds.any { it in blocking } }?.index
}

/**
 * The screen cursor for one open form. Owns "which screen is current" so no
 * client reimplements it; clients call [next]/[previous] and render
 * [currentScreen].
 */
class FormNavigator(private val instance: FormInstance) {
    val plan: List<FormScreen> = instance.form.screens

    var currentIndex: Int = nextScreen(plan, instance, -1) ?: -1
        private set

    val currentScreen: FormScreen? get() = plan.getOrNull(currentIndex)

    val hasNext: Boolean get() = nextScreen(plan, instance, currentIndex) != null
    val hasPrevious: Boolean get() = previousScreen(plan, instance, currentIndex) != null

    /**
     * Moves to the next relevant screen.
     *
     * Never consults validity (spec 6.2): an enumerator can always leave a
     * screen whose answers are missing or wrong. The gate is [canFinalize].
     */
    fun next(): Boolean {
        val target = nextScreen(plan, instance, currentIndex) ?: return false
        currentIndex = target
        return true
    }

    fun previous(): Boolean {
        val target = previousScreen(plan, instance, currentIndex) ?: return false
        currentIndex = target
        return true
    }

    /**
     * The fields standing between this submission and finalisation (spec 6.2).
     * Lives here rather than in each client so Android, iOS, desktop and web
     * cannot disagree about which submissions may be sent.
     */
    val finalizationBlockers: List<String> get() = blockingFields(instance)

    /** True when the submission may be finalised (spec 6.2). */
    val canFinalize: Boolean get() = finalizationBlockers.isEmpty()

    /**
     * Moves to the first screen holding a blocking field, so a refusal to
     * finalise lands the enumerator on the question causing it.
     *
     * Returns false when there is no such screen — either nothing blocks, or
     * what blocks is inside a repeat and has no screen (spec 11.1). A caller
     * refusing finalisation must therefore test [canFinalize], not this.
     */
    fun goToFirstBlocking(): Boolean {
        val target = firstBlockingScreen(plan, instance) ?: return false
        currentIndex = target
        return true
    }

    /** 1-based position among relevant screens to total (spec 11.2); position
     * is 0 while the current screen itself is not relevant. */
    fun progress(): Pair<Int, Int> {
        val relevant = relevantScreens(plan, instance)
        return relevant.indexOf(currentIndex) + 1 to relevant.size
    }
}
