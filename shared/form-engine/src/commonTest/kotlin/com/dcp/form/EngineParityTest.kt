package com.dcp.form

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/*
 * The same assertions on every target the engine is built for.
 *
 * `commonTest` rather than `jvmTest` deliberately: the point is not that these
 * behaviours hold, which the conformance vectors already establish far more
 * thoroughly on the JVM. The point is that they hold **somewhere other than
 * the JVM**, which nothing in this repository has ever checked (known defect
 * 18). The form is inline because the 113 vectors are files on disk and a
 * browser has no disk — that gap is what docs/wasm-spike.md is about.
 */
private const val IR = """
{"irVersion":"0.1","formId":"parity","version":1,"defaultLanguage":"en",
 "languages":["en"],
 "children":[
  {"type":"question","id":"age","dataType":"integer","label":{"en":"Age"}},
  {"type":"question","id":"preg","dataType":"boolean","label":{"en":"Pregnant"},
   "relevant":{"op":"gte","args":[{"op":"ref","path":"age"},{"op":"lit","value":18}]}},
  {"type":"repeat","id":"members","label":{"en":"Members"},
   "summaryLabel":{"en":"{0}"},"summaryLabelArgs":[{"op":"ref","path":"name"}],
   "minInstances":2,
   "children":[{"type":"question","id":"name","dataType":"text","label":{"en":"Name"}}]}]}
"""

private fun instance() =
    FormInstance(CompiledForm(FormIr.parse(IR)), today = "2026-09-06").also { it.recalculate() }

class EngineParityTest {

    @Test
    fun relevanceOfAnUnansweredDependencyIsTrue() {
        // §4.4.7: null coerces to true for relevance. A question is shown until
        // something says otherwise, which is why an unanswered form opens.
        assertEquals(true, instance().states["preg"]?.relevant)
    }

    @Test
    fun relevanceFlipsWithTheAnswer() {
        val form = instance()
        form.set("age", FormValue.Integer(10L))
        assertEquals(false, form.states["preg"]?.relevant)
        form.set("age", FormValue.Integer(20L))
        assertEquals(true, form.states["preg"]?.relevant)
    }

    @Test
    fun theLabelChainFallsThroughToThePosition() {
        // Every summaryLabelArgs argument null -> the 1-based position (§2.3).
        val form = instance()
        val ids = form.instances.getValue("members")
        assertEquals(listOf("1", "2"), ids.map { form.summaryLabel("members", it, "en") })
        form.set("members[0].name", FormValue.Text("Ali"))
        assertEquals("⁨Ali⁩", form.summaryLabel("members", ids[0], "en"))
    }

    @Test
    fun theScreenPlanIsBuilt() {
        val plan = buildScreenPlan(FormIr.parse(IR))
        assertTrue(plan.screens.isNotEmpty())
    }
}
