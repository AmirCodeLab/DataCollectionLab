package com.amr.data_collection_lab.collection

import com.dcp.form.CompiledForm
import com.dcp.form.FormInstance
import com.dcp.form.FormIr
import com.dcp.form.FormValue
import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The collection surface asks for a `rows` list **by path**, not by field id.
 *
 * Above the line the conformance vectors reach (docs/project-conventions.md).
 * `repeat-017` proves the engine hands out a different list per instance; it
 * says nothing about whether the thing drawing the screen asks for the right
 * one. Asking by field id compiles, runs, renders a plausible list of names —
 * and on the second member's row it is the **first** member's list: her own
 * name offered as her own mother, and his missing. Nothing below this file
 * could see that, and neither could anybody looking at the screen unless they
 * knew the roster.
 *
 * A source check rather than a ViewModel test, for the reason
 * `FinalisationGateTest` gives: `CollectionViewModel` needs a lifecycle, a
 * store and a catalog, and nothing in this module drives one. The engine half
 * below is what makes the source check mean something — it pins what the two
 * calls actually differ by, so a reader can see that the line being asserted
 * is load-bearing rather than stylistic.
 */
class RowChoiceScopeTest {

    private val viewModel: File by lazy {
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null) {
            val candidate = dir.resolve(
                "clients/composeApp/src/commonMain/kotlin/com/amr/data_collection_lab/" +
                    "collection/CollectionViewModel.kt"
            )
            if (candidate.isFile) return@lazy candidate
            dir = dir.parentFile
        }
        error("CollectionViewModel.kt not found above ${System.getProperty("user.dir")}")
    }

    @Test
    fun `questionUi resolves choices from the path it was given`() {
        val text = viewModel.readText()
        assertTrue(
            "instance.choices(path)" in text,
            "the choice list must be resolved from the question's path: a rows list is a " +
                "function of (field, instance), so by field id every row gets the first " +
                "row's list (Form IR §3.3)",
        )
        assertTrue(
            "instance.choices(node.id)" !in text,
            "asking by field id is the defect this test exists for",
        )
    }

    /** MICS6 HL14: the roster, the question on the member's own row. */
    private val ir = """
        {"irVersion":"0.1","formId":"hl","version":1,
         "title":{"en":"HL"},"defaultLanguage":"en","languages":["en"],
         "children":[
           {"type":"repeat","id":"members","label":{"en":"Members"},
            "summaryLabel":{"en":"{0}"},
            "summaryLabelArgs":[{"op":"ref","path":"name"}],
            "allowAdd":true,"allowDelete":true,
            "children":[
              {"type":"question","id":"name","dataType":"text","label":{"en":"Name"}},
              {"type":"question","id":"mother_line","dataType":"select_one",
               "label":{"en":"Record the line number of mother"},
               "choices":{"kind":"rows","repeat":"members","excludeSelf":true}}]}]}
    """.trimIndent()

    @Test
    fun `by path each row offers everybody but the person on it`() {
        val instance = FormInstance(CompiledForm(FormIr.parse(ir)), today = "2026-09-14")
        val ids = listOf("Zubaida", "Bilal", "Amina").map { name ->
            val id = instance.addInstance("members")
            instance.set("members[$id].name", FormValue.Text(name))
            id
        }

        assertEquals(
            listOf(ids[1], ids[2]),
            instance.choices("members[${ids[0]}].mother_line").map { it.value },
        )
        assertEquals(
            listOf(ids[0], ids[2]),
            instance.choices("members[${ids[1]}].mother_line").map { it.value },
        )

        // And the failure the source check is about, stated as a value: asking
        // by field id gives every row the first row's list, which on the second
        // member's row offers her to herself.
        val byFieldId = instance.choices("mother_line").map { it.value }
        assertEquals(listOf(ids[1], ids[2]), byFieldId)
        assertTrue(
            ids[1] in byFieldId,
            "the first row's list contains the second member — which is why handing it " +
                "to her is the wrong list and not merely a stale one",
        )
    }
}
