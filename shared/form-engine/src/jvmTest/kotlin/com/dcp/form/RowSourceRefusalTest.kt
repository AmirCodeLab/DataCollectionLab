package com.dcp.form

import kotlinx.serialization.json.Json
import org.junit.Test
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * §10.2's four `rowSource` refusals (Form IR §2.3).
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
 * half is `backend/tests/test_row_source_refusals.py`, and the two must be
 * changed together.
 *
 * **One of these four is expected to be deleted.** `kind: "dataset"` is not
 * malformed and not ambiguous — it is specified, and two things it depends on
 * do not exist (§2.3, *What is live*). Its test asserts that its message says
 * so, because a form author who wrote a valid preloaded roster needs to read
 * "not built yet" rather than "your form is wrong".
 */
class RowSourceRefusalTest {

    private fun form(repeat: String): FormIr = FormIr.parse(
        Json.parseToJsonElement(
            """
            {"irVersion":"0.1","formId":"row_source","version":1,
             "title":{"en":"rowSource"},"defaultLanguage":"en","languages":["en"],
             "children":[
               {"type":"question","id":"hh","dataType":"text","label":{"en":"Hh"}},
               $repeat]}
            """
        )
    )

    private val items = """
        [{"value":"zero_till","label":{"en":"Zero tillage"}},
         {"value":"laser_lvl","label":{"en":"Laser levelling"}}]
    """

    private fun repeat(rowSource: String, extra: String = ""): String = """
        {"type":"repeat","id":"practices","label":{"en":"Practices"},
         "rowSource":$rowSource$extra,
         "children":[{"type":"question","id":"practice","dataType":"text",
                      "label":{"en":"Practice"}}]}
    """

    private fun inline(extra: String = ""): String =
        """{"kind":"inline","items":$items$extra}"""

    /**
     * The control. Without it every assertion below passes on a broken parser.
     *
     * Three of the four refusals are about a form that is *nearly* this one, so
     * a compiler that refused all `rowSource` nodes would satisfy them and fail
     * a customer.
     */
    @Test
    fun `a valid inline row source compiles`() {
        val compiled = CompiledForm(form(repeat(inline(""", "bind":{"practice":"value"}"""))))
        assertTrue("practices" in compiled.repeats)
    }

    @Test
    fun `countExpr and rowSource together are refused`() {
        val failure = assertFailsWith<CompileException> {
            CompiledForm(form(repeat(inline(), extra = ""","countExpr":{"op":"lit","value":3}""")))
        }
        assertTrue("countExpr" in failure.message!! && "rowSource" in failure.message!!)
    }

    /**
     * `hh` is a real question, and it is not per-row. Naming a field that does
     * not exist at all would be caught by reference resolution and would prove
     * nothing about this rule.
     */
    @Test
    fun `a bind reaching outside its repeat is refused`() {
        val failure = assertFailsWith<CompileException> {
            CompiledForm(form(repeat(inline(""", "bind":{"hh":"value"}"""))))
        }
        assertTrue("hh" in failure.message!!)
    }

    /**
     * A label is §7 i18n and an answer is one value in no language.
     *
     * Refused rather than defaulted to the form's default language: two engines
     * choosing a language is two forms, and the failure would be invisible
     * until somebody opened the form in Urdu.
     */
    @Test
    fun `binding an inline label is refused`() {
        val failure = assertFailsWith<CompileException> {
            CompiledForm(form(repeat(inline(""", "bind":{"practice":"label"}"""))))
        }
        assertTrue("label" in failure.message!!)
    }

    @Test
    fun `binding a column an inline row does not have is refused`() {
        val failure = assertFailsWith<CompileException> {
            CompiledForm(form(repeat(inline(""", "bind":{"practice":"age"}"""))))
        }
        assertTrue("age" in failure.message!!)
    }

    /**
     * The refusal expected to be deleted, and the only one whose *wording* is
     * asserted here.
     *
     * §10.2 requires this message to read differently from the other three: the
     * form is valid and the platform is not ready. An author who wrote a
     * correct preloaded roster and read "invalid rowSource" would go and change
     * a form that has nothing wrong with it.
     */
    @Test
    fun `a dataset row source is refused and says why it is not built`() {
        val failure = assertFailsWith<CompileException> {
            CompiledForm(
                form(
                    repeat(
                        """{"kind":"dataset","dataset":"hh_members",
                            "bind":{"practice":"name"}}"""
                    )
                )
            )
        }
        val message = failure.message!!
        assertTrue("not yet implemented" in message)
        assertTrue("case_key" in message, "name the dependency, not just the refusal")
        assertTrue("16" in message, "point at the defect holding the other half")
    }

    @Test
    fun `an unknown row source kind is refused`() {
        assertFailsWith<CompileException> {
            CompiledForm(form(repeat("""{"kind":"sample","items":$items}""")))
        }
    }
}
