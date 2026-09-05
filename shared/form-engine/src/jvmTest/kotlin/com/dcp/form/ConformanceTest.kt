package com.dcp.form

/**
 * Runs every conformance vector in conformance/vectors against the Kotlin
 * engine, asserting the same expectations as backend/tests/test_conformance.py.
 * Any divergence from the Python reference is a release blocker.
 */

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
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

/**
 * Runs an operation the spec says must be refused.
 *
 * Asserts the refusal and nothing about its wording: a message is English and
 * the vectors are the contract between two engines. What stops this passing on
 * the wrong refusal is the vector around it — `repeat-009` deletes a valid
 * index that a permitted delete has already exercised two steps earlier, so a
 * bound is the only thing left to refuse it.
 */
fun refuse(instance: FormInstance, op: JsonObject, where: String) {
    val refused =
        try {
            when {
                op.containsKey("addInstance") ->
                    instance.addInstance(op.getValue("addInstance").jsonPrimitive.content)
                op.containsKey("deleteInstance") ->
                    op.getValue("deleteInstance").jsonObject.let { deletion ->
                        instance.deleteInstance(
                            deletion.getValue("repeat").jsonPrimitive.content,
                            deletion.getValue("index").jsonPrimitive.content.toInt(),
                        )
                    }
                else -> error("$where: refuse step names no operation: ${op.keys}")
            }
            false
        } catch (expected: CompileException) {
            true
        }
    assertTrue(refused, "$where: expected ${op.keys.first()} to be refused, it succeeded")
}

/**
 * Dataset rows from a vector's `datasets` block, as the source hands them back.
 *
 * Rows are plain JSON — text, numbers, nulls — and become [FormValue] the same
 * way an answer does, so an engine cannot be right about a filter only because
 * the harness typed a cell for it.
 */
fun datasetsOf(vector: JsonObject): RecordingDatasetSource = RecordingDatasetSource(
    vector["datasets"]?.jsonObject.orEmpty().mapValues { (_, rows) ->
        rows.jsonArray.map { row ->
            row.jsonObject.mapValues { (_, cell) -> formValueFromJson(cell) }
        }
    },
)

/** One question the engine asked a dataset source, and how it was answered. */
data class SourceCall(
    val dataset: String,
    val selector: Map<String, FormValue>,
    val equals: Pair<String, FormValue>?,
    val returned: Int,
)

/**
 * An in-memory source that remembers what the engine asked it for.
 *
 * The vectors' `selector` and `candidates` expectations are assertions about
 * the **question the engine asked**, not about the answer it ended up with, and
 * the difference is the entire performance contract (§3.2). Reading them off
 * the engine's own output instead was watched to be useless: an engine that
 * asked for every row and filtered them itself produced the right selector, the
 * right list and the right count, and passed. It is the source that has to be
 * the witness.
 */
class RecordingDatasetSource(
    datasets: Map<String, List<Map<String, FormValue>>>,
) : DatasetSource {
    private val inner = InMemoryDatasetSource(datasets)
    val calls = mutableListOf<SourceCall>()

    override fun rows(
        dataset: String,
        selector: Map<String, FormValue>,
        equals: Pair<String, FormValue>?,
    ): List<Map<String, FormValue>> {
        val found = inner.rows(dataset, selector, equals)
        calls.add(SourceCall(dataset, selector, equals, found.size))
        return found
    }
}

/**
 * Vectors address instances positionally, as everywhere else in this format. A
 * minted id (`i3`) never appears in one: it is an engine's private counter, and
 * pinning it would make the format assert something §2.3 does not promise. The
 * POSITION an engine holds is an id — that is §11.3's whole point — so the
 * translation happens here, once, at the boundary.
 */
fun instanceIdAt(instance: FormInstance, repeatId: String, index: Int): String =
    instance.instances.getValue(repeatId)[index]

