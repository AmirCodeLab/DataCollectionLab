package com.amr.data_collection_lab.collection

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.core.sync.OpKind
import com.dcp.core.sync.SubmissionStore
import com.dcp.form.CompileException
import com.dcp.form.CompiledForm
import com.dcp.form.FormInstance
import com.dcp.form.FormIr
import com.dcp.form.FormNavigator
import com.dcp.form.FormValue
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The roster is a view over Form IR §11.3, and these are the claims the view
 * makes that the engine's vectors cannot see: what the rows are called, which
 * controls appear, what the op log records, and — the one that matters most —
 * that a required question inside a row blocks finalisation once rows exist.
 *
 * The first end-to-end run (docs/e2e-run-2026-09-07.md) finalized and synced a
 * submission with two questions unanswered inside a roster nobody could reach.
 * The gate was never wrong; the door was missing. Now that the door exists,
 * this is what stops it opening onto a room the gate cannot see.
 */
class RosterTest {

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
               "required":true}]},
           {"type":"repeat","id":"visits","label":{"en":"Visits"},"minInstances":0,
            "maxInstances":2,"addLabel":{"en":"Add a visit"},
            "children":[
              {"type":"question","id":"note","dataType":"text","label":{"en":"Note"},
               "required":true}]}
         ]}
    """.trimIndent()

    private fun fresh(): Triple<CompiledForm, FormInstance, FormNavigator> {
        val form = CompiledForm(FormIr.parse(ir))
        val instance = FormInstance(form, today = "2026-09-07")
        return Triple(form, instance, FormNavigator(instance))
    }

    private fun FormNavigator.goToRepeat(repeatId: String) {
        while (currentScreen?.repeatId != repeatId) check(next()) { "no screen for $repeatId" }
    }

    @Test
    fun `a fixed list shows its rows by their source labels and neither control`() {
        val (_, instance, navigator) = fresh()
        navigator.goToRepeat("members")
        val roster = assertNotNull(rosterUi(navigator, instance, "en"))
        assertEquals("Household members", roster.title)
        assertEquals(listOf("Mother", "Father"), roster.rows.map { it.label })
        assertFalse(roster.canAdd, "a fixed list with allowAdd false shows no add control")
        assertTrue(roster.rows.none { it.canDelete }, "nor a delete control")
        // And the bound question is seeded from the row's value (§2.3).
        assertEquals(FormValue.Text("mother"), instance.values["members[i1].name"])
    }

    @Test
    fun `an enumerator-driven roster starts empty with an add control, and fills`() {
        val (_, instance, navigator) = fresh()
        navigator.goToRepeat("visits")
        val empty = assertNotNull(rosterUi(navigator, instance, "en"))
        assertTrue(empty.rows.isEmpty())
        assertTrue(empty.canAdd)
        assertEquals("Add a visit", empty.addLabel, "the form's own wording, §2.3")

        instance.addInstance("visits")
        instance.addInstance("visits")
        val full = assertNotNull(rosterUi(navigator, instance, "en"))
        assertEquals(listOf("1", "2"), full.rows.map { it.label }, "no label: the position")
        assertTrue(full.rows.all { it.canDelete })
        assertFalse(full.canAdd, "maxInstances 2 is reached")
    }

    @Test
    fun `the controls the roster shows are exactly what the engine would permit`() {
        // The engine refuses by throwing; the roster reads §2.3 from the node.
        // Side by side, on every repeat, so the two cannot drift.
        for (repeatId in listOf("members", "visits")) {
            val (_, instance, navigator) = fresh()
            navigator.goToRepeat(repeatId)
            val shown = assertNotNull(rosterUi(navigator, instance, "en")).canAdd
            val permitted = runCatching { instance.addInstance(repeatId) }.isSuccess
            assertEquals(permitted, shown, "add control on $repeatId")
        }
        val (_, instance, navigator) = fresh()
        navigator.goToRepeat("members")
        val shownDelete = rosterUi(navigator, instance, "en")!!.rows.first().canDelete
        val permittedDelete = runCatching { instance.deleteInstance("members", 0) }.isSuccess
        assertEquals(permittedDelete, shownDelete)
    }

    @Test
    fun `entering a row asks that row's questions and reads both pairs`() {
        val (_, instance, navigator) = fresh()
        navigator.goToRepeat("members")
        assertNull(instanceUi(navigator, instance, "en"), "outside a row there is no pair")

        assertTrue(navigator.enter("members", "i2"))
        assertNull(rosterUi(navigator, instance, "en"), "inside a row the roster is not shown")
        val open = assertNotNull(instanceUi(navigator, instance, "en"))
        assertEquals("Father", open.rowLabel)
        assertEquals(2 to 2, open.acrossPosition to open.acrossTotal)
        assertEquals(1 to 2, open.withinPosition to open.withinTotal)
        assertEquals(listOf("name"), navigator.currentInstanceScreen?.questionIds)
        assertEquals("members[i2].name", instancePath("members", "i2", "name"))
        assertEquals("name", fieldIdOf("members[i2].name"))
        assertEquals("members" to "i2", scopeOfPath("members[i2].name"))
    }

    @Test
    fun `finalisation is refused while a row's required question is unanswered`() {
        val (_, instance, navigator) = fresh()
        assertFalse(navigator.canFinalize)
        assertEquals(
            listOf("members[i1].age", "members[i2].age"),
            navigator.finalizationBlockers,
            "the gate sees the rows' required questions",
        )
        // And the refusal lands the enumerator inside the first row, on the
        // screen holding the question — not merely on the roster.
        assertTrue(navigator.goToFirstBlocking())
        val open = assertNotNull(instanceUi(navigator, instance, "en"))
        assertEquals("Mother", open.rowLabel)
        assertEquals(listOf("age"), navigator.currentInstanceScreen?.questionIds)

        instance.set("members[i1].age", FormValue.Integer(41))
        instance.set("members[i2].age", FormValue.Integer(44))
        assertTrue(navigator.canFinalize, "an empty enumerator roster blocks nothing")

        instance.addInstance("visits")
        assertFalse(navigator.canFinalize, "an added row's required question blocks")
        assertEquals(listOf("visits[i3].note"), navigator.finalizationBlockers)
    }

    @Test
    fun `the op log rebuilds the rows an enumerator added, and the answers land on them`() {
        val db = DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema))
        val store = SubmissionStore(db, deviceIdOverride = "dev-test")
        val submissionId = store.createDraft("clinic", 1)

        val (_, first, _) = fresh()
        val added = first.addInstance("visits")
        assertEquals("i3", added, "the fixed list minted i1 and i2; the add mints i3")
        store.appendOp(submissionId, "clinic", 1, OpKind.REPEAT_ADD, path = "visits[$added]")
        store.appendOp(submissionId, "clinic", 1, OpKind.SET, path = "visits[$added].note",
            value = FormValue.Text("came for a check-up"))

        // A second open of the same submission: rows first, then answers.
        val (_, second, _) = fresh()
        replayInstanceOps(second, store.opsFor(submissionId))
        assertEquals(listOf("i3"), second.instances["visits"]?.toList())
        val stored = store.materialisedAnswers(submissionId).filterKeys { it in second.values }
        second.setMany(stored)
        assertEquals(FormValue.Text("came for a check-up"), second.values["visits[i3].note"])

        store.appendOp(submissionId, "clinic", 1, OpKind.REPEAT_DELETE, path = "visits[i3]")
        val (_, third, _) = fresh()
        replayInstanceOps(third, store.opsFor(submissionId))
        assertEquals(emptyList<String>(), third.instances["visits"].orEmpty().toList())
    }

    @Test
    fun `a row the engine cannot mint under its recorded id is refused, not misplaced`() {
        val db = DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema))
        val store = SubmissionStore(db, deviceIdOverride = "dev-test")
        val submissionId = store.createDraft("clinic", 1)
        store.appendOp(submissionId, "clinic", 1, OpKind.REPEAT_ADD, path = "visits[i9]")
        val (_, instance, _) = fresh()
        val refused = assertFailsWith<CompileException> {
            replayInstanceOps(instance, store.opsFor(submissionId))
        }
        assertTrue("i9" in refused.message.orEmpty())
    }
}
