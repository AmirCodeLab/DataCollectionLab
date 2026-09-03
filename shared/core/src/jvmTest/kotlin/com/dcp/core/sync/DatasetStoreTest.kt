package com.dcp.core.sync

import app.cash.sqldelight.driver.jdbc.sqlite.JdbcSqliteDriver
import com.dcp.core.db.DcpDatabase
import com.dcp.form.FormValue
import java.util.Properties
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * The local dataset store, and the staleness it exists to refuse.
 *
 * `FormStoreTest` guards a failure that at least has a symptom: a device that
 * dropped a version cannot open a draft, and somebody notices. This guards one
 * that has none.
 *
 * The device holds v1 of `villages`, the server moved to v2, and an enumerator
 * picks a village that no longer exists. The form opens. The list scrolls. The
 * search works. The answer saves and syncs and is accepted. Nothing on any
 * screen is in an error state and the data is wrong — and a delta mechanism
 * makes it *more* likely, because "nothing changed" and "I failed to ask"
 * produce the same silence.
 *
 * All of this is Kotlin-only and above the line the conformance vectors reach
 * (docs/project-conventions.md). Worse than that: *which version of a list is used* is precisely
 * the which-artifact decision a vector is structurally unable to see. A
 * completely green conformance run says nothing about any of it. This file is
 * the only thing that does.
 */
class DatasetStoreTest {

    private fun db(): DcpDatabase =
        DcpDatabase(JdbcSqliteDriver(JdbcSqliteDriver.IN_MEMORY, Properties(), DcpDatabase.Schema))

    private fun entry(
        formVersionId: String = "fv-1",
        key: String = "villages",
        versionId: String = "dv-1",
        version: Int = 1,
        rowCount: Int = 2,
        checksum: String = "sha256:$versionId",
    ) = DatasetManifestEntry(formVersionId, key, versionId, version, rowCount, checksum)

    private fun rows(vararg keys: String) =
        keys.map { it to """{"name":"$it","label":"Village $it"}""" }

    /** A manifest applied and every page delivered — a first sync that worked. */
    private fun DatasetStore.deliver(entry: DatasetManifestEntry, vararg keys: String) {
        applyManifest(listOf(entry))
        appendRows(entry.datasetVersionId, rows(*keys), nextCursor = null)
    }

    // -- the resolver ------------------------------------------------------

    @Test
    fun `rows resolve through the form version that pinned them`() {
        val store = DatasetStore(db())
        store.deliver(entry(), "V1", "V2")

        assertEquals(listOf("V1", "V2"), store.rowsFor("fv-1", "villages").map { it.first })
    }

    @Test
    fun `a form version that pinned nothing gets no rows`() {
        // Not "the rows that happen to be here". The store holds them; this
        // form version did not ask for them; the answer is nothing.
        val store = DatasetStore(db())
        store.deliver(entry(), "V1")

        assertTrue(store.rowsFor("fv-other", "villages").isEmpty())
    }

    @Test
    fun `a stale pin resolves to nothing rather than to the version held`() {
        /**
         * The whole point of the class.
         *
         * The device holds v1 whole. A new manifest says this form version is
         * now published against v2, whose rows have not arrived. The tempting
         * answer — and the one a store keyed on `dataset_key` would give — is
         * v1's rows: they are right there, they are complete, and they are a
         * village list. They are last month's village list.
         */
        val store = DatasetStore(db())
        store.deliver(entry(versionId = "dv-1", version = 1), "V1", "V2")
        assertEquals(2, store.rowsFor("fv-1", "villages").size)

        store.applyManifest(listOf(entry(versionId = "dv-2", version = 2)))

        assertTrue(
            store.rowsFor("fv-1", "villages").isEmpty(),
            "the form is now pinned to v2 and v2 has not arrived; serving v1 " +
                "would be a village list that is wrong and looks right",
        )
        assertEquals(
            listOf(MissingDataset("villages", "dv-2")),
            store.missingFor("fv-1"),
            "and it has to be *sayable*, or the empty list is just a mystery",
        )
    }

