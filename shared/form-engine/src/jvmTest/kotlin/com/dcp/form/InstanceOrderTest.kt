package com.dcp.form

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

/**
 * A repeat's instance list is in creation order.
 *
 * No conformance vector can reach this. A vector fixes the inputs and compares
 * the outputs; this is an assertion about the engine's own internal state, and
 * the way to violate it is to reorder [FormInstance.instances] directly — which
 * a vector has no step for and never will. So it is watched here and in
 * `backend/tests/test_instance_order_invariant.py`, one per engine, the pattern
 * docs/project-conventions.md sets out for anything above the vectors' reach.
 *
 * Why it matters is spec 2.3, and it takes two of its sentences together:
 * shrinking a `countExpr` repeat "discards the trailing instances", and the
 * shrink implements that by popping the END of the list. That is only the
 * trailing instance while the list is in creation order. Break 75 is what the
 * other outcome looks like — the count stays right and somebody else's answers
 * are destroyed.
 */
class InstanceOrderTest {

    private fun instance(): FormInstance = FormInstance(
        CompiledForm(
            FormIr.parse(
                """
                {
                  "irVersion": "0.1", "formId": "order", "version": 1,
                  "title": {"en": "order"}, "defaultLanguage": "en",
                  "languages": ["en"],
                  "children": [
                    {"type": "question", "id": "n", "dataType": "integer",
                     "label": {"en": "How many"}},
                    {"type": "repeat", "id": "members", "label": {"en": "Members"},
                     "countExpr": {"op": "ref", "path": "n"},
                     "children": [
                       {"type": "question", "id": "name", "dataType": "text",
                        "label": {"en": "Name"}}
                     ]}
                  ]
                }
                """
            )
        ),
        today = "2026-08-28",
    )

    private fun threeMembers(): FormInstance {
        val instance = instance()
        instance.set("n", FormValue.Integer(3))
        instance.setMany(
            mapOf(
                "members[0].name" to FormValue.Text("A"),
                "members[1].name" to FormValue.Text("B"),
                "members[2].name" to FormValue.Text("C"),
            )
        )
        return instance
    }

    @Test
    fun `a reordered instance list is refused rather than silently shrunk`() {
        val instance = threeMembers()
        assertEquals(listOf("i1", "i2", "i3"), instance.instances.getValue("members"))

        instance.instances.getValue("members").reverse()

        val raised = assertFailsWith<CompileException> {
            instance.set("n", FormValue.Integer(2))
        }
        assertTrue(
            raised.message!!.contains("not in creation order"),
            "message should name the invariant, was: ${raised.message}",
        )
        assertTrue(
            raised.message!!.contains("members"),
            "message should name the repeat, was: ${raised.message}",
        )
    }

    @Test
    fun `the same shrink is allowed and discards the trailing member when order holds`() {
        val instance = threeMembers()

        instance.set("n", FormValue.Integer(2))

        assertEquals(listOf("i1", "i2"), instance.instances.getValue("members"))
        assertEquals(FormValue.Text("A"), instance.values.getValue("members[i1].name"))
        assertEquals(FormValue.Text("B"), instance.values.getValue("members[i2].name"))
    }

    @Test
    fun `a swap of two adjacent instances is caught, not only a full reversal`() {
        val instance = threeMembers()
        val ordered = instance.instances.getValue("members")

        val first = ordered[0]
        ordered[0] = ordered[1]
        ordered[1] = first

        assertFailsWith<CompileException> { instance.set("n", FormValue.Integer(2)) }
    }
}
