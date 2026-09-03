package com.dcp.form

/**
 * Every §4.3 function and operator, against every value shape.
 *
 * The Kotlin half of `conformance/functions`; `backend/tests/test_function_conformance.py`
 * runs the same files and any divergence is a release blocker.
 *
 * `ConformanceTest` runs chosen cases — somebody thought of a construct and
 * wrote it down. Nothing in the corpus had ever put text where a number
 * belongs, because until dataset columns existed nothing could, and when the
 * sweep was finally run **762 of 1,395 probes disagreed** between the two
 * engines (break 46). This set is the cross product rather than a selection,
 * and its whole value is that nobody picked the cases.
 *
 * Form IR §4.7 is the rule it encodes: an argument that is not of its declared
 * type is null, `eq`/`ne` are total across types, `concat` renders rather than
 * refuses, and evaluation raises for exactly one reason — integer overflow.
 */

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.fail

private fun functionMatrixDir(): File {
    var dir: File? = File(System.getProperty("user.dir")).absoluteFile
    while (dir != null) {
        val candidate = dir.resolve("conformance/functions")
        if (candidate.isDirectory) return candidate
        dir = dir.parentFile
    }
    error("conformance/functions not found above ${System.getProperty("user.dir")}")
}

@RunWith(Parameterized::class)
class FunctionConformanceTest(
    @Suppress("unused") private val name: String,
    private val file: File,
) {

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun files(): List<Array<Any>> {
            val found = functionMatrixDir().listFiles { f -> f.extension == "json" }!!
                .sortedBy { it.name }
            check(found.isNotEmpty()) { "no function matrix files found" }
            return found.map { arrayOf(it.nameWithoutExtension, it) }
        }
    }

    @Test
    fun probes() {
        val document = Json.parseToJsonElement(file.readText()).jsonObject
        val today = document["context"]?.jsonObject?.get("today")?.jsonPrimitive?.content
            ?: "2026-08-28"
        val ctx = EvalContext(values = emptyMap(), today = today, now = "${today}T00:00:00")

        val probes = document.getValue("probes").jsonArray
        assertTrue(probes.isNotEmpty(), "${file.name} holds no probes; an empty file proves nothing")

        for (element in probes) {
            val probe = element.jsonObject
            val where = probe.getValue("id").jsonPrimitive.content
            val expr = exprFromJson(probe.getValue("expr"))

            if (probe.containsKey("raises")) {
                // The single exception §4.7 allows, asserted rather than
                // assumed: "evaluation is total apart from integer overflow" is
                // a claim this suite makes, not one it makes about itself.
                val threw = try {
                    Evaluator.evaluate(expr, ctx); false
                } catch (_: EvaluationException) {
                    true
                }
                assertTrue(threw, "$where: expected an integer overflow and got a value")
                continue
            }

            val got = try {
                Evaluator.evaluate(expr, ctx)
            } catch (e: Throwable) {
                fail(
                    "$where: evaluation threw ${e::class.simpleName}: ${e.message}. " +
                        "§4.7 makes evaluation total apart from integer overflow — an " +
                        "expression evaluated on every keystroke must not be able to " +
                        "stop a form mid-interview."
                )
            }
            val want = formValueFromJson(probe.getValue("expect"))
            assertEquals(want, got, "$where")
        }
    }

    /**
     * The other half of the mirror in `test_function_conformance.py`.
     *
     * The suites guard notices a CI step that stops running a suite. It cannot
     * notice a test *file* being deleted — the suite simply reports one fewer
     * and stays green — so the two halves point at each other.
     */
    @Test
    fun theOtherHalfOfThisMirrorStillExists() {
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null && !dir.resolve("backend").isDirectory) dir = dir.parentFile
        val python = dir?.resolve("backend/tests/test_function_conformance.py")
        assertTrue(
            python != null && python.isFile,
            "backend/tests/test_function_conformance.py is gone; this set would then " +
                "be one engine agreeing with itself",
        )
    }
}
