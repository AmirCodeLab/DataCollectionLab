package com.dcp.form

/**
 * Runs every vector in conformance/sensitivity against the Kotlin check,
 * asserting the same violations the Python reference produces
 * (backend/tests/test_sensitivity_conformance.py).
 *
 * A form that publishes on one implementation and is refused on the other is a
 * release blocker: a form author would meet a refusal their builder told them
 * was not there. Spec: Form IR §10, encryption envelope §5.2.
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
class SensitivityConformanceTest(
    @Suppress("unused") private val name: String,
    private val file: File,
) {

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun vectors(): List<Array<Any>> {
            var dir: File? = File(System.getProperty("user.dir")).absoluteFile
            while (dir != null) {
                val candidate = dir.resolve("conformance/sensitivity")
                if (candidate.isDirectory) {
                    val files = candidate.listFiles { f -> f.extension == "json" }!!
                        .sortedBy { it.name }
                    check(files.isNotEmpty()) { "no sensitivity vectors found" }
                    return files.map { arrayOf(it.nameWithoutExtension, it) }
                }
                dir = dir.parentFile
            }
            error("conformance/sensitivity not found above ${System.getProperty("user.dir")}")
        }
    }

    @Test
    fun vector() {
        val vector: JsonObject = Json.parseToJsonElement(file.readText()).jsonObject
        assertEquals("sensitivity", vector.getValue("type").jsonPrimitive.content)

        val form = CompiledForm(FormIr.parse(vector.getValue("form")))
        val expected = vector.getValue("expectedViolations").jsonArray
            .map { it.jsonPrimitive.content }

        assertEquals(
            expected,
            checkSensitivityPropagation(form),
            vector.getValue("description").jsonPrimitive.content,
        )
    }
}

class SensitivityReferenceTest {

    /**
     * Form IR §4.2. Resolving `members[0].income` to `members` would look
     * harmless — `members` is not a field, so the check would simply find
     * nothing — and would make the whole check blind inside repeats, which is
     * where household income and per-member health data actually live.
     */
    @Test
    fun `a reference resolves to the field it reads, not the repeat`() {
        assertEquals("income", referencedField("income"))
        assertEquals("income", referencedField("members[0].income"))
        assertEquals("income", referencedField("members[.].income"))
        assertEquals("income", referencedField("members[].income"))
        assertEquals("_metadata.start_time", referencedField("_metadata.start_time"))
    }
}
