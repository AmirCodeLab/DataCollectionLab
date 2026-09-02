package com.amr.data_collection_lab.collection

import com.dcp.core.sync.FormStore
import com.dcp.core.sync.StoredFormVersion
import com.dcp.core.sync.SubmissionStore
import com.dcp.form.CompiledForm
import com.dcp.form.FormIr
import kotlinx.coroutines.Dispatchers
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
) {
    private val mutex = Mutex()
    private val compiled = mutableMapOf<String, CompiledForm>()

    /** Forms a new submission may be started on — current versions only. */
    suspend fun startable(): List<FormChoice> = withContext(Dispatchers.Default) {
        forms.startable().map { FormChoice(it.formId, it.version, it.title) }
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
