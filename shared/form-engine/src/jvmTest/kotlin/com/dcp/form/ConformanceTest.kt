package com.dcp.form

/**
 * Runs every conformance vector in conformance/vectors against the Kotlin
 * engine, asserting the same expectations as backend/tests/test_conformance.py.
 * Any divergence from the Python reference is a release blocker.
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

/** Walks up from the working directory to the repo root holding the vectors. */
fun vectorDir(): File {
    var dir: File? = File(System.getProperty("user.dir")).absoluteFile
    while (dir != null) {
        val candidate = dir.resolve("conformance/vectors")
        if (candidate.isDirectory) return candidate
        dir = dir.parentFile
    }
    error("conformance/vectors not found above ${System.getProperty("user.dir")}")
}

fun loadVector(file: File): JsonObject = Json.parseToJsonElement(file.readText()).jsonObject

fun runSteps(vector: JsonObject, check: ((FormInstance, JsonObject, Int) -> Unit)? = null): FormInstance {
    val compiled = CompiledForm(FormIr.parse(vector.getValue("form")))

    val ctx = vector["context"]?.jsonObject
    val today = ctx?.get("today")?.jsonPrimitive?.content ?: "2026-08-28"
    val now = ctx?.get("now")?.jsonPrimitive?.content ?: "${today}T00:00:00"

    val instance = FormInstance(compiled, today = today, now = now)

    vector.getValue("steps").jsonArray.forEachIndexed { i, stepElement ->
        val step = stepElement.jsonObject
        step["set"]?.jsonObject?.let { answers ->
            instance.setMany(answers.mapValues { formValueFromJson(it.value) })
        }
        step["expect"]?.jsonObject?.let { expect ->
            check?.invoke(instance, expect, i)
        }
    }
    return instance
}

@RunWith(Parameterized::class)
class ConformanceTest(@Suppress("unused") private val name: String, private val file: File) {

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun vectors(): List<Array<Any>> {
            val files = vectorDir().listFiles { f -> f.extension == "json" }!!.sortedBy { it.name }
            check(files.isNotEmpty()) { "no conformance vectors found" }
            return files.map { arrayOf(it.nameWithoutExtension, it) }
        }
    }

    @Test
    fun vector() {
        val vector = loadVector(file)
        val vectorId = vector.getValue("id").jsonPrimitive.content
        runSteps(vector) { instance, expect, stepIndex ->
            checkExpectations(instance, expect, vectorId, stepIndex)
        }
    }

    private fun checkExpectations(
        instance: FormInstance,
        expect: JsonObject,
        vectorId: String,
        stepIndex: Int,
    ) {
        val where = "$vectorId step $stepIndex"

        expect["relevant"]?.jsonObject?.forEach { (path, want) ->
            val got = instance.states.getValue(path).relevant
            assertEquals(want.jsonPrimitive.content.toBoolean(), got, "$where: relevant[$path]")
        }

        expect["values"]?.jsonObject?.forEach { (path, wantJson) ->
            val want = formValueFromJson(wantJson)
            val got = instance.states.getValue(path).value
            assertTrue(
                formValuesEqual(got, want),
                "$where: values[$path] expected $want, got $got",
            )
        }

        expect["required"]?.jsonObject?.forEach { (path, want) ->
            val got = instance.states.getValue(path).required
            assertEquals(want.jsonPrimitive.content.toBoolean(), got, "$where: required[$path]")
        }

        expect["valid"]?.jsonObject?.forEach { (path, want) ->
            val got = instance.states.getValue(path).valid
            assertEquals(want.jsonPrimitive.content.toBoolean(), got, "$where: valid[$path]")
        }

        expect["errors"]?.jsonObject?.forEach { (path, wantKinds) ->
            val got = instance.states.getValue(path).errors.map { it.kind }
            val want = wantKinds.jsonArray.map { it.jsonPrimitive.content }
            assertEquals(want, got, "$where: errors[$path]")
        }

        expect["formValid"]?.let { want ->
            assertEquals(want.jsonPrimitive.content.toBoolean(), instance.isValid, "$where: formValid")
        }
    }

    /**
     * Value equality with the same looseness as the Python reference test,
     * where `13 == 13.0` holds: integers and decimals compare numerically.
     */
    private fun formValuesEqual(got: FormValue, want: FormValue): Boolean {
        if (got is FormValue.Sequence && want is FormValue.Sequence) {
            return got.items.size == want.items.size &&
                got.items.zip(want.items).all { (g, w) -> formValuesEqual(g, w) }
        }
        val gotNum = numberOrNull(got)
        val wantNum = numberOrNull(want)
        if (gotNum != null && wantNum != null) return gotNum == wantNum
        return got == want
    }

    private fun numberOrNull(v: FormValue): Double? = when (v) {
        is FormValue.Integer -> v.value.toDouble()
        is FormValue.Decimal -> v.value
        else -> null
    }
}

class DeterminismPairTest {

    /**
     * determinism-001 and -002 apply the same answers in opposite orders and
     * must end in identical state.
     */
    @Test
    fun determinismPairsAgree() {
        val dir = vectorDir()

        fun run(name: String): Map<String, FormValue> =
            runSteps(loadVector(dir.resolve(name))).snapshot().mapValues { it.value.value }

        assertEquals(run("determinism-001.json"), run("determinism-002.json"))
    }
}
