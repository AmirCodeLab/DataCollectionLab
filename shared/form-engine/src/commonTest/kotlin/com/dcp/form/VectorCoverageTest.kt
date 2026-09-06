package com.dcp.form

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * The generated suite covers exactly the corpus **this target can see**.
 *
 * Without this, `vectorNames()` is dead code and two failures are invisible.
 * The generator reads the directory at build time through Gradle, and each
 * @Test it emits reads its own file by name — so a target whose reader returns
 * a smaller corpus still runs every generated test and reports a full count.
 * That was true when this was first written, and a break that dropped one
 * vector from the wasm reader passed everything.
 *
 * `scripts/check_ci_runs_every_suite.py` compares each target's report against
 * the files on disk and would catch a generator that skipped one. It cannot
 * catch a *reader* that sees a different corpus than the generator did, because
 * both numbers come out right. This can, and it fails on the target that
 * disagrees rather than in aggregate.
 */
class VectorCoverageTest {

    @Test
    fun theGeneratedSuiteIsTheCorpusThisTargetSees() {
        val seen = vectorNames().toSet()
        val generated = GENERATED_VECTOR_IDS.toSet()

        assertTrue(seen.isNotEmpty(), "this target read no vectors at all")
        assertEquals(
            generated,
            seen,
            "the corpus this target reads and the suite generated from it disagree. " +
                "Only generated: ${(generated - seen).sorted()}. " +
                "Only readable: ${(seen - generated).sorted()}",
        )
    }
}
