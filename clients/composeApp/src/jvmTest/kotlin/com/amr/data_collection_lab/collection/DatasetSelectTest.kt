package com.amr.data_collection_lab.collection

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.runComposeUiTest
import kotlin.test.Test

/**
 * A dataset-backed select reaches an enumerator, and a long one is searchable.
 *
 * Above the line the conformance vectors reach (docs/project-conventions.md), and this is the
 * layer that made `choiceSources` refuse `dataset` for two whole parts of item
 * 4: the engine resolved the list, the store held it, the server delivered it,
 * every vector passed — and `CollectionViewModel` read `choices.items`, which a
 * dataset-backed list has none of, so the question arrived with nothing under
 * its label. Nothing below this file could have seen that.
 *
 * The second test is about size rather than correctness, and size is what makes
 * this feature different from every other answer widget. A district in the UCL
 * data holds 229 villages out of 37,852; every other list in a form is twenty
 * options composed eagerly in a `Column`, and doing that with 229 is a visible
 * pause on a handset.
 */
@OptIn(ExperimentalTestApi::class)
class DatasetSelectTest {

    private fun state(choices: List<ChoiceUi>, selected: String? = null) = CollectionState(
        isLoading = false,
        formTitle = "UCL Biomass",
        language = "en",
        languages = listOf("en"),
        questions = listOf(
            QuestionUi(
                path = "village",
                dataType = "select_one",
                label = "Village",
                hint = null,
                required = true,
                readOnly = false,
                displayText = "",
                selectedValue = selected,
                choices = choices,
                dateIso = null,
                error = null,
            ),
        ),
    )

    private fun villages(n: Int) =
        (1..n).map { ChoiceUi("V${it.toString().padStart(6, '0')}", "Village $it") }

    @Test
    fun `a short list is rendered as options an enumerator can tap`() {
        runComposeUiTest {
            setContent { CollectionScreen(state = villages(3).let(::state), onAction = {}) }
            onNodeWithText("Village 1").assertIsDisplayed()
            onNodeWithText("Village 3").assertIsDisplayed()
        }
    }

    @Test
    fun `a long list is searched, and says how many there are`() {
        runComposeUiTest {
            setContent { CollectionScreen(state = villages(229).let(::state), onAction = {}) }

            // The count is the point: a dataset list has already been narrowed
            // by the form's filter, and this is how an enumerator knows it was.
            // Asserted as a substring because the number carries the bidi
            // isolates §7.1 uses, for the reason §7.1 gives.
            onNodeWithText("229", substring = true).assertIsDisplayed()

            // 229 eager composables is what this replaces; only what fits is
            // composed, so the last village is not on screen until searched for.
            onNodeWithText("Village 1").assertIsDisplayed()
            onNodeWithText("Search", substring = true).performTextInput("Village 200")
            // Two nodes now hold that text — the search box carries what was
            // typed, and the option carries its label — so both are asked for
            // and the second one is the list having narrowed.
            onAllNodesWithText("Village 200").assertCountEquals(2)
        }
    }

    @Test
    fun `an empty result says so rather than showing nothing`() {
        // The distinction §3.2 spends its length on: an enumerator has to be
        // able to tell "I typed badly" from "the reference data has not
        // arrived", and a blank space says neither.
        runComposeUiTest {
            setContent { CollectionScreen(state = villages(229).let(::state), onAction = {}) }
            onNodeWithText("Search", substring = true).performTextInput("Nowhere")
            onNodeWithText("No option matches", substring = true).assertIsDisplayed()
        }
    }

    @Test
    fun `the threshold sits below the smallest real cascade`() {
        // Not a round number for looks: a UCL district holds 229 villages, so
        // the case this feature exists for must take the searchable path — and
        // the twenty-option lists a form is mostly made of must not, because a
        // search box over five options is worse than five options.
        runComposeUiTest {
            setContent { CollectionScreen(state = villages(21).let(::state), onAction = {}) }
            onNodeWithText("21", substring = true).assertIsDisplayed()
        }
        runComposeUiTest {
            setContent { CollectionScreen(state = villages(20).let(::state), onAction = {}) }
            onAllNodesWithText("Search", substring = true).assertCountEquals(0)
        }
    }
}
