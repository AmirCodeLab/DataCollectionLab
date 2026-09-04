package com.dcp.form

/**
 * Every function §4.3 declares is implemented by **this** engine.
 *
 * The half of the guard that matters, because this is the engine that was
 * missing four of them. `regex`, `substr` and `distance` were in the spec's
 * table, implemented in the Python reference, and had no branch in
 * `Functions.call` — they fell through to
 * `throw CompileException("function not implemented")`. A form using one worked
 * on the server and threw on a phone the moment the field was evaluated, and
 * the UCL biomass form's phone-number constraint uses `regex`. `pulldata` was
 * in the table and in neither engine.
 *
 * All four were **declared** in `signatures`. That is the whole lesson: the map
 * said they existed and the `when` did not implement them, so a check against
 * the map would have passed. Nothing may be checked against a declaration.
 *
 * So this calls each one. A function with no branch throws, and throwing is the
 * failure. `backend/tests/test_function_surface.py` is the other half.
 *
 * Break 49.
 */

import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue
import kotlin.test.fail

class FunctionSurfaceTest {

    private fun repoRoot(): File {
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null) {
            if (dir.resolve("specs/form-ir-v0.1.md").isFile) return dir
            dir = dir.parentFile
        }
        error("specs/form-ir-v0.1.md not found above ${System.getProperty("user.dir")}")
    }

    /**
     * Every function name in §4.3's table, parsed from the spec.
     *
     * Parsed rather than transcribed, for the reason everything else here is: a
     * transcription is a second copy of the list that had the hole in it.
     *
     * `if` is excluded — it is in the table for the reader and is an operator,
     * because a function cannot be lazy in its branches.
     */
    private fun specFunctions(): Set<String> {
        val spec = repoRoot().resolve("specs/form-ir-v0.1.md").readText()
        val table = spec.substringAfter("### 4.3 Functions").substringBefore("#### 4.3.1")
        check(table.isNotBlank()) { "no §4.3 table found in the spec" }
        val names = table.lineSequence()
            .filter { it.startsWith("| `") }
            .flatMap { line ->
                Regex("`([a-z_]+)`").findAll(line.split("|")[1]).map { it.groupValues[1] }
            }
            .toMutableSet()
        names.remove("if")
        check(names.size >= 25) { "parsed only $names out of §4.3" }
        return names
    }

    @Test
    fun everyFunctionInTheSpecTableIsImplemented() {
        val ctx = EvalContext(
            values = emptyMap(),
            today = "2026-08-28",
            now = "2026-08-28T00:00:00",
            datasets = InMemoryDatasetSource(emptyMap()),
        )
        // Null arguments throughout: §4.7 makes every function total over them,
        // so a null answer is the expected one and the ONLY thing being asked
        // here is whether a branch exists at all. Feeding real values would
        // duplicate conformance/functions and make this test about semantics,
        // which is not what was missing.
        val nulls = List(4) { FormValue.Null }

        val unimplemented = specFunctions().filter { fn ->
            try {
                // Try each arity the signature map permits, so an arity error
                // is never mistaken for a missing implementation.
                (0..4).any { arity ->
                    try {
                        Functions.call(fn, nulls.take(arity), ctx); true
                    } catch (e: CompileException) {
                        if (e.message?.contains("not implemented") == true) throw e
                        false
                    }
                }
                false
            } catch (_: CompileException) {
                true
            } catch (_: Throwable) {
                // Anything else means a branch ran, which is what is being asked.
                false
            }
        }

        assertTrue(
            unimplemented.isEmpty(),
            "§4.3 declares ${unimplemented.joinToString(", ")} and this engine has no " +
                "branch for them — a form using one publishes, deploys, and throws " +
                "mid-interview while working perfectly on the server. Declaring them " +
                "in `signatures` is what made the last four invisible.",
        )
    }

    @Test
    fun theSignatureMapDeclaresNothingItCannotDo() {
        /**
         * The asymmetry that shipped, asserted directly.
         *
         * `signatures` is what `call` checks before dispatching, so a name in it
         * with no branch is a promise the `when` does not keep — and the error
         * a caller then gets says "not implemented", from inside a function the
         * map said existed.
         */
        val ctx = EvalContext(
            values = emptyMap(),
            today = "2026-08-28",
            now = "2026-08-28T00:00:00",
            datasets = InMemoryDatasetSource(emptyMap()),
        )
        val declared = specFunctions()
        for (fn in declared) {
            for (arity in 0..4) {
                try {
                    Functions.call(fn, List(arity) { FormValue.Null }, ctx)
                } catch (e: CompileException) {
                    if (e.message?.contains("not implemented") == true) {
                        fail("`$fn` is declared and not implemented: ${e.message}")
                    }
                } catch (_: Throwable) {
                    // A branch ran and disliked its arguments. Fine.
                }
            }
        }
    }

    @Test
    fun theOtherHalfOfThisGuardStillExists() {
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null && !dir.resolve("backend").isDirectory) dir = dir.parentFile
        val python = dir?.resolve("backend/tests/test_function_surface.py")
        assertTrue(
            python != null && python.isFile,
            "backend/tests/test_function_surface.py is gone; without it nothing " +
                "holds the spec table, the reference and the conformance matrix " +
                "to each other",
        )
    }
}
