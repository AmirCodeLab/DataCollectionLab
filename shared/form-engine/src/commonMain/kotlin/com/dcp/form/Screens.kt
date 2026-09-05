package com.dcp.form

/**
 * Screen partition and navigation. Spec: specs/form-ir-v0.1.md section 11.
 *
 * This MUST produce results identical to the Python reference implementation in
 * backend/app/modules/form_engine/screens.py for every conformance vector.
 * Clients render what this module says — they never compute screen flow
 * themselves, so Android, iOS, desktop and web page through a form identically.
 *
 * Two levels, and exactly two. The plan holds one screen per question, one per
 * field-list group and **one per repeat**; a repeat's own children are
 * partitioned by the same rules into an *instance plan*, rendered once per
 * instance (§11.3). A repeat inside a repeat is a compile error (§2.3), so an
 * instance plan can hold no repeat screen and the nesting cannot go deeper.
 */

const val SCREEN_QUESTIONS: String = "questions"
const val SCREEN_REPEAT: String = "repeat"

data class FormScreen(
    /** Stable zero-based position in its plan; nothing renumbers it. */
    val index: Int,
    /** [SCREEN_QUESTIONS] or [SCREEN_REPEAT]. */
    val kind: String,
    /** The field-list group that produced this screen, or null. */
    val groupId: String?,
    /** Nearest enclosing group, for header/context display. */
    val sectionId: String?,
    /** Empty on a repeat screen: it asks nothing itself. */
    val questionIds: List<String>,
    /** Set only on a repeat screen: the repeat whose instance list it shows. */
    val repeatId: String? = null,
)

/**
 * The whole partition: the top-level screens and one plan per repeat.
 *
 * Both halves are pure functions of the IR. **An instance count never enters
 * either** (§11.3) — that is what keeps indices stable while an enumerator adds
 * members, and it is the property to check a change against.
 */
data class ScreenPlan(
    val screens: List<FormScreen>,
    val instancePlans: Map<String, List<FormScreen>>,
) {
    val size: Int get() = screens.size

    operator fun get(index: Int): FormScreen = screens[index]

    /**
     * Every question a runtime can put in front of somebody.
     *
     * Both levels, in one call, deliberately. A caller that read [screens]
     * alone would silently miss every repeat question — which is the exact
     * defect the importer's reachability refusal exists to catch
     * (`docs/known-defects.md` 14). There is no way to ask this question
     * half-way.
     */
    fun askableQuestionIds(): Set<String> =
        (screens.flatMap { it.questionIds } +
            instancePlans.values.flatten().flatMap { it.questionIds }).toSet()
}

/**
 * Where the enumerator is (§11.2): a top-level screen, or — inside a repeat
 * instance — that repeat's screen plus the **instance id** and the index within
 * the instance plan.
 *
 * The id is the point. §2.3 guarantees a delete never renumbers the survivors,
 * so a position holding an ordinal would silently move the enumerator into a
 * different person's answers when some other instance was deleted, with every
 * control on the screen still reading correctly. An id either still resolves or
 * it does not.
 */
data class Position(
    val screen: Int,
    val instanceId: String? = null,
    val instanceScreen: Int? = null,
) {
    val inside: Boolean get() = instanceId != null
}

/** Computes the static plan from the IR alone (spec 11.1). */
fun buildScreenPlan(ir: FormIr): ScreenPlan {
    val screens = mutableListOf<FormScreen>()
    val instancePlans = LinkedHashMap<String, List<FormScreen>>()

    fun collectQuestions(nodes: List<FormNode>, out: MutableList<String>) {
        for (node in nodes) when (node) {
            // A calculate is computed, never asked (spec 11.1). Listing it on a
            // field-list screen puts a control nobody can answer beside the ones
            // they can, and makes the screen relevant on the strength of a field
            // that is never drawn.
            is QuestionNode -> if (node.calculate == null) out.add(node.id)
            is GroupNode -> collectQuestions(node.children, out)
            // A repeat cannot appear here: it is a compile error inside a
            // field-list group (§10.2), and this walk only runs under one.
            is RepeatNode -> Unit
        }
    }

    fun walk(nodes: List<FormNode>, sectionId: String?, out: MutableList<FormScreen>) {
        for (node in nodes) when (node) {
            // A calculate produces NO screen. It has nothing to read and nothing
            // to answer, so its screen is blank: the enumerator taps past it,
            // and — the part that is not merely ugly — it counts toward the
            // "N of M" progress, which then overstates how much work is left on
            // every form that carries one.
            is QuestionNode -> if (node.calculate == null) out.add(
                FormScreen(out.size, SCREEN_QUESTIONS, groupId = null,
                    sectionId = sectionId, questionIds = listOf(node.id))
            )
            is GroupNode ->
                if (node.appearance == "field-list") {
                    val questions = mutableListOf<String>()
                    collectQuestions(node.children, questions)
                    if (questions.isNotEmpty()) out.add(
                        FormScreen(out.size, SCREEN_QUESTIONS, groupId = node.id,
                            sectionId = sectionId, questionIds = questions)
                    )
                } else {
                    walk(node.children, node.id, out)
                }
            is RepeatNode -> {
                // One screen, whatever the instance count — see ScreenPlan.
                out.add(
                    FormScreen(out.size, SCREEN_REPEAT, groupId = null,
                        sectionId = sectionId, questionIds = emptyList(),
                        repeatId = node.id)
                )
                val inner = mutableListOf<FormScreen>()
                walk(node.children, node.id, inner)
                instancePlans[node.id] = inner
            }
        }
    }
    walk(ir.children, null, screens)
    return ScreenPlan(screens, instancePlans)
}

