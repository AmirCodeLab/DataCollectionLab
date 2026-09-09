package com.amr.data_collection_lab.collection

import com.dcp.core.sync.HeldCase
import com.dcp.form.FormValue
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * What the handset does with a case that vanished from the statement while a
 * draft was on it (item 2, analysis §4.3): kept, listed as no longer
 * assigned, openable, and never a starting point for new work.
 */
class CaseListingTest {

    private fun held(
        id: String,
        key: String,
        assigned: Boolean,
        submissions: Long = 0,
        latest: String? = null,
    ) = HeldCase(
        caseId = id,
        caseKey = key,
        datasetKey = "village",
        status = "open",
        priority = 0,
        dueAt = null,
        dataJson = """{"case_key":"$key","headName":"Amina","hhSize":"4","note":""}""",
        assigned = assigned,
        firstSeenAt = "2026-09-09T10:00:00Z",
        releasedSeenAt = if (assigned) null else "2026-09-09T12:00:00Z",
        submissions = submissions,
        latestSubmissionId = latest,
    )

    @Test
    fun `a released case with a draft is listed under its own heading, one without is not`() {
        val sections = sectionsOf(
            listOf(
                held("c1", "S3|1|1", assigned = true),
                held("c2", "S3|1|2", assigned = false, submissions = 1, latest = "sub-2"),
                held("c3", "S3|2|1", assigned = false),
            ),
        )
        assertEquals(listOf("S3|1|1"), sections.assigned.map { it.label })
        assertEquals(listOf("S3|1|2"), sections.releasedWithWork.map { it.label })
        assertEquals("headName: Amina · hhSize: 4", sections.assigned.single().summary)
    }

    @Test
    fun `a tap opens the draft on a released case, starts on an assigned one, refuses otherwise`() {
        val draftOnReleased = held("c2", "S3|1|2", assigned = false, submissions = 1, latest = "sub-2").toUi()
        assertEquals(CaseTap.OpenExisting("sub-2"), tapOn(draftOnReleased))

        val fresh = held("c1", "S3|1|1", assigned = true).toUi()
        assertEquals(CaseTap.StartNew("c1"), tapOn(fresh))

        val inProgress = held("c1", "S3|1|1", assigned = true, submissions = 2, latest = "sub-9").toUi()
        assertEquals(CaseTap.OpenExisting("sub-9"), tapOn(inProgress))

        val refused = tapOn(held("c3", "S3|2|1", assigned = false).toUi())
        assertIs<CaseTap.Refused>(refused)
        assertTrue("no longer assigned to you" in refused.message)
    }

    @Test
    fun `the case key reaches the engine as metadata, and the note says when the case moved`() {
        assertEquals(mapOf("case_key" to FormValue.Text("S3|1|1")), caseMetadata("S3|1|1"))
        assertTrue(caseMetadata(null).isEmpty())
        assertNull(caseNoteFor(null, null))
        assertEquals("Case S3|1|1", caseNoteFor("S3|1|1", true))
        assertEquals(
            "Case S3|1|1 · no longer assigned to you — the draft is kept",
            caseNoteFor("S3|1|1", false),
        )
    }
}