    @Test
    fun `a half-transferred version is not the version`() {
        // A list that stopped two thirds of the way through is one an
        // enumerator can search, scroll and choose from. Nothing about it looks
        // wrong, and the village they need may be in the third that is missing.
        val store = DatasetStore(db())
        store.applyManifest(listOf(entry(rowCount = 3)))
        store.appendRows("dv-1", rows("V1", "V2"), nextCursor = "cursor-2")

        assertTrue(store.rowsFor("fv-1", "villages").isEmpty())
        assertEquals(1, store.missingFor("fv-1").size)
        assertFalse(assertNotNull(store.find("dv-1")).complete)
        assertEquals("cursor-2", store.find("dv-1")?.nextCursor)

        store.appendRows("dv-1", rows("V3"), nextCursor = null)
        assertEquals(3, store.rowsFor("fv-1", "villages").size)
        assertTrue(store.missingFor("fv-1").isEmpty())
        assertNull(store.find("dv-1")?.nextCursor)
    }

    @Test
    fun `two form versions may pin different versions of one list`() {
        // The reason the manifest is keyed by form version and not by dataset:
        // an enumerator holding a v2 draft the morning v3 lands has both forms
        // on the device, and they were published against different lists.
        val store = DatasetStore(db())
        store.applyManifest(
            listOf(
                entry(formVersionId = "fv-1", versionId = "dv-1", version = 1),
                entry(formVersionId = "fv-2", versionId = "dv-2", version = 2),
            )
        )
        store.appendRows("dv-1", rows("OLD"), nextCursor = null)
        store.appendRows("dv-2", rows("NEW"), nextCursor = null)

        assertEquals(listOf("OLD"), store.rowsFor("fv-1", "villages").map { it.first })
        assertEquals(listOf("NEW"), store.rowsFor("fv-2", "villages").map { it.first })
    }

    // -- the manifest ------------------------------------------------------

    @Test
    fun `a version already held whole is not re-fetched`() {
        // The cost of getting this wrong is a 38,000-row download on every sync
        // for a manifest that said nothing new.
        val store = DatasetStore(db())
        store.deliver(entry(), "V1", "V2")

        assertTrue(store.missingFrom(listOf(entry())).isEmpty())

        store.applyManifest(listOf(entry()))
        assertEquals(2, store.rowsFor("fv-1", "villages").size, "rows survived a re-applied manifest")
    }

    @Test
    fun `a version whose checksum moved is missing even though its id is held`() {
        val store = DatasetStore(db())
        store.deliver(entry(checksum = "sha256:old"), "V1")

        val moved = entry(checksum = "sha256:new")
        assertEquals(listOf(moved), store.missingFrom(listOf(moved)))
    }

    @Test
    fun `changed content clears the rows it replaces`() {
        // Otherwise a shrinking list keeps the rows it lost: the new pages are
        // written over the old ones by key and whatever was not overwritten
        // stays, which is a village list with deleted villages still in it.
        val store = DatasetStore(db())
        store.deliver(entry(checksum = "sha256:old"), "V1", "V2", "V3")

        store.applyManifest(listOf(entry(checksum = "sha256:new")))
        store.appendRows("dv-1", rows("V1"), nextCursor = null)

        assertEquals(listOf("V1"), store.rowsFor("fv-1", "villages").map { it.first })
    }

    @Test
    fun `pins are replaced per form version rather than merged`() {
        // A pin left behind from an earlier manifest is a list this device
        // believes a form uses and the server does not.
        val store = DatasetStore(db())
        store.applyManifest(
            listOf(
                entry(key = "villages", versionId = "dv-v"),
                entry(key = "districts", versionId = "dv-d"),
            )
        )
        assertEquals(setOf("villages", "districts"), store.pinsFor("fv-1").keys)

        store.applyManifest(listOf(entry(key = "villages", versionId = "dv-v")))
        assertEquals(setOf("villages"), store.pinsFor("fv-1").keys)
    }

    // -- retention ---------------------------------------------------------

    @Test
    fun `a list is kept while a form version this device holds pins to it`() {
        val store = DatasetStore(db())
        val database = db()
        val forms = FormStore(database)
        val datasets = DatasetStore(database)

        forms.applyManifest(
            listOf(
                FormManifestEntry("fv-1", "household", 1, "Household", "sha256:f1")
            ),
            mapOf("fv-1" to """{"irVersion":"0.1","formId":"household","version":1}"""),
        )
        datasets.deliver(entry(formVersionId = "fv-1"), "V1")

        assertEquals(0, datasets.prune(), "the form is held, so its list is held")
        assertEquals(1, datasets.rowsFor("fv-1", "villages").size)
        assertEquals(0, store.prune())
    }