// -- relevance -------------------------------------------------------------

/** Whether spec 2.3 would let the enumerator add an instance right now. */
private fun canAdd(instance: FormInstance, repeatId: String): Boolean {
    val node = instance.form.repeats[repeatId] ?: return false
    if (node.countExpr != null) return false
    val maximum = node.maxInstances ?: return true
    return instance.instanceCount(repeatId) < maximum
}

/**
 * A screen is relevant while at least one of its questions is (spec 11.2).
 *
 * A repeat screen has no questions, so §11.3 decides it instead: the repeat
 * itself is relevant, AND the screen has something to offer — an instance, or
 * one the enumerator may add.
 *
 * Both halves of that second condition matter and they pull opposite ways. A
 * countExpr repeat sized zero offers neither and is skipped, as a screen of only
 * calculates is. An enumerator-driven repeat with no instances yet must NOT be
 * skipped: its empty screen is the only door to the first instance.
 */
fun screenRelevant(screen: FormScreen, instance: FormInstance): Boolean {
    if (screen.kind == SCREEN_REPEAT) {
        val repeatId = screen.repeatId ?: return false
        if (!instance.containerRelevant(repeatId)) return false
        return instance.instanceCount(repeatId) > 0 || canAdd(instance, repeatId)
    }
    return screen.questionIds.any { instance.states[it]?.relevant == true }
}

/** The same rule, read against one instance's field states. */
fun instanceScreenRelevant(
    screen: FormScreen,
    instance: FormInstance,
    repeatId: String,
    instanceId: String,
): Boolean = screen.questionIds.any {
    instance.states["$repeatId[$instanceId].$it"]?.relevant == true
}

fun relevantInstanceScreens(
    plan: ScreenPlan,
    instance: FormInstance,
    repeatId: String,
    instanceId: String,
): List<Int> = (plan.instancePlans[repeatId] ?: emptyList())
    .filter { instanceScreenRelevant(it, instance, repeatId, instanceId) }
    .map { it.index }

// -- top-level navigation (spec 11.2) --------------------------------------

/** Lowest-index relevant screen after [from]; `from = -1` gives the first. */
fun nextScreen(plan: ScreenPlan, instance: FormInstance, from: Int): Int? =
    plan.screens.firstOrNull { it.index > from && screenRelevant(it, instance) }?.index

/** Highest-index relevant screen before [from]. */
fun previousScreen(plan: ScreenPlan, instance: FormInstance, from: Int): Int? =
    plan.screens.lastOrNull { it.index < from && screenRelevant(it, instance) }?.index

/** Indices of every currently relevant screen, in order. */
fun relevantScreens(plan: ScreenPlan, instance: FormInstance): List<Int> =
    plan.screens.filter { screenRelevant(it, instance) }.map { it.index }

// -- positions (spec 11.2, 11.3) -------------------------------------------

private fun repeatOf(plan: ScreenPlan, screenIndex: Int): String? =
    plan.screens[screenIndex].takeIf { it.kind == SCREEN_REPEAT }?.repeatId

/**
 * An instance that ceases to exist drops the position back to its repeat.
 *
 * One rule for every cause (§11.3): a delete, or a countExpr shrink that
 * discarded the trailing instance the enumerator was inside.
 */
fun resolvePosition(plan: ScreenPlan, instance: FormInstance, position: Position): Position {
    if (!position.inside) return position
    val repeatId = repeatOf(plan, position.screen) ?: return Position(position.screen)
    val order = instance.instances[repeatId] ?: return Position(position.screen)
    return if (position.instanceId in order) position else Position(position.screen)
}

/** The only way into an instance (§11.2). `next` never enters one. */
fun enterInstance(
    plan: ScreenPlan,
    instance: FormInstance,
    repeatId: String,
    instanceId: String,
): Position {
    val screen = plan.screens.firstOrNull {
        it.kind == SCREEN_REPEAT && it.repeatId == repeatId
    } ?: throw CompileException("no repeat screen for '$repeatId'")
    val relevant = relevantInstanceScreens(plan, instance, repeatId, instanceId)
    return if (relevant.isEmpty()) Position(screen.index)
    else Position(screen.index, instanceId, relevant.first())
}