/** A vector's position spec as a [Position]: an int, an object, or null. */
fun wantPosition(
    instance: FormInstance,
    plan: ScreenPlan,
    spec: kotlinx.serialization.json.JsonElement?,
): Position? {
    if (spec == null || spec is JsonNull) return null
    if (spec is JsonPrimitive) return Position(spec.content.toInt())
    val obj = spec.jsonObject
    val screen = plan[obj.getValue("screen").jsonPrimitive.content.toInt()]
    val instanceIndex = obj["instanceIndex"] ?: return Position(screen.index)
    val repeatId = requireNotNull(screen.repeatId) {
        "position names screen ${screen.index} as a repeat screen; it is not"
    }
    return Position(
        screen.index,
        instanceIdAt(instance, repeatId, instanceIndex.jsonPrimitive.content.toInt()),
        obj.getValue("instanceScreen").jsonPrimitive.content.toInt(),
    )
}

fun runSteps(
    vector: JsonObject,
    check: ((FormInstance, JsonObject, Int, Position) -> Unit)? = null,
): FormInstance {
    val compiled = CompiledForm(FormIr.parse(vector.getValue("form")))

    val ctx = vector["context"]?.jsonObject
    val today = ctx?.get("today")?.jsonPrimitive?.content ?: "2026-08-28"
    val now = ctx?.get("now")?.jsonPrimitive?.content ?: "${today}T00:00:00"

    val instance = FormInstance(compiled, today = today, now = now, datasets = datasetsOf(vector))

    val plan = compiled.screens
    // The position a runtime holds (§11.2). It starts where a client opens the
    // form: the first relevant screen.
    var position = Position(nextScreen(plan, instance, -1) ?: 0)

    vector.getValue("steps").jsonArray.forEachIndexed { i, stepElement ->
        val step = stepElement.jsonObject
        val where = "${vector.getValue("id").jsonPrimitive.content} step $i"
        step["addInstance"]?.jsonPrimitive?.content?.let { repeatId ->
            // §11.3: on success the new instance becomes the open one and the
            // position becomes its first relevant instance screen. That rule is
            // `enterInstance` — the same function a client calls when the
            // enumerator taps a row — so applying it here is the rule, not the
            // harness's own idea of one.
            val added = instance.addInstance(repeatId)
            position = enterInstance(plan, instance, repeatId, added)
        }
        step["deleteInstance"]?.jsonObject?.let { deletion ->
            instance.deleteInstance(
                deletion.getValue("repeat").jsonPrimitive.content,
                deletion.getValue("index").jsonPrimitive.content.toInt(),
            )
        }
        step["refuse"]?.jsonObject?.let { op ->
            refuse(instance, op, where)
        }
        step["set"]?.jsonObject?.let { answers ->
            instance.setMany(answers.mapValues { formValueFromJson(it.value) })
        }
        step["goToScreen"]?.jsonPrimitive?.let { target ->
            position = Position(target.content.toInt())
        }
        step["enterInstance"]?.jsonObject?.let { spec ->
            val repeatId = spec.getValue("repeat").jsonPrimitive.content
            position = enterInstance(
                plan,
                instance,
                repeatId,
                instanceIdAt(instance, repeatId, spec.getValue("index").jsonPrimitive.content.toInt()),
            )
        }
        step["navigate"]?.jsonPrimitive?.content?.let { direction ->
            val moved =
                if (direction == "next") nextPosition(plan, instance, position)
                else previousPosition(plan, instance, position)
            assertTrue(
                moved != null,
                "$where: navigate $direction yielded nothing from $position. A " +
                    "vector asserting that uses the next/previous probes, not a move",
            )
            position = moved!!
        }
        step["expect"]?.jsonObject?.let { expect ->
            // §11.3: an instance that ceased to exist drops the position back
            // to its repeat screen. Applied on every read rather than only
            // after a delete, because a countExpr shrink can discard it too and
            // no step verb announces that.
            position = resolvePosition(plan, instance, position)
            check?.invoke(instance, expect, i, position)
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
        runSteps(vector) { instance, expect, stepIndex, position ->
            checkExpectations(instance, expect, vectorId, stepIndex, position)
        }
    }

    /**
     * Resolve this field's list and return the one call it made to the source.
     *
     * Exactly one: resolving a list is one question, and an engine that asked
     * twice — once to narrow and once to check — would be doing on a handset
     * the thing §3.2 exists to stop.
     */
    private fun resolutionCall(instance: FormInstance, path: String, where: String): SourceCall {
        val source = instance.datasets as RecordingDatasetSource
        source.calls.clear()
        instance.choices(path)
        assertEquals(
            1,
            source.calls.size,
            "$where: resolving $path made ${source.calls.size} calls to the dataset " +
                "source; §3.2 is one question, asked once",
        )
        return source.calls.first()
    }

    private fun checkExpectations(
        instance: FormInstance,
        expect: JsonObject,
        vectorId: String,
        stepIndex: Int,
        position: Position,
    ) {
        val where = "$vectorId step $stepIndex"

        // Vectors address repeat fields positionally; resolve to canonical paths.
        fun state(path: String): FieldState = instance.states.getValue(instance.canonical(path))

        expect["relevant"]?.jsonObject?.forEach { (path, want) ->
            val got = state(path).relevant
            assertEquals(want.jsonPrimitive.content.toBoolean(), got, "$where: relevant[$path]")
        }

        expect["values"]?.jsonObject?.forEach { (path, wantJson) ->
            val want = formValueFromJson(wantJson)
            val got = state(path).value
            assertTrue(
                formValuesEqual(got, want),
                "$where: values[$path] expected $want, got $got",
            )
        }

        expect["required"]?.jsonObject?.forEach { (path, want) ->
            val got = state(path).required
            assertEquals(want.jsonPrimitive.content.toBoolean(), got, "$where: required[$path]")
        }

        expect["valid"]?.jsonObject?.forEach { (path, want) ->
            val got = state(path).valid
            assertEquals(want.jsonPrimitive.content.toBoolean(), got, "$where: valid[$path]")
        }

        expect["errors"]?.jsonObject?.forEach { (path, wantKinds) ->
            val got = state(path).errors.map { it.kind }
            val want = wantKinds.jsonArray.map { it.jsonPrimitive.content }
            assertEquals(want, got, "$where: errors[$path]")
        }

        expect["instanceCount"]?.jsonObject?.forEach { (repeatId, want) ->
            val got = instance.instanceCount(repeatId)
            assertEquals(want.jsonPrimitive.content.toInt(), got, "$where: instanceCount[$repeatId]")
        }

        // --- interpolated text (§7.1) -------------------------------------

        expect["renderedLabels"]?.jsonObject?.forEach { (path, want) ->
            want.jsonObject.forEach { (language, wantText) ->
                assertEquals(
                    wantText.jsonPrimitive.content,
                    instance.renderedLabel(path, language),
                    "$where: renderedLabels[$path][$language]",
                )
            }
        }

        expect["renderedMessages"]?.jsonObject?.forEach { (path, want) ->
            want.jsonObject.forEach { (language, wantText) ->
                assertEquals(
                    wantText.jsonPrimitive.content,
                    instance.renderedConstraintMessage(path, language),
                    "$where: renderedMessages[$path][$language]",
                )
            }
        }

        expect["dependsOn"]?.jsonObject?.forEach { (path, want) ->
            // Asserted directly, not inferred from a re-render. A label that
            // happened to be recomputed for another reason would pass a render
            // check; this is the edge itself.
            assertEquals(
                want.jsonArray.map { it.jsonPrimitive.content }.sorted(),
                instance.form.fields.getValue(path).dependsOn.sorted(),
                "$where: dependsOn[$path]",
            )
        }

        // --- dataset-backed choice lists (§3.2) ---------------------------
        //
        // Three assertions and not one, deliberately. `choices` alone would
        // pass on an engine that scanned the whole dataset to build the same
        // list, and on a handset those are not the same engine. `selector`
        // compares the decomposition and `candidates` compares how many rows
        // the source was asked to hand back, so a change that quietly stops
        // narrowing fails here while the answer stays right.

        expect["choices"]?.jsonObject?.forEach { (path, want) ->
            val got = instance.choices(path).map { it.value }
            assertEquals(want.jsonArray.map { it.jsonPrimitive.content }, got, "$where: choices[$path]")
        }

        expect["labels"]?.jsonObject?.forEach { (path, want) ->
            val got = instance.choices(path).map { it.label ?: emptyMap() }
            val wanted = want.jsonArray.map { entry ->
                entry.jsonObject.mapValues { it.value.jsonPrimitive.content }
            }
            assertEquals(wanted, got, "$where: labels[$path]")
        }

        expect["selector"]?.jsonObject?.forEach { (path, want) ->
            val got = resolutionCall(instance, path, where).selector
            val wanted = want.jsonObject.mapValues { formValueFromJson(it.value) }
            assertEquals(
                wanted,
                got,
                "$where: selector[$path] — this is what the source was asked for, " +
                    "not what the engine computed",
            )
        }

        expect["selectorOrder"]?.jsonObject?.forEach { (path, want) ->
            val got = instance.form.fields.getValue(path).choiceQuery!!.selector.keys.toList()
            assertEquals(want.jsonArray.map { it.jsonPrimitive.content }, got, "$where: selectorOrder[$path]")
        }

        expect["candidates"]?.jsonObject?.forEach { (path, want) ->
            val got = resolutionCall(instance, path, where).returned
            assertEquals(
                want.jsonPrimitive.content.toInt(),
                got,
                "$where: candidates[$path] — rows back from the source. The engine " +
                    "asked a different question, which is the performance contract " +
                    "(§3.2) and not only a count",
            )
        }

        expect["scans"]?.jsonObject?.forEach { (path, want) ->
            val got = instance.form.fields.getValue(path).choiceQuery!!.scans
            assertEquals(want.jsonPrimitive.content.toBoolean(), got, "$where: scans[$path]")
        }

        expect["formValid"]?.let { want ->
            assertEquals(want.jsonPrimitive.content.toBoolean(), instance.isValid, "$where: formValid")
        }

        expect["screens"]?.jsonObject?.let { screens ->
            val plan = instance.form.screens

            fun idOrNull(element: kotlinx.serialization.json.JsonElement): String? =
                if (element is JsonNull) null else element.jsonPrimitive.content

            fun indexOrNull(element: kotlinx.serialization.json.JsonElement): Int? =
                if (element is JsonNull) null else element.jsonPrimitive.content.toInt()

            screens["count"]?.let { want ->
                assertEquals(want.jsonPrimitive.content.toInt(), plan.size, "$where: screens.count")
            }
            screens["questions"]?.jsonObject?.forEach { (idx, want) ->
                assertEquals(
                    want.jsonArray.map { it.jsonPrimitive.content },
                    plan[idx.toInt()].questionIds,
                    "$where: screens.questions[$idx]",
                )
            }
            screens["groups"]?.jsonObject?.forEach { (idx, want) ->
                assertEquals(idOrNull(want), plan[idx.toInt()].groupId, "$where: screens.groups[$idx]")
            }
            screens["sections"]?.jsonObject?.forEach { (idx, want) ->
                assertEquals(idOrNull(want), plan[idx.toInt()].sectionId, "$where: screens.sections[$idx]")
            }
            screens["relevant"]?.jsonArray?.let { want ->
                assertEquals(
                    want.map { it.jsonPrimitive.content.toInt() },
                    relevantScreens(plan, instance),
                    "$where: screens.relevant",
                )
            }
            screens["next"]?.jsonObject?.forEach { (from, want) ->
                assertEquals(
                    indexOrNull(want),
                    nextScreen(plan, instance, from.toInt()),
                    "$where: screens.next[$from]",
                )
            }
            screens["previous"]?.jsonObject?.forEach { (from, want) ->
                assertEquals(
                    indexOrNull(want),
                    previousScreen(plan, instance, from.toInt()),
                    "$where: screens.previous[$from]",
                )
            }
            screens["canFinalize"]?.let { want ->
                assertEquals(
                    want.jsonPrimitive.content.toBoolean(),
                    canFinalize(instance),
                    "$where: screens.canFinalize",
                )
            }
            screens["blocking"]?.jsonArray?.let { want ->
                assertEquals(
                    // Vectors address repeat fields positionally, as elsewhere.
                    want.map { instance.canonical(it.jsonPrimitive.content) },
                    blockingFields(instance),
                    "$where: screens.blocking",
                )
            }
            screens["firstBlocking"]?.let { want ->
                assertEquals(
                    wantPosition(instance, plan, want),
                    firstBlockingPosition(plan, instance),
                    "$where: screens.firstBlocking",
                )
            }

            // --- repeats (§11.3) ------------------------------------------

            screens["kinds"]?.jsonObject?.forEach { (idx, want) ->
                assertEquals(
                    want.jsonPrimitive.content,
                    plan[idx.toInt()].kind,
                    "$where: screens.kinds[$idx]",
                )
            }
            screens["repeats"]?.jsonObject?.forEach { (idx, want) ->
                assertEquals(
                    idOrNull(want),
                    plan[idx.toInt()].repeatId,
                    "$where: screens.repeats[$idx]",
                )
            }
            screens["instancePlan"]?.jsonObject?.forEach { (repeatId, want) ->
                val inner = plan.instancePlans[repeatId]
                assertTrue(
                    inner != null,
                    "$where: instancePlan[$repeatId] — the plan has no such repeat",
                )
                want.jsonObject["count"]?.let { count ->
                    assertEquals(
                        count.jsonPrimitive.content.toInt(),
                        inner!!.size,
                        "$where: instancePlan[$repeatId].count",
                    )
                }
                want.jsonObject["questions"]?.jsonObject?.forEach { (idx, wantQ) ->
                    assertEquals(
                        wantQ.jsonArray.map { it.jsonPrimitive.content },
                        inner!![idx.toInt()].questionIds,
                        "$where: instancePlan[$repeatId].questions[$idx]",
                    )
                }
            }
            screens["instanceRelevant"]?.jsonObject?.forEach { (repeatId, byInstance) ->
                byInstance.jsonObject.forEach { (instIdx, want) ->
                    val id = instanceIdAt(instance, repeatId, instIdx.toInt())
                    assertEquals(
                        want.jsonArray.map { it.jsonPrimitive.content.toInt() },
                        relevantInstanceScreens(plan, instance, repeatId, id),
                        "$where: instanceRelevant[$repeatId][$instIdx]",
                    )
                }
            }
            screens["position"]?.let { want ->
                assertEquals(
                    wantPosition(instance, plan, want),
                    position,
                    "$where: screens.position",
                )
            }
            screens["progress"]?.jsonArray?.let { want ->
                val got = progress(plan, instance, position)
                assertEquals(
                    want.map { it.jsonPrimitive.content.toInt() },
                    listOf(got.first, got.second),
                    "$where: screens.progress — a repeat counts once, whatever it " +
                        "holds (§11.2)",
                )
            }
            screens["instanceProgress"]?.let { want ->
                val got = instanceProgress(plan, instance, position)
                if (want is JsonNull) {
                    assertEquals(
                        null,
                        got,
                        "$where: instanceProgress expected null (not inside an instance)",
                    )
                } else {
                    assertTrue(got != null, "$where: instanceProgress expected a pair, got null")
                    assertEquals(
                        want.jsonObject.getValue("within").jsonArray
                            .map { it.jsonPrimitive.content.toInt() },
                        listOf(got!!.first.first, got.first.second),
                        "$where: instanceProgress.within",
                    )
                    assertEquals(
                        want.jsonObject.getValue("across").jsonArray
                            .map { it.jsonPrimitive.content.toInt() },
                        listOf(got.second.first, got.second.second),
                        "$where: instanceProgress.across",
                    )
                }
            }
            screens["nextFrom"]?.jsonArray?.forEach { probe ->
                val from = wantPosition(instance, plan, probe.jsonObject.getValue("from"))!!
                assertEquals(
                    wantPosition(instance, plan, probe.jsonObject["to"]),
                    nextPosition(plan, instance, from),
                    "$where: next from $from",
                )
            }
            screens["previousFrom"]?.jsonArray?.forEach { probe ->
                val from = wantPosition(instance, plan, probe.jsonObject.getValue("from"))!!
                assertEquals(
                    wantPosition(instance, plan, probe.jsonObject["to"]),
                    previousPosition(plan, instance, from),
                    "$where: previous from $from",
                )
            }
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
