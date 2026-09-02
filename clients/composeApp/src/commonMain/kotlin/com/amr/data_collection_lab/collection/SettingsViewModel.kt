package com.amr.data_collection_lab.collection

import androidx.compose.runtime.Stable
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.dcp.core.sync.ConnectionCheck
import com.dcp.core.sync.ServerConfig
import com.dcp.core.sync.ServerUrlResult
import com.dcp.core.sync.SubmissionStore
import com.dcp.core.sync.SyncClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.receiveAsFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** One form version on this device, as a row on the settings screen. */
data class HeldFormUi(
    val title: String,
    val formId: String,
    val version: Int,
    /** False: withdrawn on the server, kept because a submission needs it. */
    val deployed: Boolean,
    /** When this device fetched it — "is this form actually new?". */
    val fetchedAt: String,
)

/** The outcome of the last "Test connection", ready to render. */
sealed interface ConnectionUi {
    data class Reached(val url: String, val environment: String) : ConnectionUi
    data class Failed(val url: String, val reason: String) : ConnectionUi
}

@Stable
data class SettingsState(
    /** What is in the text field — not what is in effect until it is saved. */
    val serverUrlDraft: String = "",
    /** The address syncs actually use. */
    val serverUrlInEffect: String = "",
    /** True while no address has been saved and the built-in one stands. */
    val isPlatformDefault: Boolean = true,
    val platformDefault: String = "",
    /** Why the draft was refused, from `parseServerUrl`. Shown under the field. */
    val urlError: String? = null,
    /** Confirmation that a save landed — an address changing needs saying. */
    val savedNotice: String? = null,
    val isTestingConnection: Boolean = false,
    val connection: ConnectionUi? = null,
    val deviceId: String = "",
    val lastSyncAt: String? = null,
    val lastSyncError: String? = null,
    val pendingOps: Long = 0,
    val forms: List<HeldFormUi> = emptyList(),
    val isLoading: Boolean = true,
) {
    /** Nothing to save while the field matches what is already in effect. */
    val canSave: Boolean get() = serverUrlDraft.trim() != serverUrlInEffect
}

sealed interface SettingsAction {
    data class OnServerUrlChanged(val value: String) : SettingsAction
    data object OnSaveServerUrl : SettingsAction
    data object OnResetToDefault : SettingsAction
    data object OnTestConnection : SettingsAction
    data object OnBack : SettingsAction
}

sealed interface SettingsEvent {
    data object NavigateBack : SettingsEvent
}

/**
 * The settings screen: which server this device talks to, how the last sync
 * went, and which forms are actually on the phone.
 *
 * ## Why those three things are one screen
 *
 * They are one question asked three ways. "Why has this phone got no forms?"
 * is answered by the address (wrong server), by the last sync (never ran, or
 * failed) or by the form list (synced fine, this environment deploys nothing) —
 * and until now a person in a field office could see none of the three. The
 * screen exists so that the next question after "it isn't working" has somewhere
 * to be answered, rather than requiring a rebuild with a different constant in
 * it.
 *
 * ## What is deliberately not here
 *
 * No sync button. Sync belongs to the submission list, where the outbox is, and
 * a second one here would make "did it sync?" depend on which screen you were
 * standing on. [SettingsAction.OnTestConnection] is not a sync: it asks
 * `/health` and moves no data, which is what makes it safe to press against an
 * address you are not sure about yet.
 *
 * Kotlin-only, above the line the conformance vectors reach (docs/project-conventions.md, "Where
 * the conformance architecture stops protecting you"). `SettingsScreenTest` is
 * what watches it.
 */
