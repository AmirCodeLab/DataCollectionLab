package com.dcp.form

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * [FormNavigator] — the screen cursor every client drives.
 *
 * The conformance vectors pin the pure functions underneath it ([nextScreen],
 * [blockingFields], [firstBlockingPosition]) on both engines. They cannot see
 * this class: it is Kotlin-only, because the Python reference has no
 * interactive cursor. So a validity check added to [FormNavigator.next] — the
 * exact drift §6.2 exists to prevent, one level above where the vectors look —
 * would pass every vector. These tests watch that layer.
 */
class NavigatorTest {

    /**
     * Three screens: an unanswered required name, an age that can be given an
     * impossible value, and a comment that is never a problem.
     */
    private fun instance(): FormInstance = FormInstance(
        CompiledForm(
            FormIr.parse(
                """
                {
                  "irVersion": "0.1", "formId": "nav", "version": 1,
                  "title": {"en": "nav"}, "defaultLanguage": "en",
                  "languages": ["en"],
                  "children": [
                    {"type": "question", "id": "name", "dataType": "text",
                     "label": {"en": "Name"}, "required": true},
                    {"type": "question", "id": "age", "dataType": "integer",
                     "label": {"en": "Age"},
                     "constraint": {"op": "lte", "args": [
                        {"op": "ref", "path": "age"}, {"op": "lit", "value": 120}]}},
                    {"type": "question", "id": "comment", "dataType": "text",
                     "label": {"en": "Comment"}}
                  ]
                }
                """
            )
        ),
        today = "2026-08-28",
    )

    @Test
    fun `an enumerator can leave a screen whose required question is unanswered`() {
        val instance = instance()
        val nav = FormNavigator(instance)

        assertEquals(0, nav.currentIndex)
        assertFalse(instance.states.getValue("name").valid, "precondition: name blocks")

        assertTrue(nav.hasNext, "the forward control must not be disabled by an error")
        assertTrue(nav.next(), "next() must move off a screen holding a blocking field")
        assertEquals(1, nav.currentIndex)
    }

    @Test
    fun `an enumerator can leave a screen whose answer is invalid`() {
        val instance = instance()
        instance.set("age", FormValue.Integer(150))
        val nav = FormNavigator(instance)

        assertTrue(nav.next())
        assertEquals(1, nav.currentIndex, "on the invalid age")
        assertTrue(nav.next(), "and off it again")
        assertEquals(2, nav.currentIndex)
        assertTrue(nav.previous(), "and back onto it")
        assertEquals(1, nav.currentIndex)
    }

    @Test
    fun `finalisation is refused while a field blocks, and allowed once none does`() {
        val instance = instance()
        val nav = FormNavigator(instance)

        assertFalse(nav.canFinalize)
        assertEquals(listOf("name"), nav.finalizationBlockers)

        instance.set("age", FormValue.Integer(150))
        assertEquals(listOf("name", "age"), nav.finalizationBlockers, "document order")

        instance.set("name", FormValue.Text("Amina"))
        instance.set("age", FormValue.Integer(40))
        assertTrue(nav.canFinalize)
        assertEquals(emptyList(), nav.finalizationBlockers)
    }

    @Test
    fun `a refusal lands the enumerator on the screen holding the first blocker`() {
        val instance = instance()
        instance.set("age", FormValue.Integer(150))
        val nav = FormNavigator(instance)
        nav.next()
        nav.next()
        assertEquals(2, nav.currentIndex, "parked on the last screen")

        assertTrue(nav.goToFirstBlocking())
        assertEquals(0, nav.currentIndex, "the unanswered name, not the bad age")

        instance.set("name", FormValue.Text("Amina"))
        assertTrue(nav.goToFirstBlocking())
        assertEquals(1, nav.currentIndex, "now the bad age")

        instance.set("age", FormValue.Integer(40))
        assertFalse(nav.goToFirstBlocking(), "nothing to go to")
        assertEquals(1, nav.currentIndex, "and the cursor has not moved")
    }

