package com.dcp.form

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The trace reports evaluation and does not define it: every node's `result`
 * is what [Evaluator.evaluate] says for that node in the same context. The
 * case it exists for is §4.4's — an `and` whose second conjunct reads an
 * unanswered question is null, not false, and the screen cannot show which.
 */
class TraceTest {

    private val ir = """
        {"irVersion":"0.1","formId":"t","version":1,"title":{"en":"T"},
         "defaultLanguage":"en","languages":["en"],
         "children":[
           {"type":"question","id":"age","dataType":"integer","label":{"en":"Age"}},
           {"type":"question","id":"consent","dataType":"text","label":{"en":"Consent"}},
           {"type":"question","id":"detail","dataType":"text","label":{"en":"Detail"},
            "relevant":{"op":"and","args":[
              {"op":"gt","args":[{"op":"ref","path":"age"},{"op":"lit","value":17}]},
              {"op":"eq","args":[{"op":"ref","path":"consent"},{"op":"lit","value":"yes"}]}]}}
         ]}
    """.trimIndent()

    private fun assertMatchesEvaluator(node: TraceNode, expr: Expr, ctx: EvalContext) {
        assertEquals(Evaluator.evaluate(expr, ctx), node.result, "result of ${node.op}")
        val args = when (expr) {
            is Expr.Op -> expr.args
            is Expr.Call -> expr.args
            else -> emptyList()
        }
        assertEquals(args.size, node.args.size)
        args.zip(node.args).forEach { (e, n) -> assertMatchesEvaluator(n, e, ctx) }
    }

    @Test
    fun `an unanswered reference shows as null through the whole conjunction`() {
        val form = CompiledForm(FormIr.parse(ir))
        val instance = FormInstance(form, today = "2026-09-07")
        instance.set("age", FormValue.Integer(30))

        val trace = instance.trace("detail", "relevant")!!
        assertEquals("and", trace.op)
        assertEquals(FormValue.Null, trace.result, "null, not false: §4.4")
        assertEquals(FormValue.Bool(true), trace.args[0].result, "the first conjunct held")
        val second = trace.args[1]
        assertEquals(FormValue.Null, second.result)
        assertEquals("ref", second.args[0].op)
        assertEquals("consent", second.args[0].path)
        assertEquals(FormValue.Null, second.args[0].result, "the reference is what is null")
        assertEquals(FormValue.Text("yes"), second.args[1].literal)

        // §4.4: null is coerced to TRUE at the relevance boundary, so the question
        // stays visible — and nothing on screen says the condition never held.
        // The trace is how an author learns it came to null, not true.
        assertEquals(true, instance.states["detail"]?.relevant)
    }

    @Test
    fun `every node's result is the evaluator's for that node`() {
        val form = CompiledForm(FormIr.parse(ir))
        val instance = FormInstance(form, today = "2026-09-07")
        instance.set("age", FormValue.Integer(30))
        instance.set("consent", FormValue.Text("yes"))
        val expr = form.fields.getValue("detail").node.relevant!!
        val ctx = EvalContext(values = instance.values, today = "2026-09-07", now = "2026-09-07T00:00:00")
        assertMatchesEvaluator(traceExpression(expr, ctx), expr, ctx)
        assertEquals(FormValue.Bool(true), traceExpression(expr, ctx).result)
    }

    @Test
    fun `the JSON shape is the console's TraceNode`() {
        val form = CompiledForm(FormIr.parse(ir))
        val instance = FormInstance(form, today = "2026-09-07")
        val json = instance.trace("detail", "relevant")!!.toJson().jsonObject
        assertEquals("and", json.getValue("op").jsonPrimitive.content)
        assertEquals("null", json.getValue("result").toString())
        val ref = json.getValue("args").toString()
        check("\"path\":\"age\"" in ref) { ref }
        assertEquals(null, instance.trace("age", "relevant"), "no expression, no trace")
        assertEquals(null, instance.trace("nobody", "relevant"))
    }
}
