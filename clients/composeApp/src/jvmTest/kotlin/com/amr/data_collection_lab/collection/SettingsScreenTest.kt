package com.amr.data_collection_lab.collection

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.runComposeUiTest
import kotlin.test.Test

/**
 * What the settings screen says, driven through a real composition.
 *
 * The three things this screen exists to answer are the three things a person
 * holding a phone that "is not working" needs, and every one of them fails
 * silently if the screen renders the wrong one: an unconfigured device that
 * looks configured, an empty form list that does not say whether a sync has
 * ever run, and a withdrawn version that looks current. None of those is a
 * wrong value — the state is right in each case — so nothing below the UI can
 * catch them. That is the gap docs/project-conventions.md describes under "Where the conformance
 * architecture stops protecting you", and this is the test that stands in it.
 *
 * On the JVM target, so this is the same skiko-backed implementation the
 * desktop client uses. Break 32 in docs/known-breaks.md.
 */
@OptIn(ExperimentalTestApi::class)
class SettingsScreenTest {

    private fun state(
        serverUrlDraft: String = "http://10.0.2.2:8000",
        serverUrlInEffect: String = "http://10.0.2.2:8000",
        isPlatformDefault: Boolean = true,
        urlError: String? = null,
        lastSyncAt: String? = null,
        lastSyncError: String? = null,
        connection: ConnectionUi? = null,
        forms: List<HeldFormUi> = emptyList(),
    ) = SettingsState(
        serverUrlDraft = serverUrlDraft,
        serverUrlInEffect = serverUrlInEffect,
        isPlatformDefault = isPlatformDefault,
        platformDefault = "http://10.0.2.2:8000",
        urlError = urlError,
        lastSyncAt = lastSyncAt,
        lastSyncError = lastSyncError,
        connection = connection,
        forms = forms,
        deviceId = "dev_test01",
        isLoading = false,
    )

    @Test
    fun theAddressInEffectIsOnTheScreen() = runComposeUiTest {
        // The point of the screen. Before it, the address a device used was a
        // compile-time constant and there was no way to read it off a phone.
        setContent { SettingsScreen(state(), onAction = {}) }

        onNodeWithText("http://10.0.2.2:8000").assertExists()
    }

    @Test
    fun aDeviceNobodyHasConfiguredSaysSo() = runComposeUiTest {
        // A phone still on the built-in address looks exactly like one somebody
        // set deliberately, and the two need different next steps.
        setContent { SettingsScreen(state(isPlatformDefault = true), onAction = {}) }

        onNodeWithText("No address has been set", substring = true).assertExists()
    }

    @Test
    fun aConfiguredDeviceDoesNotClaimToBeOnTheDefault() = runComposeUiTest {
        setContent {
            SettingsScreen(
                state(
                    serverUrlDraft = "http://192.168.1.20:8000",
                    serverUrlInEffect = "http://192.168.1.20:8000",
                    isPlatformDefault = false,
                ),
                onAction = {},
            )
        }

        onNodeWithText("No address has been set", substring = true).assertDoesNotExist()
        onNodeWithText("Reset").assertExists()
    }

    @Test
    fun saveIsOffUntilTheAddressActuallyChanges() = runComposeUiTest {
        // An enabled Save on an unchanged field invites a tap that does nothing
        // and reports nothing, which reads as the screen being broken.
        setContent { SettingsScreen(state(), onAction = {}) }

        onNodeWithText("Save").assertIsNotEnabled()
    }

    @Test
    fun saveTurnsOnOnceTheFieldDiffersFromWhatIsInEffect() = runComposeUiTest {
        setContent {
            SettingsScreen(
                state(serverUrlDraft = "http://192.168.1.20:8000"),
                onAction = {},
            )
        }

        onNodeWithText("Save").assertIsEnabled()
    }

    @Test
    fun aRefusedAddressShowsTheReasonAndNotJustAnErrorState() = runComposeUiTest {
        // `parseServerUrl` writes a sentence precisely so that the screen has
        // something to say. Rendering only a red border would throw it away.
        setContent {
            SettingsScreen(
                state(urlError = "Leave off the /api/v1 — the app adds it. Try http://host:8000"),
                onAction = {},
            )
        }

        onNodeWithText("Leave off the /api/v1", substring = true).assertExists()
    }