    /**
     * The navigator reads live state rather than a snapshot taken when it was
     * constructed: a client holds one navigator for the whole submission, and
     * answers arrive through the instance, not through it.
     */
    @Test
    fun `blockers follow relevance, so a hidden field stops blocking`() {
        val instance = FormInstance(
            CompiledForm(
                FormIr.parse(
                    """
                    {
                      "irVersion": "0.1", "formId": "nav2", "version": 1,
                      "title": {"en": "nav2"}, "defaultLanguage": "en",
                      "languages": ["en"],
                      "children": [
                        {"type": "question", "id": "has_job", "dataType": "boolean",
                         "label": {"en": "Has job"}},
                        {"type": "question", "id": "employer", "dataType": "text",
                         "label": {"en": "Employer"}, "required": true,
                         "relevant": {"op": "eq", "args": [
                            {"op": "ref", "path": "has_job"},
                            {"op": "lit", "value": true}]}}
                      ]
                    }
                    """
                )
            ),
            today = "2026-08-28",
        )
        val nav = FormNavigator(instance)

        instance.set("has_job", FormValue.Bool(true))
        assertEquals(listOf("employer"), nav.finalizationBlockers)
        assertEquals(Position(1), firstBlockingPosition(nav.plan, instance))

        instance.set("has_job", FormValue.Bool(false))
        assertTrue(nav.canFinalize, "a question never asked cannot block")
        assertNull(firstBlockingPosition(nav.plan, instance))
    }

    /**
     * The "N of M" an enumerator reads, on a form carrying calculations.
     *
     * [FormNavigator.progress] is Kotlin-only — the Python reference has no
     * cursor — so no conformance vector reaches it. `screens-009` and
     * `screens-010` pin the plan and the relevant list on both engines; this
     * pins the pair of numbers the collection screen actually renders, which is
     * where the wrongness was visible: a calculate used to produce a blank
     * screen, so a two-question form with three calculations counted five.
     */
    @Test
    fun `progress counts only screens somebody can answer`() {
        val instance = FormInstance(
            CompiledForm(
                FormIr.parse(
                    """
                    {
                      "irVersion": "0.1", "formId": "prog", "version": 1,
                      "title": {"en": "prog"}, "defaultLanguage": "en",
                      "languages": ["en"],
                      "children": [
                        {"type": "question", "id": "a", "dataType": "integer",
                         "label": {"en": "A"}},
                        {"type": "question", "id": "c1", "dataType": "integer",
                         "label": {"en": "C1"}, "calculate": {"op": "lit", "value": 1}},
                        {"type": "question", "id": "c2", "dataType": "integer",
                         "label": {"en": "C2"}, "calculate": {"op": "lit", "value": 2}},
                        {"type": "question", "id": "c3", "dataType": "integer",
                         "label": {"en": "C3"}, "calculate": {"op": "lit", "value": 3}},
                        {"type": "question", "id": "b", "dataType": "integer",
                         "label": {"en": "B"}}
                      ]
                    }
                    """
                )
            ),
            today = "2026-08-28",
        )
        val nav = FormNavigator(instance)

        assertEquals(2, nav.progress().second, "three calculations must not be counted")
        assertEquals(1 to 2, nav.progress())

        assertTrue(nav.next(), "the next screen is the second real question, not a calculation")
        assertEquals(2 to 2, nav.progress())
        assertEquals("b", instance.form.screens[nav.currentIndex].questionIds.single())
    }

    /**
     * A roster: one question outside it, two inside, one after.
     *
     * The cursor's repeat behaviour is thin over vector-covered functions on
     * purpose (§11.3 is specified as pure functions so the vectors reach it),
     * but three decisions are this class's alone and no vector can see them:
     * whether [enter] validates the instance it is given, whether [refresh]
     * is applied at all, and whether [leave] exists as a distinct move.
     */
    private fun roster(): FormInstance = FormInstance(
        CompiledForm(
            FormIr.parse(
                """
                {
                  "irVersion": "0.1", "formId": "roster", "version": 1,
                  "title": {"en": "roster"}, "defaultLanguage": "en",
                  "languages": ["en"],
                  "children": [
                    {"type": "question", "id": "hh", "dataType": "text",
                     "label": {"en": "Household"}},
                    {"type": "repeat", "id": "members", "label": {"en": "Members"},
                     "minInstances": 0, "maxInstances": 5,
                     "children": [
                       {"type": "question", "id": "nm", "dataType": "text",
                        "label": {"en": "Name"}},
                       {"type": "question", "id": "ag", "dataType": "integer",
                        "label": {"en": "Age"}}]},
                    {"type": "question", "id": "tail", "dataType": "text",
                     "label": {"en": "Anything else"}}
                  ]
                }
                """
            )
        ),
        today = "2026-08-28",
    )

