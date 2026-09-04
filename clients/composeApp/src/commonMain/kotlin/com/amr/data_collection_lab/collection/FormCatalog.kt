package com.amr.data_collection_lab.collection

import com.dcp.core.sync.DatasetStore
import com.dcp.core.sync.MissingDataset
import com.dcp.core.sync.StoredDatasetSource
import com.dcp.form.DatasetSource
import com.dcp.core.sync.FormStore
import com.dcp.core.sync.StoredFormVersion
import com.dcp.core.sync.SubmissionStore
import com.dcp.form.CompiledForm
import com.dcp.form.FormIr
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext

/** A form this device can start a new submission on. */
data class FormChoice(
    val formId: String,
    val version: Int,
    val title: String,
)

/**
 * One form version on this device, as the settings screen reports it.
 *
 * [deployed] is the server's word and not this device's: false means the
 * manifest has stopped listing the version, and it is still here only because a
 * submission refers to it (Form IR §9). Worth showing, because "withdrawn, kept
 * for a draft" and "current" look identical otherwise and the first is the one
 * a supervisor is ringing about.
 */
data class HeldForm(
    val formId: String,
    val version: Int,
    val title: String,
    val deployed: Boolean,
    val fetchedAt: String,
)

/**
 * Compiles the form versions the server has delivered to this device.
 *
 * This used to read one form out of the app's own resources. That made the
 * bundled `household_survey.json` the only form any device could ever collect,
 * which is why a customer's form could not be put on a phone at all — the
 * question was not which form to show, it was that there was no route from an
 * author to a device. Forms now arrive over sync (§5) and land in [FormStore];
 * this compiles what is there.
 *
 * **There is deliberately no bundled fallback.** A device that has never synced
 * has no forms, and the list says so. Falling back to a form compiled into the
 * app would show an enumerator a questionnaire nobody deployed to them, and
 * every answer collected against it would be filed under a form version the
 * server may not even have — which reads, from the phone, exactly like working.
 *
 * Compilation is cached per (formId, version) because it is not cheap and a
 * published version is immutable, so the result can never go stale.
 */
class FormCatalog(
    private val forms: FormStore,
    private val submissions: SubmissionStore,
    /**
     * The reference data behind `select_one_from_file` (Form IR §3).
     *
     * Null on a build with no dataset store — the desktop review client — where
     * a dataset-backed list resolves to nothing and [missingDatasetsForSubmission]
     * says so, rather than a select rendering empty for no stated reason.
     */
    private val datasets: DatasetStore? = null,
) {
    private val mutex = Mutex()
    private val compiled = mutableMapOf<String, CompiledForm>()

    /** Forms a new submission may be started on — current versions only. */
    suspend fun startable(): List<FormChoice> = withContext(Dispatchers.Default) {
        forms.startable().map { FormChoice(it.formId, it.version, it.title) }
    }

    /**
     * Every version this device holds, including the ones it may no longer
     * start — for the settings screen, which answers "what is actually on this
     * phone".
     *
     * Deliberately not [startable]. A device retains every version any local
     * submission still refers to (Form IR §9), so the two lists differ exactly
     * when something interesting is true: a version has been withdrawn on the
     * server and a draft here still needs it. A screen that showed only the
     * startable ones would report a form as absent while a draft was open
     * against it, which is the question this screen exists to answer.
     *
     * A flow rather than a call, because the screen must not be able to
     * disagree with the database it is reporting on — see [FormStore.observeAll].
     */
    fun observeHeld(): Flow<List<HeldForm>> = forms.observeAll().map { versions ->
        versions.map {
            HeldForm(
                formId = it.formId,
                version = it.version,
                title = it.title,
                deployed = it.deployed,
                fetchedAt = it.fetchedAt,
            )
        }
    }

    /**
     * The compiled form for one submission, resolved from the submission itself.
     *
     * **The caller does not choose a version, and that is the point.** Form IR
     * §9 binds a submission to the version it was collected under, and the only
     * way to honour that is for nothing above this line to be in a position to
     * pass a different one. An enumerator can be half way through a v2 interview
     * on the morning v3 deploys; opening it against v3 would evaluate their
     * answers under rules nobody asked them — silently, since the answers are
     * still there and the questions merely changed.
     *
     * That failure is invisible to every automated check this repository had:
     * it lives above the conformance vectors, above the engine, and above the
     * shared sync code. `FormVersionBindingTest` is what watches it.
     *
     * Null when the submission is unknown, or when this device no longer holds
     * its version — the honest answer, which the caller renders rather than
     * papers over.
     */
    suspend fun compiledFormForSubmission(submissionId: String): CompiledForm? {
        val summary = withContext(Dispatchers.Default) {
            submissions.getSubmission(submissionId)
        } ?: return null
        return compiledForm(summary.formId, summary.formVersion)
    }

    /**
     * Where this submission's choice lists come from — the same binding, again.
     *
     * **The caller does not choose a version here either, and for the same
     * reason.** A dataset key in the IR is a key, not a version (§3.2), and the
     * version it means is the one the *form version* was published against. A
     * source resolved any other way would serve last month's villages to this
     * month's answers, which is [compiledFormForSubmission]'s failure with a
     * village list instead of a question list.
     *
     * So this takes a submission id and nothing else, exactly as the form does,
     * and there is no sibling that takes a form version.
     */
    suspend fun datasetSourceForSubmission(submissionId: String): DatasetSource? {
        val store = datasets ?: return null
        val id = formVersionIdForSubmission(submissionId) ?: return null
        return StoredDatasetSource(store, id)
    }

    /**
     * The lists this submission's form needs and this device cannot serve.
     *
     * Empty is the ordinary answer. A non-empty one is what turns "the select
     * has no options" into a sentence somebody can act on — the reference data
     * has not finished syncing — rather than a blank space an enumerator has to
     * interpret (§3.2).
     */
    suspend fun missingDatasetsForSubmission(submissionId: String): List<MissingDataset> {
        val store = datasets ?: return emptyList()
        val id = formVersionIdForSubmission(submissionId) ?: return emptyList()
        return withContext(Dispatchers.Default) { store.missingFor(id) }
    }

    private suspend fun formVersionIdForSubmission(submissionId: String): String? =
        withContext(Dispatchers.Default) {
            val summary = submissions.getSubmission(submissionId) ?: return@withContext null
            forms.find(summary.formId, summary.formVersion)?.formVersionId
        }

    /**
     * The compiled form for one exact version.
     *
     * Internal: [compiledFormForSubmission] is how a submission gets its form.
     * Exposed only to the sensitivity lookup, which is genuinely asking about a
     * (formId, version) pair off an outbound op rather than about a submission.
     */
    suspend fun compiledForm(formId: String, version: Int): CompiledForm? {
        val key = "$formId@$version"
        return mutex.withLock {
            compiled[key] ?: withContext(Dispatchers.Default) {
                forms.find(formId, version)?.let { compile(it) }
            }?.also { compiled[key] = it }
        }
    }

    /**
     * Title for a submission's form, without paying to compile it.
     *
     * The list screen needs one line per row and nothing else; compiling every
     * distinct version to read a title back would be the expensive way to
     * render a list. Falls back to the form key so a row is never blank.
     */
    suspend fun titleFor(formId: String, version: Int): String =
        withContext(Dispatchers.Default) { forms.find(formId, version)?.title ?: formId }

    private fun compile(stored: StoredFormVersion): CompiledForm =
        CompiledForm(FormIr.parse(stored.irJson))
}
