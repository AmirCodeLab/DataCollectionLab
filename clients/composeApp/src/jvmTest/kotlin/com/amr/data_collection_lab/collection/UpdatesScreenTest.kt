package com.amr.data_collection_lab.collection

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.runComposeUiTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * What a person sees before they tap, which is this item's whole value.
 *
 * Item 4 is not "three functions instead of one". It is a person on a village
 * connection being able to tell, without spending anything, which of these
 * they are agreeing to — and being unable to mistake a 38,000-row list for
 * their morning's interviews.
 */
@OptIn(ExperimentalTestApi::class)
class UpdatesScreenTest {

    private val waitingLists = listOf(
        ListUpdateUi(
            datasetKey = "villages",
            statusLine = "villages v8 — not downloaded",
            costLine = "Update from v7 — only the rows that changed. " +
                "The whole list is about 11.3 MB.",
            partial = false,
        ),
        ListUpdateUi(
            datasetKey = "health_facilities",
            statusLine = "health_facilities v2 — 412 of 1,900 rows",
            costLine = "Full download — about 240 KB.",
            partial = true,
        ),
    )

    @Test
    fun theCostIsOnTheScreenBesideTheButtonThatSpendsIt() = runComposeUiTest {
        setContent {
            UpdatesScreen(
                state = UpdatesState(isLoading = false, lists = waitingLists),
                onAction = {},
            )
        }

        // Delta or full download, and how much: the two sentences that decide
        // it, both present before anything is tapped.
        onNodeWithText(
            "Update from v7 — only the rows that changed. The whole list is about 11.3 MB.",
        ).assertIsDisplayed()
        onNodeWithText("Full download — about 240 KB.").assertIsDisplayed()

        // And the button beside each says which of the two it is doing.
        onNodeWithText("Download").assertIsDisplayed()
        onNodeWithText("Resume").assertIsDisplayed()
    }

    @Test
    fun eachListIsItsOwnDecision() = runComposeUiTest {
        val asked = mutableListOf<String>()
        setContent {
            UpdatesScreen(
                state = UpdatesState(isLoading = false, lists = waitingLists),
                onAction = { action ->
                    if (action is UpdatesAction.OnUpdateList) asked += action.datasetKey
                },
            )
        }

        onNodeWithText("Download").performClick()

        // Villages only. Taking the village list today and the facility list
        // tomorrow is the choice this screen exists to offer.
        assertEquals(listOf("villages"), asked)
    }

    @Test
    fun theScreenSaysWorkIsNotHere() = runComposeUiTest {
        setContent {
            UpdatesScreen(
                state = UpdatesState(isLoading = false, lists = waitingLists),
                onAction = {},
            )
        }

        onNodeWithText(
            "Your interviews are sent from the Submissions screen and never wait for anything here.",
        ).assertIsDisplayed()
    }

    @Test
    fun aScopeNeverCheckedSaysSoRatherThanLookingUpToDate() = runComposeUiTest {
        setContent {
            UpdatesScreen(
                state = UpdatesState(isLoading = false, listsStatus = "Not checked yet"),
                onAction = {},
            )
        }

        onNodeWithText("Not checked yet").assertIsDisplayed()
        onNodeWithText("Every list your forms use is on this device.").assertIsDisplayed()
    }

}

/**
 * The submissions screen, where the hierarchy lives.
 *
 * A1 says the work sync is never deferrable. A screen with three equal buttons
 * says the opposite, and an enumerator reading it as "I'll do that one later"
 * about their morning's interviews is the failure. So the other two actions
 * are not on this screen at all — the link goes to them, and nothing here
 * downloads anything.
 */
@OptIn(ExperimentalTestApi::class)
class SubmissionListHierarchyTest {

    private fun state(
        updatesWaiting: String? = "Updates waiting: 1 form and 1 list (about 11.3 MB)",
        emptyState: EmptyState? = null,
    ) = SubmissionListState(
        isLoading = false,
        submissions = listOf(
            SubmissionUi("01A", "Household Survey", 2, "2026-09-10 10:12", false, 3),
        ),
        updatesWaiting = updatesWaiting,
        emptyState = emptyState,
    )