/**
 * `next` over a position (§11.2, §11.3).
 *
 * From inside an instance this never returns null: past the last relevant
 * instance screen it LEAVES the instance to the repeat screen, which is where
 * the "are we finished?" decision belongs. It never moves to another instance.
 */
fun nextPosition(plan: ScreenPlan, instance: FormInstance, from: Position): Position? {
    val position = resolvePosition(plan, instance, from)
    if (!position.inside) {
        val next = nextScreen(plan, instance, position.screen) ?: return null
        return Position(next)
    }
    val repeatId = repeatOf(plan, position.screen)!!
    val relevant = relevantInstanceScreens(plan, instance, repeatId, position.instanceId!!)
    val later = relevant.filter { it > position.instanceScreen!! }
    return if (later.isEmpty()) Position(position.screen)
    else Position(position.screen, position.instanceId, later.first())
}

/** `previous` over a position. From the first instance screen it leaves. */
fun previousPosition(plan: ScreenPlan, instance: FormInstance, from: Position): Position? {
    val position = resolvePosition(plan, instance, from)
    if (!position.inside) {
        val previous = previousScreen(plan, instance, position.screen) ?: return null
        return Position(previous)
    }
    val repeatId = repeatOf(plan, position.screen)!!
    val relevant = relevantInstanceScreens(plan, instance, repeatId, position.instanceId!!)
    val earlier = relevant.filter { it < position.instanceScreen!! }
    return if (earlier.isEmpty()) Position(position.screen)
    else Position(position.screen, position.instanceId, earlier.last())
}

// -- progress (spec 11.2, 11.3) --------------------------------------------

/**
 * The form-level pair: 1-based position among relevant screens, and how many.
 *
 * A repeat screen counts ONCE, whatever it holds, and this pair does not move
 * while the enumerator is inside an instance — they have not left the repeat
 * screen. A household of six members reads `4 of 12` and still reads `4 of 12`
 * at seven; a denominator that moves is a promise the form withdraws.
 *
 * Position is 0 while the current screen is not itself relevant.
 */
fun progress(plan: ScreenPlan, instance: FormInstance, position: Position): Pair<Int, Int> {
    val relevant = relevantScreens(plan, instance)
    return relevant.indexOf(position.screen) + 1 to relevant.size
}

/**
 * The two pairs an open instance reports (§11.3), or null outside one: position
 * within the instance's currently relevant screens, and which instance is open
 * out of how many exist.
 *
 * Specified rather than left to clients for §6.2's reason — two runtimes that
 * each decide what "3 of 5" counts will decide differently, it will read as a
 * UX detail, and no conformance vector reaches a client.
 *
 * The across pair moves as instances are added. That is correct: it is the
 * roster's own count and not a claim about how much of the form is left.
 */
fun instanceProgress(
    plan: ScreenPlan,
    instance: FormInstance,
    from: Position,
): Pair<Pair<Int, Int>, Pair<Int, Int>>? {
    val position = resolvePosition(plan, instance, from)
    if (!position.inside) return null
    val repeatId = repeatOf(plan, position.screen)!!
    val relevant = relevantInstanceScreens(plan, instance, repeatId, position.instanceId!!)
    val within = relevant.indexOf(position.instanceScreen) + 1 to relevant.size
    val order = instance.instances[repeatId] ?: emptyList<String>()
    val across = order.indexOf(position.instanceId) + 1 to order.size
    return within to across
}

// -- finalisation (spec 6.2) -----------------------------------------------

/**
 * Fields that block finalisation (spec 6.2): relevant, and carrying at least
 * one error of severity `error`. A soft constraint (`warning`) makes a field
 * invalid without blocking, so this is deliberately not `!isValid`.
 *
 * Order is field-state order — fields outside a repeat in document order, then
 * each repeat instance's fields in instance order — which is the same on both
 * engines, and is NOT the order [firstBlockingPosition] walks.
 */
fun blockingFields(instance: FormInstance): List<String> =
    instance.states.entries
        .filter { (_, s) -> s.relevant && s.errors.any { it.severity == "error" } }
        .map { it.key }

/** True when nothing blocks finalisation (spec 6.2). */
fun canFinalize(instance: FormInstance): Boolean = blockingFields(instance).isEmpty()