    @Test
    fun aNeverSyncedDeviceSaysNeverRatherThanShowingNothing() = runComposeUiTest {
        // A blank timestamp is read as "recently", which is the opposite of
        // the truth and sends somebody looking at the wrong thing.
        setContent { SettingsScreen(state(lastSyncAt = null), onAction = {}) }

        onNodeWithText("never completed a sync", substring = true).assertExists()
    }

    @Test
    fun aFailedSyncShowsTheWholeSentence() = runComposeUiTest {
        // SyncFailure's whole job is to produce something actionable; a screen
        // that truncates it to "sync failed" undoes that.
        val reason = "Nothing is listening at http://192.168.1.20:8000. The address was " +
            "reached, so this is usually the server not running."
        setContent { SettingsScreen(state(lastSyncError = reason), onAction = {}) }

        onNodeWithText("Nothing is listening at http://192.168.1.20:8000", substring = true)
            .assertExists()
    }

    @Test
    fun anEmptyFormListDistinguishesNeverSyncedFromNothingDeployed() = runComposeUiTest {
        // The two have completely different fixes — press Sync, versus go and
        // deploy the form on the server — and both are an empty list.
        setContent { SettingsScreen(state(lastSyncAt = null), onAction = {}) }
        onNodeWithText("Forms arrive on the first successful sync", substring = true).assertExists()

        setContent { SettingsScreen(state(lastSyncAt = "2026-09-02 09:14"), onAction = {}) }
        onNodeWithText("no form deployed", substring = true).assertExists()
    }

    @Test
    fun everyHeldVersionIsListed_notOnlyTheStartableOnes() = runComposeUiTest {
        // A device keeps every version a local submission still refers to
        // (Form IR §9). Listing only the startable ones would report a form as
        // absent while a draft was open against it.
        setContent {
            SettingsScreen(
                state(
                    lastSyncAt = "2026-09-02 09:14",
                    forms = listOf(
                        HeldFormUi("Household Survey", "household_survey", 2, true, "2026-09-02"),
                        HeldFormUi("Household Survey", "household_survey", 1, false, "2026-08-28"),
                    ),
                ),
                onAction = {},
            )
        }

        onNodeWithText("household_survey · v2", substring = true).assertExists()
        onNodeWithText("household_survey · v1", substring = true).assertExists()
    }

    @Test
    fun aWithdrawnVersionIsMarkedAndACurrentOneIsNot() = runComposeUiTest {
        setContent {
            SettingsScreen(
                state(
                    lastSyncAt = "2026-09-02 09:14",
                    forms = listOf(
                        HeldFormUi("Household Survey", "household_survey", 2, true, "2026-09-02"),
                    ),
                ),
                onAction = {},
            )
        }
        onNodeWithText("Withdrawn").assertDoesNotExist()

        setContent {
            SettingsScreen(
                state(
                    lastSyncAt = "2026-09-02 09:14",
                    forms = listOf(
                        HeldFormUi("Household Survey", "household_survey", 1, false, "2026-08-28"),
                    ),
                ),
                onAction = {},
            )
        }
        onNodeWithText("Withdrawn").assertExists()
    }

    @Test
    fun aSuccessfulConnectionCheckNamesTheEnvironment() = runComposeUiTest {
        // "Connected" alone is a reassurance that hides the failure worth
        // catching: a phone on staging syncs perfectly and files a morning's
        // interviews where nobody will look for them.
        setContent {
            SettingsScreen(
                state(
                    connection = ConnectionUi.Reached("http://192.168.1.20:8000", "staging"),
                ),
                onAction = {},
            )
        }

        onNodeWithText("staging", substring = true).assertExists()
    }

    @Test
    fun aFailedConnectionCheckShowsTheReasonAndTheUrl() = runComposeUiTest {
        setContent {
            SettingsScreen(
                state(
                    connection = ConnectionUi.Failed(
                        "http://10.0.2.2:8000",
                        "Nothing is listening at http://10.0.2.2:8000. Note: 10.0.2.2 only " +
                            "works in the Android emulator.",
                    ),
                ),
                onAction = {},
            )
        }

        onNodeWithText("10.0.2.2 only works in the Android emulator", substring = true)
            .assertExists()
    }
}
