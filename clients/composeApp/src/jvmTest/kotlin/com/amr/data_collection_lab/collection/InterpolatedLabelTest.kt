package com.amr.data_collection_lab.collection

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.runComposeUiTest
import com.dcp.form.CompiledForm
import com.dcp.form.FormInstance
import com.dcp.form.FormIr
import com.dcp.form.FormValue
import com.dcp.form.Interpolation
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * A label that inserts an answer reaches the screen with the answer in it.
 *
 * Above the line the conformance vectors reach (docs/project-conventions.md): they prove the
 * engine renders `Stems of tree with tag number ⁨42⁩`, and say nothing about
 * whether anything puts that string in front of an enumerator. The
 * `CollectionViewModel` used to read `node.label` straight off the document,
 * which after §7.1 would have shown a literal `{0}` — a form that passes every
 * vector and displays a placeholder.
 *
 * The isolates are asserted here as well as in `label-004`, and deliberately:
 * they are two invisible codepoints, and a client that stripped them "for
 * display" would undo the bidi fix at the last possible moment, where no engine
 * test could see it.
 */
@OptIn(ExperimentalTestApi::class)
class InterpolatedLabelTest {

    private val ir = """
        {"irVersion":"0.1","formId":"tagged","version":1,
         "title":{"en":"Tagged"},"defaultLanguage":"en","languages":["en"],
         "children":[
          {"type":"question","id":"tag","dataType":"integer","label":{"en":"Tag"}},
          {"type":"question","id":"note","dataType":"note",
           "label":{"en":"Stems of tree with tag number {0}"},
           "labelArgs":[{"op":"ref","path":"tag"}]}]}
    """.trimIndent()

    private fun instanceWith(tag: Long?): FormInstance {
        val instance = FormInstance(CompiledForm(FormIr.parse(ir)), today = "2026-09-03")
        if (tag != null) instance.set("tag", FormValue.Integer(tag))
        return instance
    }

    @Test
    fun `the engine renders the answer into the label, isolated`() {
        val rendered = instanceWith(42).renderedLabel("note", "en")
        assertEquals(
            "Stems of tree with tag number " +
                "${Interpolation.FIRST_STRONG_ISOLATE}42${Interpolation.POP_DIRECTIONAL_ISOLATE}",
            rendered,
        )
    }

    @Test
    fun `the screen shows the rendered label and not the template`() {
        val instance = instanceWith(42)
        val shown = instance.renderedLabel("note", "en")!!
        runComposeUiTest {
            setContent {
                CollectionScreen(
                    state = CollectionState(
                        isLoading = false,
                        formTitle = "Tagged",
                        language = "en",
                        languages = listOf("en"),
                        questions = listOf(
                            QuestionUi(
                                path = "note",
                                dataType = "note",
                                label = shown,
                                hint = null,
                                required = false,
                                readOnly = true,
                                displayText = "",
                                selectedValue = null,
                                choices = emptyList(),
                                dateIso = null,
                                error = null,
                            ),
                        ),
                    ),
                    onAction = {},
                )
            }
            onNodeWithText(shown, substring = true).assertExists()
        }
        assertTrue(
            Interpolation.FIRST_STRONG_ISOLATE in shown,
            "the isolate must survive all the way to the composable — stripping it " +
                "for display undoes the bidi fix where no engine test can see it",
        )
        assertTrue("{0}" !in shown, "the template must not reach the screen")
    }

    @Test
    fun `an unanswered insert leaves a gap rather than a placeholder`() {
        // §7.1: the empty string, the same rule `concat` has. Which glyph a gap
        // should show is a translation decision, and `coalesce` is how an author
        // makes it.
        assertEquals(
            "Stems of tree with tag number ",
            instanceWith(null).renderedLabel("note", "en"),
        )
    }
}
