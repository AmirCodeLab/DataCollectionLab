package com.dcp.form

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive

/**
 * The preview session answers in the console's shape and decides nothing: the
 * rows, the controls, the pairs, the blockers are the engine's. The fixture is
 * the handset's roster fixture (`RosterTest` in clients/composeApp), so the
 * preview and the handset are asked the same questions of the same form.
 */
class PreviewSessionTest {

    private val ir = """
        {"irVersion":"0.1","formId":"clinic","version":1,
         "title":{"en":"Clinic"},"defaultLanguage":"en","languages":["en"],
         "children":[
           {"type":"question","id":"consent","dataType":"text","label":{"en":"Consent"}},
           {"type":"repeat","id":"members","label":{"en":"Household members"},
            "rowSource":{"kind":"inline","items":[
               {"value":"mother","label":{"en":"Mother"}},
               {"value":"father","label":{"en":"Father"}}],
             "bind":{"name":"value"},"allowAdd":false,"allowDelete":false},
            "children":[
              {"type":"question","id":"name","dataType":"text","label":{"en":"Name"}},
              {"type":"question","id":"age","dataType":"integer","label":{"en":"Age"},
               "required":true,
               "relevant":{"op":"ne","args":[{"op":"ref","path":"name"},{"op":"lit","value":"skip"}]}}]},
           {"type":"repeat","id":"visits","label":{"en":"Visits"},"minInstances":0,
            "maxInstances":2,"addLabel":{"en":"Add a visit"},
            "children":[
              {"type":"question","id":"note","dataType":"text","label":{"en":"Note"},
               "required":true}]}
         ]}
    """.trimIndent()

    private fun parse(raw: String): JsonObject = Json.parseToJsonElement(raw).jsonObject
    private fun open() = PreviewSession.open(ir, "2026-09-07")
    private fun JsonObject.str(key: String) = getValue(key).jsonPrimitive.content
    private fun JsonObject.bool(key: String) = getValue(key).jsonPrimitive.boolean

    private fun PreviewSession.toRepeat(repeatId: String): JsonObject {
        var state = parse(state())
        while (state.getValue("screen").jsonObject.getValue("repeatId").let { it is JsonNull || it.jsonPrimitive.content != repeatId }) {
            state = parse(next())
        }
        return state
    }

    @Test
    fun `the fixed-list roster shows rows by their labels, no add, no delete`() {
        val session = open()
        val state = session.toRepeat("members")
        val roster = state.getValue("roster").jsonObject
        assertEquals(listOf("Mother", "Father"), roster.getValue("rows").jsonArray.map { it.jsonObject.str("label") })
        assertFalse(roster.bool("canAdd"))
        assertTrue(roster.getValue("rows").jsonArray.none { it.jsonObject.bool("canDelete") })
        assertEquals("Household members", roster.str("title"))
        assertEquals(JsonNull, state.getValue("inside"))
        assertTrue(state.getValue("questions").jsonArray.isEmpty(), "a repeat screen asks nothing")
    }

    @Test
    fun `entering a row gives the two pairs and questions keyed by the instance path`() {
        val session = open()
        session.toRepeat("members")
        val state = parse(session.enter("members", "i1"))
        val inside = state.getValue("inside").jsonObject
        assertEquals("Mother", inside.str("rowLabel"))
        assertEquals("[1,2]", inside.getValue("within").toString())
        assertEquals("[1,2]", inside.getValue("across").toString())
        val questions = state.getValue("questions").jsonArray.map { it.jsonObject }
        assertEquals(listOf("members[i1].name"), questions.map { it.str("path") })
        assertEquals("mother", questions[0].str("value"), "seeded from the row (§2.3)")
        assertEquals(JsonNull, state.getValue("roster"), "no roster inside a row")
        // The form-level pair does not move inside a row (§11.3).
        assertEquals("[2,3]", state.getValue("progress").toString())
    }

    @Test
    fun `set changes the values, and an unknown path is an error`() {
        val session = open()
        val state = parse(session.set("members[i1].age", "41"))
        assertEquals("41", state.getValue("values").jsonObject.str("members[i1].age"))
        val refused = parse(session.set("nobody", "1"))
        assertTrue("unknown path" in refused.str("error"))
    }

    @Test
    fun `adding a row opens it, and its required question blocks finalisation`() {
        val session = open()
        session.toRepeat("visits")
        val state = parse(session.addRow("visits"))
        val inside = state.getValue("inside").jsonObject
        assertEquals("visits", inside.str("repeatId"))
        assertEquals("i3", inside.str("instanceId"), "the fixed list minted i1 and i2")
        assertFalse(state.bool("canFinalize"))
        assertTrue("visits[i3].note" in state.getValue("blockers").jsonArray.map { it.jsonPrimitive.content })
        val back = parse(session.leave())
        val roster = back.getValue("roster").jsonObject
        assertEquals(1, roster.getValue("rows").jsonArray.size)
        assertTrue(roster.bool("canAdd"), "maxInstances 2, one row")
        assertEquals("Add a visit", roster.str("addLabel"))
    }

    @Test
    fun `the controls shown are what the engine permits, side by side`() {
        for (repeatId in listOf("members", "visits")) {
            val session = open()
            val shown = session.toRepeat(repeatId).getValue("roster").jsonObject.bool("canAdd")
            val fresh = FormInstance(CompiledForm(FormIr.parse(ir)), today = "2026-09-07")
            val permitted = runCatching { fresh.addInstance(repeatId) }.isSuccess
            assertEquals(permitted, shown, "add on $repeatId")
        }
    }

    @Test
    fun `a refused delete is an error and the state is unchanged`() {
        val session = open()
        val before = session.toRepeat("members").toString()
        val refused = parse(session.deleteRow("members", "i1"))
        assertTrue("does not permit deleting" in refused.str("error"), refused.toString())
        assertEquals(before, session.state())
    }

    @Test
    fun `a trace's root result is the field's relevance`() {
        val session = open()
        session.set("members[i1].name", "\"skip\"")
        val state = parse(session.state())
        assertFalse(state.getValue("relevant").jsonObject.bool("members[i1].age"))
        val trace = parse(session.trace("members[i1].age", "relevant"))
        assertEquals("ne", trace.str("op"))
        assertEquals("false", trace.getValue("result").toString())
        // Traced in ITS row: the other row's name is still "father".
        val other = parse(session.trace("members[i2].age", "relevant"))
        assertEquals("true", other.getValue("result").toString())
        val none = parse(session.trace("consent", "relevant"))
        assertTrue("no `relevant`" in none.str("error"))
    }

    @Test
    fun `sessions are handles, and a wrong one is an error`() {
        val opened = parse(PreviewSessions.open(ir, "2026-09-07"))
        val handle = opened.str("handle")
        assertTrue(handle.startsWith("s"))
        assertTrue(parse(PreviewSessions.with(handle) { it.state() }).containsKey("screen"))
        PreviewSessions.close(handle)
        assertTrue("no open preview" in parse(PreviewSessions.with(handle) { it.state() }).str("error"))
        assertTrue("error" in parse(PreviewSessions.open("{\"nonsense\":1}", "2026-09-07")))
    }
}
