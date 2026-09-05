package com.dcp.form

import kotlinx.serialization.json.Json
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * A repeat inside a field-list group is refused (§10.2), and the shapes that
 * are fine still are.
 *
 * **No conformance vector reaches this.** Every case in `conformance/vectors`
 * is a form plus an ordered list of steps, and every step assumes a form that
 * compiled — the format cannot say "this document must be refused".
 * `conformance/malformed` covers §10.1 and `conformance/sensitivity` covers
 * exactly one §10.2 rule; the rest of §10.2, this refusal and the nested-repeat
 * refusal included, is held by a test in each engine and nothing else.
 *
 * That is a real exposure and it is named here rather than left to be
 * discovered: two engines disagreeing about which forms compile is a form
 * author meeting a refusal their builder told them was not there. The Python
 * half is `backend/tests/test_repeat_in_field_list.py`, and the two must be
 * changed together.
 */
class ScreensRepeatTest {

    private fun form(children: String): FormIr = FormIr.parse(
        Json.parseToJsonElement(
            """
            {"irVersion":"0.1","formId":"fl_repeat","version":1,
             "title":{"en":"field-list and repeat"},"defaultLanguage":"en",
             "languages":["en"],"children":[$children]}
            """
        )
    )

    private val roster = """
        {"type":"repeat","id":"members","label":{"en":"Members"},
         "children":[{"type":"question","id":"nm","dataType":"text",
                      "label":{"en":"Name"}}]}
    """

    /**
     * Not a trade — a contradiction. `field-list` means these questions appear
     * together on one screen; a repeat means a separate screen you enter and
     * leave (§11.3). Both cannot be true of the same subtree.
     */
    @Test
    fun aRepeatInsideAFieldListGroupIsRefused() {
        val failure = assertFailsWith<CompileException> {
            CompiledForm(
                form(
                    """
                    {"type":"group","id":"fl","label":{"en":"Field list"},
                     "appearance":"field-list","children":[
                        {"type":"question","id":"a","dataType":"text","label":{"en":"A"}},
                        $roster]}
                    """
                )
            )
        }
        assertTrue("field-list" in failure.message!!, failure.message!!)
        // Names both ends, so an author can find it in a workbook of any size.
        assertTrue("members" in failure.message!! && "fl" in failure.message!!)
    }

    /**
     * The half a shallow check would miss. §11.1 flattens nested plain groups
     * into the field-list screen, so a repeat two levels down is inside it
     * exactly as much as one directly in it. A check that looked only at the
     * immediate parent would let this through and drop the roster's questions
     * silently, which is defect 14 again.
     */
    @Test
    fun theRefusalReachesThroughANestedPlainGroup() {
        val failure = assertFailsWith<CompileException> {
            CompiledForm(
                form(
                    """
                    {"type":"group","id":"fl","label":{"en":"Field list"},
                     "appearance":"field-list","children":[
                        {"type":"group","id":"inner","label":{"en":"Inner"},
                         "children":[$roster]}]}
                    """
                )
            )
        }
        assertTrue("field-list" in failure.message!!, failure.message!!)
    }

    /**
     * The refusal is about containment and nothing wider. Without this, a check
     * that refused any form holding both would pass the two above and be wrong
     * about every real questionnaire — RCons's has 95 sections and a roster.
     */
    @Test
    fun aRepeatBesideAFieldListGroupIsFine() {
        val ir = form(
            """
            {"type":"group","id":"fl","label":{"en":"Field list"},
             "appearance":"field-list","children":[
                {"type":"question","id":"a","dataType":"text","label":{"en":"A"}}]},
            $roster
            """
        )
        val compiled = CompiledForm(ir)
        val plan = buildScreenPlan(ir)

        assertTrue("members" in compiled.repeats)
        assertEquals(listOf(SCREEN_QUESTIONS, SCREEN_REPEAT), plan.screens.map { it.kind })
        assertEquals(setOf("a", "nm"), plan.askableQuestionIds())
    }

    /**
     * A plain group contributes no screen of its own (§11.1), so it makes no
     * promise a repeat can contradict.
     */
    @Test
    fun aRepeatInsideAPlainGroupIsFine() {
        val plan = buildScreenPlan(
            form(
                """
                {"type":"group","id":"plain","label":{"en":"Plain"},
                 "children":[$roster]}
                """
            )
        )
        assertEquals(listOf(SCREEN_REPEAT), plan.screens.map { it.kind })
        assertEquals("plain", plan.screens[0].sectionId)
    }
}