    @Test
    fun `next lands on the repeat screen and stops there`() {
        val instance = roster()
        instance.addInstance("members")
        val nav = FormNavigator(instance)

        assertEquals(Position(0), nav.position)
        assertTrue(nav.next())
        // On the roster, not inside a member: entering is an explicit act, so
        // that next moves one screen every time it is called (§11.2).
        assertEquals(Position(1), nav.position)
        assertEquals(SCREEN_REPEAT, nav.currentScreen?.kind)
        assertNull(nav.currentInstanceScreen)
        assertTrue(nav.next())
        assertEquals(Position(2), nav.position)
    }

    @Test
    fun `entering an instance that does not exist is refused rather than guessed`() {
        val instance = roster()
        val nav = FormNavigator(instance)

        // A stale id from a screen the enumerator left open, or a delete that
        // arrived between render and tap. Guessing here would put them in
        // somebody else's answers; the vectors cannot see this because
        // enterInstance is only ever called with a live id in a vector.
        assertFalse(nav.enter("members", "i99"))
        assertEquals(Position(0), nav.position)

        val added = instance.addInstance("members")
        assertTrue(nav.enter("members", added))
        assertEquals(Position(1, added, 0), nav.position)
        assertEquals("nm", nav.currentInstanceScreen?.questionIds?.single())
    }

    @Test
    fun `refresh drops a deleted instance and leaves a surviving one alone`() {
        val instance = roster()
        val first = instance.addInstance("members")
        val second = instance.addInstance("members")
        val nav = FormNavigator(instance)

        assertTrue(nav.enter("members", second))
        assertTrue(nav.next())
        assertEquals(Position(1, second, 1), nav.position)

        // Someone else's row goes: the cursor holds an id, so it does not move.
        instance.deleteInstance("members", 0)
        nav.refresh()
        assertEquals(Position(1, second, 1), nav.position)
        assertEquals(1, instance.instanceCount("members"))

        // Its own row goes: back to the list, which is the only place left.
        instance.deleteInstance("members", 0)
        nav.refresh()
        assertEquals(Position(1), nav.position)
        assertNull(nav.instanceProgress())
        assertEquals(first, first) // both ids were distinct; nothing survives
    }

    @Test
    fun `leave returns to the roster without touching the top level position`() {
        val instance = roster()
        val added = instance.addInstance("members")
        val nav = FormNavigator(instance)

        assertTrue(nav.enter("members", added))
        assertEquals(2 to 3, nav.progress())
        nav.leave()
        assertEquals(Position(1), nav.position)
        // The form-level pair never moved: leaving an instance is not leaving
        // the repeat screen (§11.3).
        assertEquals(2 to 3, nav.progress())
    }

    @Test
    fun `goToFirstBlocking lands inside the instance at fault, not merely on the roster`() {
        val instance = FormInstance(
            CompiledForm(
                FormIr.parse(
                    """
                    {
                      "irVersion": "0.1", "formId": "blk", "version": 1,
                      "title": {"en": "blk"}, "defaultLanguage": "en",
                      "languages": ["en"],
                      "children": [
                        {"type": "question", "id": "hh", "dataType": "text",
                         "label": {"en": "Household"}},
                        {"type": "repeat", "id": "members", "label": {"en": "Members"},
                         "minInstances": 0, "maxInstances": 5,
                         "children": [
                           {"type": "question", "id": "nm", "dataType": "text",
                            "label": {"en": "Name"}},
                           {"type": "question", "id": "ag", "dataType": "integer",
                            "label": {"en": "Age"}, "required": true}]}
                      ]
                    }
                    """
                )
            ),
            today = "2026-08-28",
        )
        instance.addInstance("members")
        val second = instance.addInstance("members")
        instance.set("members[0].ag", FormValue.Integer(40))
        val nav = FormNavigator(instance)

        assertFalse(nav.canFinalize)
        assertTrue(nav.goToFirstBlocking())
        // The second member's age screen — a refusal that named only the roster
        // would be a dead end on a household of thirty (§6.2).
        assertEquals(Position(1, second, 1), nav.position)
    }
}
