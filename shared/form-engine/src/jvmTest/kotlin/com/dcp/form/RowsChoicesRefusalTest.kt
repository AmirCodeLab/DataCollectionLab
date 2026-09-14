package com.dcp.form

import kotlinx.serialization.json.Json
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * §10.2's two refusals for a `rows` choice list (Form IR §3.3).
 *
 * **No conformance vector reaches these.** Every case in `conformance/vectors`
 * is a form plus an ordered list of steps, and every step assumes a form that
 * compiled — the format cannot say "this document must be refused".
 * `conformance/malformed` covers §10.1 and `conformance/sensitivity` covers
 * exactly one §10.2 rule; the rest of §10.2 is held by a test in each engine
 * and nothing else.
 *
 * That is a real exposure and it is named here rather than left to be
 * discovered: two engines disagreeing about which forms compile is a form
 * author meeting a refusal their builder told them was not there. The Python
 * half is `backend/tests/test_rows_choices_refusals.py`, and the two must be
 * changed together.
 */
class RowsChoicesRefusalTest {

    private fun form(vararg children: String): FormIr = FormIr.parse(
        Json.parseToJsonElement(
            """
            {"irVersion":"0.1","formId":"rows_refusal","version":1,
             "title":{"en":"rows"},"defaultLanguage":"en","languages":["en"],
             "children":[${children.joinToString(",")}]}
            """
        )
    )

    private fun roster(inner: String = "", summary: Boolean = true): String {
        val label =
            if (summary) """"summaryLabel":{"en":"{0}"},
                           "summaryLabelArgs":[{"op":"ref","path":"name"}],"""
            else ""
        val extra = if (inner.isEmpty()) "" else ",$inner"
        return """
            {"type":"repeat","id":"members","label":{"en":"Members"},
             $label"allowAdd":true,"allowDelete":true,
             "children":[{"type":"question","id":"name","dataType":"text",
                          "label":{"en":"Name"}}$extra]}
        """
    }

    private fun mother(repeat: String = "members", excludeSelf: Boolean = false): String = """
        {"type":"question","id":"mother","dataType":"select_one",
         "label":{"en":"Mother"},
         "choices":{"kind":"rows","repeat":"$repeat","excludeSelf":$excludeSelf}}
    """

    /**
     * The control. Without it every assertion below passes on an engine that
     * refused every `rows` list, which would satisfy the refusals and fail a
     * customer.
     */
    @Test
    fun `a rows list over a roster compiles`() {
        val compiled = CompiledForm(form(roster(), mother()))
        assertTrue(compiled.fields.getValue("mother").rowsQuery != null)
    }

    /**
     * There is no "self" to exclude, so the flag could only be a no-op — the
     * shape `docs/project-conventions.md` calls two claims wearing one
     * assertion. The author either named the wrong repeat or put the question
     * in the wrong place, and both are worth being told.
     */
    @Test
    fun `excludeSelf outside its own repeat is refused`() {
        val refusal = assertFailsWith<CompileException> {
            CompiledForm(form(roster(), mother(excludeSelf = true)))
        }
        assertTrue("excludeSelf" in refusal.message.orEmpty())
        assertTrue("members" in refusal.message.orEmpty())
    }

    /**
     * The other half of the rule, and why it is not simply "no flag": MICS6
     * HL14 is asked **on the member's own row**, which is exactly where the
     * flag means something.
     */
    @Test
    fun `the same question inside the repeat compiles`() {
        val compiled = CompiledForm(form(roster(mother(excludeSelf = true))))
        assertEquals(true, compiled.fields.getValue("mother").rowsQuery?.excludeSelf)
    }

    /**
     * An unresolvable reference, and one [CompiledForm.checkReferences] cannot
     * see: it walks `dependsOn`, which holds field ids, and a repeat id is not
     * a field. Without this the list resolves to nothing on every device with
     * nothing in an error state.
     */
    @Test
    fun `a rows list over something that is not a repeat is refused`() {
        val refusal = assertFailsWith<CompileException> {
            CompiledForm(form(roster(), mother(repeat = "household")))
        }
        assertTrue("household" in refusal.message.orEmpty())
    }

    /**
     * §10.3: the list is legal, correct, and a column of bare position
     * numbers. A warning rather than an error because the spec permits the
     * document, and worth making because it stopped being a limitation when
     * `summaryLabelArgs` got an editor.
     */
    @Test
    fun `a rows list with no summaryLabel warns rather than refusing`() {
        val compiled = CompiledForm(form(roster(summary = false), mother()))
        assertEquals(
            listOf(
                "mother: chooses from the rows of repeat 'members', which has no " +
                    "summaryLabel, so the options are position numbers"
            ),
            compiled.warnings,
        )
    }
}
