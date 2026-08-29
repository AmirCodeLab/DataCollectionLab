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

    /** 1-based position among relevant screens to total (spec 11.2); position
     * is 0 while the current screen itself is not relevant. */
    fun progress(): Pair<Int, Int> {
        val relevant = relevantScreens(plan, instance)
        return relevant.indexOf(currentIndex) + 1 to relevant.size
    }
}
