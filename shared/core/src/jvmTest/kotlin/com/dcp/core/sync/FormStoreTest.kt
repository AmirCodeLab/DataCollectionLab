package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The local form store, and the retention rule that is the whole reason it is
 * not a cache.
 *
 * `FormStore` is Kotlin-only. The Python reference has no device, no manifest
 * and nothing to retain, so no conformance vector can reach any of this
 * (docs/project-conventions.md, "Where the conformance architecture stops protecting you") — a
 * completely green conformance run says nothing about the code under test here.
 * This file is the only thing that does.
 *
 * The failure these tests exist to prevent looks like success from every screen:
 * a device that keeps only the newest version syncs cleanly, shows the right
 * form to start, and cannot open the draft an enumerator was half way through.
 */
class FormStoreTest {

    private fun db(): DcpDatabase =
        DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema))

    private fun entry(formId: String, version: Int, checksum: String = "sha256:$formId-$version") =
        FormManifestEntry(
            formVersionId = "fv-$formId-$version",
            formId = formId,
            version = version,
            title = "Household Survey",
            irChecksum = checksum,
        )

    private fun document(formId: String, version: Int) =
        """{"irVersion":"0.1","formId":"$formId","version":$version}"""

    /** Applies a manifest with a document for every entry — a first sync. */
    private fun FormStore.deliver(vararg entries: FormManifestEntry) =
        applyManifest(
            entries.toList(),
            entries.associate { it.formVersionId to document(it.formId, it.version) },
        )

    @Test
    fun `a version the device does not hold is the one asked for`() {
        val store = FormStore(db())
        val manifest = listOf(entry("household", 1), entry("clinic", 1))

        assertEquals(
            listOf("fv-household-1", "fv-clinic-1"),
            store.missingFrom(manifest).map { it.formVersionId },
        )

        store.deliver(*manifest.toTypedArray())
        assertEquals(
            emptyList(),
            store.missingFrom(manifest),
            "a version already held must not be fetched again — that is what makes the " +
                "manifest cheaper than sending every document on every pull",
        )
    }

    @Test
    fun `content that drifted under the same version number is refetched`() {
        val store = FormStore(db())
        store.deliver(entry("household", 1))

        // Same form, same version number, different checksum. Comparing on
        // (formId, version) instead of the checksum would call this held.
        val drifted = listOf(entry("household", 1, checksum = "sha256:something-else"))
        assertEquals(
            listOf("fv-household-1"),
            store.missingFrom(drifted).map { it.formVersionId },
        )
    }

    @Test
    fun `every deployed version is kept, not only the newest`() {
        // Form IR §9: a submission is validated against the version it was
        // collected under. A store that kept one version per form would pass
        // every other test in this file.
        val store = FormStore(db())
        store.deliver(entry("household", 1), entry("household", 2), entry("household", 3))

        assertEquals(listOf(3, 2, 1), store.all().map { it.version })
        assertNotNull(store.find("household", 1))
        assertNotNull(store.find("household", 2))
    }

    @Test
    fun `only the newest deployed version can start a new submission`() {
        val store = FormStore(db())
        store.deliver(entry("household", 1), entry("household", 2), entry("clinic", 1))

        assertEquals(
            listOf("household" to 2, "clinic" to 1).sortedBy { it.first },
            store.startable().map { it.formId to it.version }.sortedBy { it.first },
            "a new interview starts on the current version; the older ones stay openable",
        )
    }

    @Test
    fun `a version the server stops deploying is withdrawn, not deleted`() {
        val store = FormStore(db())
        store.deliver(entry("household", 1), entry("household", 2))

        // v1 gone from the manifest. It must still be *findable* — the decision
        // to delete belongs to prune(), which asks whether anything needs it.
        store.applyManifest(listOf(entry("household", 2)), emptyMap())

        val withdrawn = assertNotNull(store.find("household", 1))
        assertEquals(false, withdrawn.deployed)
        assertEquals(listOf(2), store.startable().map { it.version })
    }

    @Test
    fun `pruning keeps a withdrawn version a draft was collected under`() {
        // The failure this whole class exists to prevent. An enumerator holds a
        // v1 draft; the server deploys v2 and withdraws v1. Deleting v1 would
        // leave that draft unopenable on the device that wrote it — the op log
        // records the answers, never the questions.
        val database = db()
        val store = FormStore(database)
        val submissions = SubmissionStore(database, deviceIdOverride = "dev-test")
        store.deliver(entry("household", 1))
        submissions.createDraft("household", 1)

        store.applyManifest(listOf(entry("household", 2)), mapOf("fv-household-2" to document("household", 2)))
        assertEquals(0, store.prune(), "nothing is prunable while a submission refers to v1")

        assertNotNull(
            store.find("household", 1),
            "the version behind an existing draft must survive being withdrawn",
        )
    }

    @Test
    fun `pruning drops a withdrawn version nothing refers to`() {
        val store = FormStore(db())
        store.deliver(entry("household", 1), entry("clinic", 1))

        store.applyManifest(listOf(entry("household", 1)), emptyMap())
        assertEquals(1, store.prune())

        assertNull(store.find("clinic", 1))
        assertNotNull(store.find("household", 1), "a still-deployed version is never prunable")
    }

    @Test
    fun `a deployed version is never pruned even with no submissions`() {
        val store = FormStore(db())
        store.deliver(entry("household", 1))

        assertEquals(0, store.prune())
        assertNotNull(store.find("household", 1))
    }

    @Test
    fun `a manifest entry with no document confirms the version already held`() {
        // What a sync does when the device is up to date: the manifest lists
        // versions, missingFrom() asks for none, and applyManifest is called
        // with an empty document map. If that undeployed everything, a device
        // that changed nothing would lose every form it had.
        val store = FormStore(db())
        store.deliver(entry("household", 1), entry("household", 2))

        store.applyManifest(listOf(entry("household", 1), entry("household", 2)), emptyMap())

        assertEquals(2, store.all().size)
        assertTrue(store.all().all { it.deployed })
        assertEquals(listOf(2), store.startable().map { it.version })
    }

    @Test
    fun `redeploying a withdrawn version marks it deployed again without refetching`() {
        val store = FormStore(db())
        store.deliver(entry("household", 1))
        store.applyManifest(emptyList(), emptyMap())
        assertEquals(false, assertNotNull(store.find("household", 1)).deployed)

        // Rolled back to v1 on the server. The device still holds the document,
        // so the manifest alone is enough to put it back in service.
        store.applyManifest(listOf(entry("household", 1)), emptyMap())

        assertEquals(true, assertNotNull(store.find("household", 1)).deployed)
        assertEquals(listOf(1), store.startable().map { it.version })
    }

    @Test
    fun `the stored document is the one that comes back out`() {
        val store = FormStore(db())
        store.deliver(entry("household", 7))

        assertEquals(document("household", 7), assertNotNull(store.find("household", 7)).irJson)
    }
}