    @Test
    fun `a list goes when the form version that pinned it does`() {
        // Retention is FormStore's rule one level down and follows it rather
        // than restating it: whatever forms survive pruning, their lists
        // survive with them. Nothing here asks the server anything.
        val database = db()
        val datasets = DatasetStore(database)
        datasets.deliver(entry(formVersionId = "fv-gone"), "V1", "V2")

        // No `form_version` row was ever written, so this pin's form version is
        // not held — the state a device reaches the moment FormStore.prune()
        // drops a withdrawn version.
        assertEquals(1, datasets.prune())
        assertTrue(datasets.all().isEmpty())
        assertTrue(datasets.rowsFor("fv-gone", "villages").isEmpty())
    }

    @Test
    fun `pruning is idempotent and does not touch a list still pinned`() {
        val database = db()
        val forms = FormStore(database)
        val datasets = DatasetStore(database)
        forms.applyManifest(
            listOf(FormManifestEntry("fv-1", "household", 1, "Household", "sha256:f1")),
            mapOf("fv-1" to "{}"),
        )
        datasets.deliver(entry(formVersionId = "fv-1"), "V1")
        datasets.applyManifest(
            listOf(
                entry(formVersionId = "fv-1"),
                entry(formVersionId = "fv-dead", versionId = "dv-dead"),
            )
        )
        datasets.appendRows("dv-dead", rows("X"), nextCursor = null)

        assertEquals(1, datasets.prune(), "only the orphan goes")
        assertEquals(0, datasets.prune())
        assertEquals(1, datasets.rowsFor("fv-1", "villages").size)
    }

    // -- the engine bridge -------------------------------------------------

    @Test
    fun `the engine's source serves what the form version pinned and nothing else`() {
        val store = DatasetStore(db())
        store.applyManifest(listOf(entry(formVersionId = "fv-1")))
        store.appendRows(
            "dv-1",
            listOf(
                "V1" to """{"name":"V1","label":"Mtakuja","district_id":"D01"}""",
                "V2" to """{"name":"V2","label":"Mbuyuni","district_id":"D02"}""",
            ),
            nextCursor = null,
        )

        val source = StoredDatasetSource(store, "fv-1")
        val narrowed = source.rows("villages", mapOf("district_id" to FormValue.Text("D01")))
        assertEquals(1, narrowed.size)
        assertEquals(FormValue.Text("V1"), narrowed.single()["name"])

        // A membership check: the selector plus the value column, as §3.2 asks.
        assertEquals(
            1,
            source.rows(
                "villages",
                mapOf("district_id" to FormValue.Text("D01")),
                "name" to FormValue.Text("V1"),
            ).size,
        )
        assertTrue(
            source.rows(
                "villages",
                mapOf("district_id" to FormValue.Text("D01")),
                "name" to FormValue.Text("V2"),
            ).isEmpty(),
            "V2 is in the dataset and not in this district; membership must say no",
        )

        // And the source cannot escape its form version.
        assertTrue(StoredDatasetSource(store, "fv-other").rows("villages", emptyMap()).isEmpty())
    }

    @Test
    fun `there is no way to ask the store for a dataset key alone`() {
        /**
         * The guarantee, asserted against the source rather than the behaviour.
         *
         * Every other test here can be satisfied by a `rowsFor(key)` that
         * happens to check the pin. This asserts the stronger thing: the method
         * does not exist, so a future caller cannot reach for it. Same shape as
         * `compiledFormForSubmission` taking no version (break 30) and
         * `dataset_rows_for` taking none (break 42) — the way to stop a caller
         * choosing wrongly is to stop it choosing.
         */
        val source = DatasetStore::class.java.methods
            .filter { it.name == "rowsFor" }
        assertEquals(1, source.size, "one resolver, not a family of them")
        assertEquals(
            2,
            source.single().parameterCount,
            "rowsFor takes a form version AND a key. A one-argument overload " +
                "would answer 'whichever version happens to be here', which is " +
                "the stale list this class exists to refuse.",
        )
    }
}
