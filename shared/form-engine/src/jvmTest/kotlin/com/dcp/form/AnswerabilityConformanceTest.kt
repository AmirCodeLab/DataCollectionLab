package com.dcp.form

/**
 * Runs every vector in conformance/answerability against the Kotlin check,
 * asserting the same violations the Python reference produces
 * (backend/tests/test_answerability_conformance.py).
 *
 * A form that publishes on one implementation and is refused on the other is a
 * release blocker: a form author would meet a refusal their builder told them
 * was not there. Spec: Form IR §10.2, §2.1, §6.2.
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
class AnswerabilityConformanceTest(
    @Suppress("unused") private val name: String,
    private val file: File,
) {

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun vectors(): List<Array<Any>> {
            var dir: File? = File(System.getProperty("user.dir")).absoluteFile
            while (dir != null) {
                val candidate = dir.resolve("conformance/answerability")
                if (candidate.isDirectory) {
                    val files = candidate.listFiles { f -> f.extension == "json" }!!
                        .sortedBy { it.name }
                    check(files.isNotEmpty()) { "no answerability vectors found" }
                    return files.map { arrayOf(it.nameWithoutExtension, it) }
                }
                dir = dir.parentFile
            }
            error("conformance/answerability not found above ${System.getProperty("user.dir")}")
        }
    }

    @Test
    fun vector() {
        val vector = Json.parseToJsonElement(file.readText()).jsonObject
        assertEquals("answerability", vector.getValue("type").jsonPrimitive.content)
        val label = "${vector.getValue("id").jsonPrimitive.content}: " +
            vector.getValue("description").jsonPrimitive.content

        val ir = FormIr.parse(vector.getValue("form") as JsonObject)
        val expected = vector.getValue("expectedViolations").jsonArray
            .map { it.jsonPrimitive.content }

        assertEquals(expected, checkAnswerability(ir), label)
    }
}
