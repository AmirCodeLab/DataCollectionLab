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
 * [blockingFields], [firstBlockingScreen]) on both engines. They cannot see
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
        assertEquals(1, firstBlockingScreen(nav.plan, instance))

        instance.set("has_job", FormValue.Bool(false))
        assertTrue(nav.canFinalize, "a question never asked cannot block")
        assertNull(firstBlockingScreen(nav.plan, instance))
    }
}
