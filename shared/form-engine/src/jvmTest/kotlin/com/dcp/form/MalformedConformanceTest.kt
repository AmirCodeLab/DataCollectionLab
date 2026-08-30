package com.dcp.form

/**
 * Runs every vector in conformance/malformed against the Kotlin engine,
 * asserting the same reason and location the Python reference produces
 * (backend/tests/test_malformed_conformance.py).
 *
 * A document that compiles on one implementation and is refused on the other is
 * a release blocker, and this is the class of divergence conformance/vectors
 * could not see: every vector there assumes a form that compiled.
 *
 * Spec: Form IR §10.1 (document errors) and §9 (irVersion).
 */

import java.io.File
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlin.test.fail
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.boolean
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized

@RunWith(Parameterized::class)
class MalformedConformanceTest(
    @Suppress("unused") private val name: String,
    private val file: File,
) {

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun vectors(): List<Array<Any>> {
            var dir: File? = File(System.getProperty("user.dir")).absoluteFile
            while (dir != null) {
                val candidate = dir.resolve("conformance/malformed")
                if (candidate.isDirectory) {
                    val files = candidate.listFiles { f -> f.extension == "json" }!!
                        .sortedBy { it.name }
                    check(files.isNotEmpty()) { "no document-shape vectors found" }
                    return files.map { arrayOf(it.nameWithoutExtension, it) }
                }
                dir = dir.parentFile
            }
            error("conformance/malformed not found above ${System.getProperty("user.dir")}")
        }
    }

    @Test
    fun vector() {
        val vector: JsonObject = Json.parseToJsonElement(file.readText()).jsonObject
        assertEquals("malformed", vector.getValue("type").jsonPrimitive.content)
        val where = "${vector.getValue("id").jsonPrimitive.content}: " +
            vector.getValue("description").jsonPrimitive.content

        // The whole pipeline, as a caller runs it: parse, then compile.
        // irVersion survives decoding, so it is CompiledForm that catches it —
        // splitting the two here would let one of them go unchecked.
        val compile = { CompiledForm(FormIr.parse(vector.getValue("form"))) }

        if (!vector.getValue("refused").jsonPrimitive.boolean) {
            compile()
            return
        }

        val raised = try {
            compile()
            fail("$where: compiled, and every engine must refuse it")
        } catch (error: DocumentException) {
            error
        }

        assertEquals(vector.getValue("reason").jsonPrimitive.content, raised.reason, where)
        assertEquals(vector.getValue("where").jsonPrimitive.content, raised.where, where)
    }

    /**
     * DocumentException must stay a CompileException.
     *
     * Nothing in the clients catches DocumentException by name — they refuse a
     * malformed form because it is a compile failure like any other. Break the
     * inheritance and a bad document propagates as an unhandled exception with
     * the gate still in place and still passing its own assertions.
     */
    @Test
    fun `a refusal is a compile error to every caller`() {
        val vector: JsonObject = Json.parseToJsonElement(file.readText()).jsonObject
        if (!vector.getValue("refused").jsonPrimitive.boolean) return

        val raised = try {
            CompiledForm(FormIr.parse(vector.getValue("form")))
            fail("compiled, and every engine must refuse it")
        } catch (error: CompileException) {
            error
        }
        assertTrue(raised is DocumentException)
    }
}
