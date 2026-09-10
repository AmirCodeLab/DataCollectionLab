package com.amr.data_collection_lab.collection

import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue

/**
 * The finalisation gate is wired, and wired in the right order.
 *
 * `ReferenceDataReadinessTest` in shared core decides *whether* a submission
 * may be finalised. Nothing there can see whether the ViewModel asks. This
 * does, by reading `finalize()` and checking that readiness is consulted
 * before a `FINALIZE` op is written — because the failure this guards is
 * somebody deleting three lines and every other test staying green while a
 * device files households with no members (item 4 §2, failure 1).
 *
 * A source check rather than a ViewModel test: `CollectionViewModel` needs a
 * lifecycle and a compiled form to instantiate, and nothing in this module
 * drives one. The rule is narrow enough to read off the text, and a rule that
 * is only a convention is one this repository has already watched get undone.
 */
class FinalisationGateTest {

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

    /** The body of `private fun finalize()`, up to the next top-level member. */
    private fun finalizeBody(): String {
        val text = viewModel.readText()
        val start = text.indexOf("private fun finalize()")
        assertTrue(start > 0, "finalize() not found — this test is reading the wrong thing")
        val end = text.indexOf("\n    private fun ", start + 1)
            .let { if (it == -1) text.length else it }
        return text.substring(start, end)
    }

    @Test
    fun `readiness is consulted before a finalize op is written`() {
        val body = finalizeBody()
        val asked = body.indexOf("readinessOfSubmission")
        val written = body.indexOf("OpKind.FINALIZE")

        assertTrue(asked > 0, "finalize() does not ask whether the reference data is here")
        assertTrue(written > 0, "finalize() no longer writes a finalize op — read this test again")
        assertTrue(
            asked < written,
            "finalize() writes the op before it asks: the gate is decoration, and a " +
                "submission whose questions this device could not put would be filed complete",
        )
    }

    @Test
    fun `the gate records the facts, never a rendered sentence`() {
        // This screen has a language toggle. A sentence built at refusal time
        // stayed English when the enumerator switched to Arabic — seen on a
        // phone — so the state carries the lists and the screen renders them
        // in whatever language is showing when it draws.
        val body = finalizeBody()
        assertTrue(
            "referenceDataLists = readiness.lists" in body,
            "finalize() must record the lists, so the sentence can be rendered per language",
        )
        assertTrue(
            "UiStrings." !in body,
            "a sentence rendered here freezes the language it was built in",
        )
    }
}
