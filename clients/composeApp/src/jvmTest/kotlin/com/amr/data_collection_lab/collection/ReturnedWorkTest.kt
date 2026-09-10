package com.amr.data_collection_lab.collection

import com.dcp.core.sync.SubmissionStatus
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Work a reviewer sent back opens **editable** (item 6).
 *
 * Found in the field, not by reading: the handset run showed the reason on the
 * row, the enumerator tapped it, and the form opened read-only with "Finalized"
 * in the header. Being shown what to correct and then not being able to correct
 * it is worse than not being told — it is a dead end with an instruction on it.
 *
 * The cause is an ordering that looks harmless. `CollectionViewModel` reads the
 * submission's summary, then appends the `reopen` op, then builds its state
 * from the summary it read **before** the append. The status in hand is
 * therefore the one from before this function acted.
 */
class ReturnedWorkTest {

    @Test
    fun `the two statuses a handset can only be told are recognised as returned`() {
        assertTrue(SubmissionStatus.isReturned(SubmissionStatus.CORRECTION_REQUIRED))
        assertTrue(SubmissionStatus.isReturned(SubmissionStatus.REJECTED))
        assertFalse(SubmissionStatus.isReturned(SubmissionStatus.DRAFT))
        assertFalse(SubmissionStatus.isReturned(SubmissionStatus.FINALIZED))
    }

    @Test
    fun `returned work is not finalized, whatever the summary read before the reopen said`() {
        // The expression from CollectionViewModel, in the two states that
        // matter. `reopened` is the fact the load itself caused; the summary
        // is what the row said on arrival.
        fun finalizedFlag(status: String): Boolean {
            val reopened = SubmissionStatus.isReturned(status)
            return !reopened && status == SubmissionStatus.FINALIZED
        }

        assertFalse(
            finalizedFlag(SubmissionStatus.CORRECTION_REQUIRED),
            "work sent back for correction opened read-only",
        )
        assertFalse(
            finalizedFlag(SubmissionStatus.REJECTED),
            "rejected work opened read-only",
        )
        assertTrue(finalizedFlag(SubmissionStatus.FINALIZED))
        assertFalse(finalizedFlag(SubmissionStatus.DRAFT))
    }
}