    @Test
    fun theOnlyActionOnThisScreenIsTheOneThatSendsTheirWork() = runComposeUiTest {
        setContent { SubmissionListScreen(state = state(), onAction = {}) }

        onNodeWithText("Sync work").assertIsDisplayed()
        // The expensive two are one tap away, not beside it. If either label
        // ever appears here, they have become peers of sending the answers.
        onNodeWithText("Update forms").assertDoesNotExist()
        onNodeWithText("Download").assertDoesNotExist()
    }

    @Test
    fun theUpdatesLineNavigatesAndSyncsNothing() = runComposeUiTest {
        var navigated = 0
        val actions = mutableListOf<SubmissionListAction>()
        setContent {
            SubmissionListScreen(
                state = state(),
                onAction = { actions += it },
                onNavigateToUpdates = { navigated += 1 },
            )
        }

        onNodeWithText("Updates waiting: 1 form and 1 list (about 11.3 MB)").performClick()

        assertEquals(1, navigated)
        assertTrue(actions.isEmpty(), "the updates link performed a sync: $actions")
    }

    @Test
    fun withNothingWaitingThereIsNoUpdatesLineAtAll() = runComposeUiTest {
        setContent { SubmissionListScreen(state = state(updatesWaiting = null), onAction = {}) }

        onNodeWithText("Sync work").assertIsDisplayed()
        onNodeWithText("Updates waiting: 1 form and 1 list (about 11.3 MB)").assertDoesNotExist()
    }

    @Test
    fun anEmptyScreenThatIsSomebodyElsesJobDoesNotOfferAButton() = runComposeUiTest {
        setContent {
            SubmissionListScreen(
                state = SubmissionListState(
                    isLoading = false,
                    emptyState = emptyStateFor(
                        startable = 1,
                        waitingForms = 0,
                        cases = 0,
                        assignmentsAnswered = true,
                    ),
                ),
                onAction = {},
            )
        }

        onNodeWithText(
            "You hold no cases. A supervisor assigns them; they will appear here after a sync.",
        ).assertIsDisplayed()
        onNodeWithText("Open Updates").assertDoesNotExist()
    }

    @Test
    fun anEmptyScreenTheyCanFixThemselvesOffersTheWayToFixIt() = runComposeUiTest {
        var navigated = 0
        setContent {
            SubmissionListScreen(
                state = SubmissionListState(
                    isLoading = false,
                    emptyState = emptyStateFor(
                        startable = 0,
                        waitingForms = 2,
                        cases = 0,
                        assignmentsAnswered = false,
                    ),
                ),
                onAction = {},
                onNavigateToUpdates = { navigated += 1 },
            )
        }

        onNodeWithText("2 forms are deployed to this device and not downloaded yet.")
            .assertIsDisplayed()
        onNodeWithText("Open Updates").performClick()
        assertEquals(1, navigated)
    }
}

/**
 * The four empty states, as a decision rather than as a rendering.
 *
 * One sentence used to cover all four, and two of them are not the
 * enumerator's to fix. Which sentence appears is the whole content of this
 * rule, so it is tested as a rule.
 */
class EmptyStateTest {

    @Test
    fun `forms deployed and not downloaded is theirs to fix`() {
        val state = emptyStateFor(startable = 0, waitingForms = 1, cases = 0, assignmentsAnswered = false)
        assertEquals("One form is deployed to this device and not downloaded yet.", state.text)
        assertTrue(state.opensUpdates)
    }

    @Test
    fun `no form deployed at all is not theirs to fix`() {
        val state = emptyStateFor(startable = 0, waitingForms = 0, cases = 0, assignmentsAnswered = false)
        assertTrue("programme manager" in state.text, state.text)
        assertTrue(!state.opensUpdates, "offered an action for something they cannot do")
    }

    @Test
    fun `no cases is not theirs to fix, and is only said once the server has answered`() {
        val answered = emptyStateFor(startable = 1, waitingForms = 0, cases = 0, assignmentsAnswered = true)
        assertTrue("supervisor assigns them" in answered.text, answered.text)
        assertTrue(!answered.opensUpdates)

        // Never asked is not the same as answered "none" — the same
        // null-versus-empty distinction the manifests turn on. Saying "you
        // hold no cases" to a device that has not synced would be a guess.
        val neverAsked = emptyStateFor(startable = 1, waitingForms = 0, cases = 0, assignmentsAnswered = false)
        assertEquals("No submissions yet. Start one with “New submission”.", neverAsked.text)
    }
}
