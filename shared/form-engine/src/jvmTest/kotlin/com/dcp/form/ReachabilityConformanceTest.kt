package com.dcp.form

/**
 * Runs every vector in conformance/reachability against the Kotlin check,
 * asserting the same violations, warnings and "never shown" list the Python
 * reference produces (backend/tests/test_reachability_conformance.py).
 *
 * A form that publishes on one implementation and is refused on the other is a
 * release blocker: a form author would meet a refusal their builder told them
 * was not there. Spec: Form IR §10.2, §10.3, §11.1.
 */

import java.io.File
import kotlin.test.assertEquals
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

@RunWith(Parameterized::class)
class ReachabilityConformanceTest(
    @Suppress("unused") private val name: String,
    private val file: File,
) {

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun vectors(): List<Array<Any>> {
            var dir: File? = File(System.getProperty("user.dir")).absoluteFile
            while (dir != null) {
                val candidate = dir.resolve("conformance/reachability")
                if (candidate.isDirectory) {
                    val files = candidate.listFiles { f -> f.extension == "json" }!!
                        .sortedBy { it.name }
                    check(files.isNotEmpty()) { "no reachability vectors found" }
                    return files.map { arrayOf(it.nameWithoutExtension, it) }
                }
                dir = dir.parentFile
            }
            error("conformance/reachability not found above ${System.getProperty("user.dir")}")
        }
    }

    private fun strings(vector: JsonObject, key: String): List<String> =
        vector.getValue(key).jsonArray.map { it.jsonPrimitive.content }

    @Test
    fun vector() {
        val vector: JsonObject = Json.parseToJsonElement(file.readText()).jsonObject
        assertEquals("reachability", vector.getValue("type").jsonPrimitive.content)
        val label = vector.getValue("description").jsonPrimitive.content

        val ir = FormIr.parse(vector.getValue("form"))
        assertEquals(strings(vector, "expectedViolations"), checkReachability(ir), label)
        assertEquals(strings(vector, "expectedWarnings"), CompiledForm(ir).warnings, label)
        assertEquals(strings(vector, "expectedNeverShown"), neverShownQuestions(ir), label)
    }
}
