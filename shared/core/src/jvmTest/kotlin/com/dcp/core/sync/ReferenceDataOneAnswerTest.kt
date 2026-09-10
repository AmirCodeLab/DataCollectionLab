package com.dcp.core.sync

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals

/**
 * One question, one answer.
 *
 * Two surfaces ask whether this device holds the reference data a form version
 * pins: the finalisation gate, which refuses to call an interview complete
 * when the device could not put its questions, and the updates screen, which
 * says what is missing and offers the fetch. If either computed it for itself
 * the screen could say ready while the gate refused, or the reverse — and a
 * screen contradicting the gate beside it is worse than either being wrong,
 * because the person cannot tell which to believe.
 *
 * That is the shape known defect 24 had: two surfaces answering one question
 * from two places, agreeing in every test and disagreeing on a device. So the
 * readiness primitives are readable from `ReferenceData` and nowhere else, and
 * this fails the build when a second caller appears.
 *
 * A source scan rather than an architectural convention, for the same reason
 * `test_one_connection_factory.py` is a lint rather than a note: the rule is
 * only worth anything if breaking it is louder than following it.
 */
class ReferenceDataOneAnswerTest {

    /** The primitives. Anything that calls one of these is deciding readiness. */
    private val primitives = listOf("pinnedLists(", "missingFor(")

    /**
     * `DatasetStore` defines them, `ReferenceData` is the one place that asks,
     * and `DatasetBenchmark` is a measurement harness rather than a surface —
     * it drives a device to time a sync and shows nobody an answer.
     */
    private val exempt = setOf("DatasetStore.kt", "ReferenceData.kt", "DatasetBenchmark.kt")

    private val repoRoot: File by lazy {
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null) {
            if (dir.resolve("shared/core/src/commonMain/kotlin").isDirectory) return@lazy dir
            dir = dir.parentFile
        }
        error("repository root not found above ${System.getProperty("user.dir")}")
    }

    private val productionTrees = listOf(
        "shared/core/src/commonMain/kotlin",
        "shared/form-engine/src/commonMain/kotlin",
        "clients/composeApp/src/commonMain/kotlin",
    )

    /** Source lines with comments dropped: a mention is not a call. */
    private fun code(file: File): List<String> =
        file.readLines().map { it.trim() }.filterNot {
            it.startsWith("//") || it.startsWith("*") || it.startsWith("/*")
        }

    @Test
    fun `readiness is asked in exactly one place`() {
        val callers = productionTrees
            .map { repoRoot.resolve(it) }
            .filter { it.isDirectory }
            .flatMap { tree -> tree.walkTopDown().filter { it.extension == "kt" } }
            .filter { file ->
                file.name !in exempt && code(file).any { line -> primitives.any { it in line } }
            }
            .map { it.name }
            .sorted()

        assertEquals(
            emptyList(),
            callers,
            "these ask readiness for themselves instead of through ReferenceData: $callers — " +
                "one of them will eventually disagree with the other, on a device, in a village",
        )
    }

    @Test
    fun `the trees this scans actually exist`() {
        // A scan over a path that moved passes silently and protects nothing.
        val missing = productionTrees.filterNot { repoRoot.resolve(it).isDirectory }
        assertEquals(emptyList(), missing, "scanned paths that are not there: $missing")
    }
}