class SettingsViewModel(
    private val serverConfig: ServerConfig,
    private val store: SubmissionStore,
    private val catalog: FormCatalog,
    private val syncClient: SyncClient,
) : ViewModel() {

    private val _state = MutableStateFlow(SettingsState())
    val state = _state.asStateFlow()

    private val _events = Channel<SettingsEvent>()
    val events = _events.receiveAsFlow()

    init {
        viewModelScope.launch {
            val inEffect = withContext(Dispatchers.Default) { serverConfig.baseUrl() }
            val isDefault = withContext(Dispatchers.Default) { serverConfig.isPlatformDefault }
            _state.update {
                it.copy(
                    serverUrlDraft = inEffect,
                    serverUrlInEffect = inEffect,
                    isPlatformDefault = isDefault,
                    platformDefault = serverConfig.platformDefault,
                    deviceId = store.deviceId,
                    isLoading = false,
                )
            }
        }
        viewModelScope.launch {
            // Observed, not read once. A list read at construction is wrong at
            // exactly the moment it matters — a sync has just delivered a form
            // and the screen still reports none, contradicting the thing it was
            // opened to explain. Found on a device, with the form already in
            // the database underneath the screen saying there wasn't one.
            catalog.observeHeld().collect { held ->
                _state.update { state ->
                    state.copy(
                        forms = held.map {
                            HeldFormUi(
                                title = it.title,
                                formId = it.formId,
                                version = it.version,
                                deployed = it.deployed,
                                fetchedAt = it.fetchedAt.take(16).replace("T", " "),
                            )
                        },
                    )
                }
            }
        }
        viewModelScope.launch {
            store.observeSyncStatus().collect { status ->
                _state.update {
                    it.copy(
                        lastSyncAt = status.lastSyncAt?.take(16)?.replace("T", " "),
                        lastSyncError = status.lastError,
                    )
                }
            }
        }
        viewModelScope.launch {
            store.observeSubmissions().collect { rows ->
                _state.update { it.copy(pendingOps = rows.sumOf { row -> row.pendingOps }) }
            }
        }
    }

    fun onAction(action: SettingsAction) {
        when (action) {
            is SettingsAction.OnServerUrlChanged -> _state.update {
                // Clearing the error and the notice as soon as a key is pressed:
                // an error about the previous text sitting under new text is
                // read as being about the new text.
                it.copy(serverUrlDraft = action.value, urlError = null, savedNotice = null)
            }

            SettingsAction.OnSaveServerUrl -> viewModelScope.launch { save() }

            SettingsAction.OnResetToDefault -> viewModelScope.launch {
                withContext(Dispatchers.Default) { serverConfig.reset() }
                val restored = serverConfig.platformDefault
                _state.update {
                    it.copy(
                        serverUrlDraft = restored,
                        serverUrlInEffect = restored,
                        isPlatformDefault = true,
                        urlError = null,
                        savedNotice = "Back to this build's default address.",
                        // The old result was about the old address, and leaving
                        // it up would attach a tick to a server never contacted.
                        connection = null,
                    )
                }
            }

            SettingsAction.OnTestConnection -> viewModelScope.launch { testConnection() }

            SettingsAction.OnBack -> viewModelScope.launch {
                _events.send(SettingsEvent.NavigateBack)
            }
        }
    }

    private suspend fun save() {
        val draft = _state.value.serverUrlDraft
        when (val result = withContext(Dispatchers.Default) { serverConfig.setBaseUrl(draft) }) {
            is ServerUrlResult.Invalid -> _state.update {
                it.copy(urlError = result.reason, savedNotice = null)
            }

            is ServerUrlResult.Valid -> _state.update {
                it.copy(
                    // The normalised address, not what was typed. Showing the
                    // stored form is the only way somebody can tell that
                    // `192.168.1.20:8000/` became `http://192.168.1.20:8000`.
                    serverUrlDraft = result.url,
                    serverUrlInEffect = result.url,
                    isPlatformDefault = false,
                    urlError = null,
                    savedNotice = "Saved. The next sync will use this address.",
                    connection = null,
                )
            }
        }
    }

    /**
     * Ask whether there is a server at the address, without moving any data.
     *
     * Tests the **saved** address, not the draft: a person who has typed
     * something and not saved it would otherwise get a tick for an address the
     * app is not using, which is worse than no answer.
     */
    private suspend fun testConnection() {
        if (_state.value.isTestingConnection) return
        _state.update { it.copy(isTestingConnection = true, connection = null) }
        try {
            val url = _state.value.serverUrlInEffect
            val result = withContext(Dispatchers.Default) { syncClient.checkConnection(url) }
            _state.update {
                it.copy(
                    connection = when (result) {
                        is ConnectionCheck.Reached -> ConnectionUi.Reached(
                            result.url,
                            result.environment,
                        )

                        is ConnectionCheck.Failed -> ConnectionUi.Failed(
                            result.url,
                            result.reason,
                        )
                    },
                )
            }
        } finally {
            _state.update { it.copy(isTestingConnection = false) }
        }
    }
}
