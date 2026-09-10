package com.amr.data_collection_lab.collection

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.runComposeUiTest
import com.dcp.core.sync.PinnedList
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
            isUpdate = true,
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

        // And the button beside each says which of the two it is doing. A card
        // reading "Update from v7" over a button reading "Download" asks the
        // person to reconcile two claims about one tap.
        onNodeWithText("Update").assertIsDisplayed()
        onNodeWithText("Resume").assertIsDisplayed()
        onNodeWithText("Download").assertDoesNotExist()
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

        onNodeWithText("Update").performClick()

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
        onNodeWithText("Update").assertDoesNotExist()
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
                        manifestsAnswered = true,
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
                        manifestsAnswered = true,
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
        val state = emptyStateFor(0, 1, cases = 0, assignmentsAnswered = false, manifestsAnswered = true)
        assertEquals("One form is deployed to this device and not downloaded yet.", state.text)
        assertTrue(state.opensUpdates)
    }

    @Test
    fun `no form deployed at all is not theirs to fix`() {
        val state = emptyStateFor(0, 0, cases = 0, assignmentsAnswered = false, manifestsAnswered = true)
        assertTrue("programme manager" in state.text, state.text)
        assertTrue(!state.opensUpdates, "offered an action for something they cannot do")
    }

    @Test
    fun `a device that has never synced says so rather than speaking for the server`() {
        // Found on a phone: a fresh install said "no form has been deployed to
        // this device" before it had ever reached a server. It could not know
        // that. Never asked is not answered "none".
        val state = emptyStateFor(0, 0, cases = 0, assignmentsAnswered = false, manifestsAnswered = false)
        assertTrue("Nothing has been synced to this device yet" in state.text, state.text)
        assertTrue("programme manager" !in state.text, state.text)
    }

    @Test
    fun `no cases is not theirs to fix, and is only said once the server has answered`() {
        val answered = emptyStateFor(1, 0, cases = 0, assignmentsAnswered = true, manifestsAnswered = true)
        assertTrue("supervisor assigns them" in answered.text, answered.text)
        assertTrue(!answered.opensUpdates)

        // Never asked is not the same as answered "none" — the same
        // null-versus-empty distinction the manifests turn on. Saying "you
        // hold no cases" to a device that has not synced would be a guess.
        val neverAsked = emptyStateFor(1, 0, cases = 0, assignmentsAnswered = false, manifestsAnswered = true)
        assertEquals("No submissions yet. Start one with “New submission”.", neverAsked.text)
    }
}

/**
 * The refusal, in both languages, with the Latin runs isolated.
 *
 * Run in Arabic on a phone, the English sentence put its full stop at the far
 * left of the line: an LTR sentence inside an RTL paragraph, with the neutral
 * at the end taken by the paragraph direction. That is the same shape as the
 * "25 / 5" progress defect, and the same fix the engine already applies to
 * every interpolated label — U+2068 … U+2069 around each Latin run
 * (`Interpolation.isolate`, break 55).
 */
class ReferenceDataRefusalTextTest {

    private fun list(key: String, version: Int?, held: Long, total: Int?) = PinnedList(
        datasetKey = key,
        datasetVersionId = "dv-$key-$version",
        version = version,
        rowCount = total,
        complete = false,
        rowsHeld = held,
    )

    @Test
    fun `English names the list, the shortfall and the action`() {
        val text = UiStrings.cannotFinalizeReferenceData(
            "en",
            listOf(list("villages", 8, held = 0, total = 38_000)),
        )
        assertEquals("Cannot finalise: villages v8 not downloaded — tap Reference data.", text)
    }

    @Test
    fun `Arabic is Arabic, not the English sentence with an Arabic frame`() {
        val text = UiStrings.cannotFinalizeReferenceData(
            "ar",
            listOf(list("villages", 8, held = 0, total = 38_000)),
        )
        assertTrue(text.startsWith("لا يمكن الإنهاء:"), text)
        assertTrue("not downloaded" !in text, "English shortfall leaked into the Arabic sentence")
        assertTrue("لم يتم تنزيلها" in text, text)
    }

    @Test
    fun `every Latin run inside the Arabic sentence is isolated`() {
        val text = UiStrings.cannotFinalizeReferenceData(
            "ar",
            listOf(list("villages", 8, held = 12_400, total = 38_000)),
        )
        // The list name and both numbers: each wrapped, each balanced.
        assertEquals(3, text.count { it == '⁨' }, text)
        assertEquals(3, text.count { it == '⁩' }, text)
        assertTrue("⁨villages v8⁩" in text, text)
    }

    @Test
    fun `no lists is no sentence`() {
        assertEquals("", UiStrings.cannotFinalizeReferenceData("ar", emptyList()))
        assertEquals("", UiStrings.cannotFinalizeReferenceData("en", emptyList()))
    }
}
