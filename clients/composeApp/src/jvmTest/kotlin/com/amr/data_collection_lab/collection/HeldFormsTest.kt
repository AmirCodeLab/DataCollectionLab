package com.amr.data_collection_lab.collection

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.core.sync.FormManifestEntry
import com.dcp.core.sync.FormStore
import com.dcp.core.sync.SubmissionStore
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.yield
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout

/**
 * "Which forms are on this device" is a different question from "which forms
 * can I start", and the settings screen asks the first one.
 *
 * A device retains every version any local submission still refers to (Form IR
 * §9), so the two lists differ exactly when something is worth knowing: a
 * version has been withdrawn on the server and a draft here still needs it.
 * Answering the settings screen with [FormCatalog.startable] would report that
 * form as absent while a draft was open against it — a screen built to explain
 * a confusing device, itself lying about what the device has.
 *
 * It is the easy substitution to make, because `startable()` already existed
 * and returns something that looks right on a device where nothing has been
 * withdrawn — which is every device until the day it matters.
 *
 * Break 32 in docs/known-breaks.md.
 */
class HeldFormsTest {

    private class Fixture {
        val db: DcpDatabase = DcpDatabase(
            JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema),
        )
        val submissions = SubmissionStore(db, deviceIdOverride = "dev-test")
        val forms = FormStore(db)
        val catalog = FormCatalog(forms, submissions)

        fun entry(version: Int) = FormManifestEntry(
            formVersionId = "fv-$version",
            formId = "household",
            version = version,
            title = "Household Survey",
            irChecksum = "sha256:v$version",
        )

        fun deliver(vararg versions: Int) = forms.applyManifest(
            versions.map { entry(it) },
            versions.associate { "fv-$it" to ir(it) },
        )

        private fun ir(version: Int) =
            """{"irVersion":"0.1","formId":"household","version":$version,
                "title":{"en":"Household Survey"},"defaultLanguage":"en","languages":["en"],
                "children":[]}"""
    }

    @Test
    fun `a withdrawn version a draft still needs is listed, and marked withdrawn`() = runBlocking {
        val fixture = Fixture()
        fixture.deliver(1)
        // A draft against v1, which is what stops retention dropping it.
        fixture.submissions.createDraft("household", 1)
        // v2 deploys; the manifest no longer lists v1.
        fixture.deliver(2)

        val held = fixture.catalog.observeHeld().first()

        assertEquals(
            listOf(2 to true, 1 to false),
            held.map { it.version to it.deployed },
            "the settings screen must show both, and say which the server withdrew",
        )
    }

    @Test
    fun `startable is the narrower list, which is why it is the wrong one here`() = runBlocking {
        val fixture = Fixture()
        fixture.deliver(1)
        fixture.submissions.createDraft("household", 1)
        fixture.deliver(2)

        val startable = fixture.catalog.startable()

        assertEquals(listOf(2), startable.map { it.version })
        assertTrue(
            fixture.catalog.observeHeld().first().size > startable.size,
            "if these two ever agree, this test has stopped testing anything",
        )
    }

    @Test
    fun `a form delivered after the list is first read shows up without a relaunch`() = runBlocking {
        // The bug this was written for, found on a device: the settings screen
        // read its form list once at construction, so a sync that delivered a
        // form left the screen still reporting none — the screen contradicting
        // the database it was opened to explain, with no error anywhere and a
        // successful sync behind it. Relaunching the app "fixed" it, which is
        // the worst possible symptom: it looks like a sync problem.
        val fixture = Fixture()
        val seen = mutableListOf<List<HeldForm>>()
        val job = launch { fixture.catalog.observeHeld().collect { seen += it } }
        // Bounded, not `while (…) yield()`. A flow that emits once and never
        // again — which is exactly the break this watches — makes an unbounded
        // spin hang the build instead of failing it, and a test that hangs
        // reports nothing to the person who broke it.
        withTimeout(5_000) { while (seen.isEmpty()) yield() }
        assertEquals(emptyList(), seen.first())

        fixture.deliver(1)

        withTimeout(5_000) {
            while (seen.last().isEmpty()) yield()
        }
        assertEquals(listOf(1), seen.last().map { it.version })
        job.cancel()
    }

    @Test
    fun `a device that has synced nothing holds nothing`() = runBlocking {
        // No bundled form and no fallback to one. An empty list here is the
        // honest answer and the screen says which of the two empties it is.
        assertEquals(emptyList(), Fixture().catalog.observeHeld().first())
    }
}