/**
 * The earliest place to send somebody to see a blocking field (spec 6.2).
 *
 * Screen order, not [blockingFields] order: lowest top-level screen; then,
 * within a repeat screen, earliest instance in instance order, then lowest
 * instance screen. A blocking field on screen 9 can come first in
 * [blockingFields] while one on repeat screen 3 is the earliest place to go.
 * Both orders are defined and they answer different questions.
 *
 * Null does NOT mean finalisation is allowed. A `calculate` produces no screen
 * (§11.1), and a calculate carrying a failing hard constraint is relevant and
 * blocking, so nothing in the plan holds it — `docs/known-defects.md` 15.
 * [canFinalize] is the question about finalising; this one is about navigating.
 */
fun firstBlockingPosition(plan: ScreenPlan, instance: FormInstance): Position? {
    val blocking = blockingFields(instance).toSet()
    if (blocking.isEmpty()) return null
    for (screen in plan.screens) {
        if (screen.kind == SCREEN_REPEAT) {
            val repeatId = screen.repeatId ?: continue
            val inner = plan.instancePlans[repeatId] ?: emptyList()
            for (instanceId in instance.instances[repeatId] ?: emptyList<String>()) {
                for (innerScreen in inner) {
                    if (innerScreen.questionIds.any {
                            "$repeatId[$instanceId].$it" in blocking
                        }
                    ) {
                        return Position(screen.index, instanceId, innerScreen.index)
                    }
                }
            }
        } else if (screen.questionIds.any { it in blocking }) {
            return Position(screen.index)
        }
    }
    return null
}

/**
 * The screen cursor for one open form. Owns "which screen is current" so no
 * client reimplements it; clients call [next]/[previous] and render
 * [currentScreen].
 *
 * Thin, deliberately. Every rule it applies is a pure function above, present in
 * the Python reference too and asserted by vectors — because a rule that lives
 * only here is invisible to every vector (break 21), which is the same reason
 * §6.2's finalisation gate lives below this line.
 */
class FormNavigator(private val instance: FormInstance) {
    val plan: ScreenPlan = instance.form.screens

    var position: Position = Position(nextScreen(plan, instance, -1) ?: -1)
        private set

    val currentIndex: Int get() = position.screen

    val currentScreen: FormScreen? get() = plan.screens.getOrNull(position.screen)

    /** The instance screen being rendered, or null while not inside one. */
    val currentInstanceScreen: FormScreen?
        get() {
            val repeatId = currentScreen?.repeatId ?: return null
            val index = position.instanceScreen ?: return null
            return plan.instancePlans[repeatId]?.getOrNull(index)
        }

    val hasNext: Boolean get() = nextPosition(plan, instance, position) != null
    val hasPrevious: Boolean get() = previousPosition(plan, instance, position) != null

    /**
     * Moves to the next relevant screen — or, from the last screen of an
     * instance, out of the instance to its repeat screen (§11.3).
     *
     * Never consults validity (spec 6.2): an enumerator can always leave a
     * screen whose answers are missing or wrong. The gate is [canFinalize].
     */
    fun next(): Boolean {
        val target = nextPosition(plan, instance, position) ?: return false
        position = target
        return true
    }

    fun previous(): Boolean {
        val target = previousPosition(plan, instance, position) ?: return false
        position = target
        return true
    }

    /** Opens an instance (§11.2). `next` never does this by itself. */
    fun enter(repeatId: String, instanceId: String): Boolean {
        if (instanceId !in (instance.instances[repeatId] ?: emptyList<String>())) return false
        position = enterInstance(plan, instance, repeatId, instanceId)
        return true
    }

    /** Leaves the open instance for its repeat screen. */
    fun leave() {
        position = Position(position.screen)
    }

    /**
     * Re-reads the position after the instance list may have changed (§11.3):
     * a delete, or a countExpr shrink. A position whose instance is gone drops
     * back to the repeat screen; one whose instance survives does not move,
     * because it holds an id and not an ordinal.
     */
    fun refresh() {
        position = resolvePosition(plan, instance, position)
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
     * Moves to the first position holding a blocking field, so a refusal to
     * finalise lands the enumerator on the question causing it — inside the
     * right repeat instance, not merely on the roster.
     *
     * Returns false when there is no such position — either nothing blocks, or
     * what blocks is a calculate, which has no screen (defect 15). A caller
     * refusing finalisation must therefore test [canFinalize], not this.
     */
    fun goToFirstBlocking(): Boolean {
        val target = firstBlockingPosition(plan, instance) ?: return false
        position = target
        return true
    }

    /** 1-based position among relevant screens to total (spec 11.2); position
     * is 0 while the current screen itself is not relevant. Counts a repeat
     * once, however many instances it holds. */
    fun progress(): Pair<Int, Int> = progress(plan, instance, position)

    /** The open instance's own two pairs (spec 11.3), or null outside one. */
    fun instanceProgress(): Pair<Pair<Int, Int>, Pair<Int, Int>>? =
        instanceProgress(plan, instance, position)
}
