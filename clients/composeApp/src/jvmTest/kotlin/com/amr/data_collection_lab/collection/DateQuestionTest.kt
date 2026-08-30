package com.amr.data_collection_lab.collection

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.click
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performMouseInput
import androidx.compose.ui.test.runComposeUiTest
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * The date question's picker opens and returns a date.
 *
 * It is here because the widget is a transparent click target laid over a
 * read-only text field, and nothing else in the repository watches that: the
 * conformance vectors cannot see a composable, and a click that lands on the
 * field underneath instead of the overlay would look exactly like a picker that
 * refuses to open — which is what defect 1 reported on desktop. These run on the
 * JVM target, so they exercise the same skiko-backed implementation the desktop
 * client uses rather than the Android one.
 *
 * Mouse and touch are separate cases deliberately. Desktop delivers a mouse
 * click and the handset a touch, and hit testing is the thing under test.
 */
@OptIn(ExperimentalTestApi::class)
class DateQuestionTest {

    private fun stateWith(dateIso: String?) = CollectionState(
        isLoading = false,
        formTitle = "Household Survey",
        language = "en",
        languages = listOf("en"),
        questions = listOf(
            QuestionUi(
                path = "interview_date",
                dataType = "date",
                label = "Interview date",
                hint = null,
                required = true,
                readOnly = false,
                displayText = "",
                selectedValue = null,
                choices = emptyList(),
                dateIso = dateIso,
                error = null,
            ),
        ),
    )

    @Test
    fun aMouseClickOnTheFieldOpensThePicker() = runComposeUiTest {
        setContent { CollectionScreen(state = stateWith(null), onAction = {}) }

        onNodeWithText("Pick a date").performMouseInput { click() }
        waitForIdle()

        // The dialog's own buttons: present only once the picker is composed.
        onNodeWithText("OK").assertExists()
        onNodeWithText("Clear").assertExists()
    }

    @Test
    fun aTouchOnTheFieldOpensThePicker() = runComposeUiTest {
        setContent { CollectionScreen(state = stateWith(null), onAction = {}) }

        onNodeWithText("Pick a date").performClick()
        waitForIdle()

        onNodeWithText("OK").assertExists()
    }

    /**
     * Confirming returns the date that was already answered, which is the whole
     * round trip: ISO -> epoch millis -> the picker -> epoch millis -> ISO.
     */
    @Test
    fun confirmingThePickerEmitsTheSelectedDate() = runComposeUiTest {
        val actions = mutableListOf<CollectionAction>()
        setContent { CollectionScreen(state = stateWith("2026-08-15"), onAction = { actions += it }) }

        onNodeWithText("2026-08-15").performMouseInput { click() }
        waitForIdle()
        onNodeWithText("OK").performMouseInput { click() }
        waitForIdle()

        assertEquals<List<CollectionAction>>(
            listOf(CollectionAction.OnDateSelect("interview_date", "2026-08-15")),
            actions,
        )
    }

    @Test
    fun clearingThePickerErasesTheAnswer() = runComposeUiTest {
        val actions = mutableListOf<CollectionAction>()
        setContent { CollectionScreen(state = stateWith("2026-08-15"), onAction = { actions += it }) }

        onNodeWithText("2026-08-15").performMouseInput { click() }
        waitForIdle()
        onNodeWithText("Clear").performMouseInput { click() }
        waitForIdle()

        assertEquals<List<CollectionAction>>(
            listOf(CollectionAction.OnDateSelect("interview_date", null)),
            actions,
        )
    }

    /**
     * A finalized submission disables every question, and the date field must
     * not open a picker behind that — the overlay is what would leak, since it
     * is a separate click target from the field it covers.
     */
    @Test
    fun aDisabledFieldDoesNotOpenThePicker() = runComposeUiTest {
        setContent {
            CollectionScreen(state = stateWith(null).copy(finalized = true), onAction = {})
        }

        onNodeWithText("Pick a date").performMouseInput { click() }
        waitForIdle()

        onNodeWithText("OK").assertDoesNotExist()
    }
}
