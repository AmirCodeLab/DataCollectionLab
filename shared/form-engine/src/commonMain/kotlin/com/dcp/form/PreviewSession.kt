package com.dcp.form

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject

/**
 * One open form, driven the way a preview drives it, answering in the JSON
 * `web/src/builder/engine/facade.ts` reads (`PreviewState`, `TraceNode`).
 *
 * The console's preview is the engine, never an approximation of it — item 0's
 * second binding decision. So this class decides nothing: which screen is
 * current, which questions are on it, whether they are relevant, what a row is
 * called, whether a control appears, what blocks finalisation — all of it is
 * read from [FormInstance] and [FormNavigator] and written into JSON. It lives
 * in commonMain so the JVM tests exercise the same code the Wasm build exports.
 *
 * Only strings cross the `@JsExport` boundary on wasmJs, so every method
 * returns a JSON string; a failure is `{"error": "…"}` and leaves the session
 * where it was.
 */
class PreviewSession private constructor(
    private val form: CompiledForm,
    private val instance: FormInstance,
    private val navigator: FormNavigator,
) {
    private val language = form.ir.defaultLanguage ?: form.ir.languages.firstOrNull() ?: "en"

    companion object {
        fun open(irJson: String, today: String): PreviewSession {
            val ir = FormIr.parse(irJson)
            val form = CompiledForm(ir)
            val instance = FormInstance(form, today = today)
            return PreviewSession(form, instance, FormNavigator(instance))
        }
    }

    fun state(): String = stateJson().toString()

    fun set(path: String, valueJson: String): String = guarded {
        if (path !in instance.values) throw CompileException("unknown path: $path")
        val value = formValueFromJson(IrJson.parseToJsonElement(valueJson))
        instance.set(path, value)
    }

    fun next(): String = guarded { navigator.next() }
    fun previous(): String = guarded { navigator.previous() }
    fun enter(repeatId: String, instanceId: String): String = guarded {
        if (!navigator.enter(repeatId, instanceId)) {
            throw CompileException("repeat $repeatId has no instance '$instanceId'")
        }
    }
    fun leave(): String = guarded { navigator.leave() }

    /** §11.3: on success the new row is the open one, on its first relevant screen. */
    fun addRow(repeatId: String): String = guarded {
        val instanceId = instance.addInstance(repeatId)
        navigator.enter(repeatId, instanceId)
    }

    /** §11.3: a position inside the deleted row drops back to the roster. */
    fun deleteRow(repeatId: String, instanceId: String): String = guarded {
        val index = instance.instances[repeatId]?.indexOf(instanceId) ?: -1
        if (index < 0) throw CompileException("repeat $repeatId has no instance '$instanceId'")
        instance.deleteInstance(repeatId, index)
        navigator.refresh()
    }

    fun goToFirstBlocking(): String = guarded { navigator.goToFirstBlocking() }

    fun trace(path: String, key: String): String {
        val node = instance.trace(path, key)
            ?: return error("no `$key` expression at '$path'")
        return node.toJson().toString()
    }

    private inline fun guarded(action: () -> Unit): String = try {
        action()
        state()
    } catch (refused: CompileException) {
        error(refused.message ?: "refused")
    }

    private fun error(message: String): String =
        buildJsonObject { put("error", JsonPrimitive(message)) }.toString()

    // -- the state, read off the engine ------------------------------------

    private fun stateJson(): JsonObject {
        val position = navigator.position
        val screen = navigator.currentScreen
        val repeatId = screen?.repeatId
        val instanceId = position.instanceId
        val inside = position.inside && repeatId != null && instanceId != null
        val shown = if (inside) navigator.currentInstanceScreen else screen
        val (progressPosition, progressTotal) = navigator.progress()

        return buildJsonObject {
            put("screen", screen?.let { screenJson(it) } ?: JsonNull)
            put("inside", if (inside) insideJson(repeatId!!, instanceId!!) else JsonNull)
            put("progress", buildJsonArray { add(JsonPrimitive(progressPosition)); add(JsonPrimitive(progressTotal)) })
            put("hasNext", JsonPrimitive(navigator.hasNext))
            put("hasPrevious", JsonPrimitive(navigator.hasPrevious))
            put(
                "questions",
                JsonArray(
                    shown?.questionIds.orEmpty().mapNotNull { qid ->
                        val path = if (inside) "$repeatId[$instanceId].$qid" else qid
                        questionJson(qid, path)
                    }
                ),
            )
            put("roster", if (!inside && repeatId != null) rosterJson(repeatId) else JsonNull)
            put("canFinalize", JsonPrimitive(navigator.canFinalize))
            put("blockers", JsonArray(navigator.finalizationBlockers.map { JsonPrimitive(it) }))
            put("values", buildJsonObject {
                for ((path, state) in instance.states) put(path, formValueToJson(state.value))
            })
            put("relevant", buildJsonObject {
                for ((path, state) in instance.states) put(path, JsonPrimitive(state.relevant))
            })
            put("valid", buildJsonObject {
                for ((path, state) in instance.states) put(path, JsonPrimitive(state.valid))
            })
        }
    }

    private fun screenJson(screen: FormScreen): JsonElement = buildJsonObject {
        put("index", JsonPrimitive(screen.index))
        put("kind", JsonPrimitive(screen.kind))
        put("groupId", screen.groupId?.let { JsonPrimitive(it) } ?: JsonNull)
        put("sectionId", screen.sectionId?.let { JsonPrimitive(it) } ?: JsonNull)
        put("repeatId", screen.repeatId?.let { JsonPrimitive(it) } ?: JsonNull)
        val titleId = screen.groupId ?: screen.sectionId
        val title = titleId?.let { form.containers[it]?.label?.get(language) }
        put("title", title?.let { JsonPrimitive(it) } ?: JsonNull)
    }

    private fun insideJson(repeatId: String, instanceId: String): JsonElement {
        val (within, across) = navigator.instanceProgress() ?: (0 to 0 to (0 to 0))
        return buildJsonObject {
            put("repeatId", JsonPrimitive(repeatId))
            put("instanceId", JsonPrimitive(instanceId))
            put("rowLabel", JsonPrimitive(instance.summaryLabel(repeatId, instanceId, language)))
            put("within", buildJsonArray { add(JsonPrimitive(within.first)); add(JsonPrimitive(within.second)) })
            put("across", buildJsonArray { add(JsonPrimitive(across.first)); add(JsonPrimitive(across.second)) })
        }
    }

    private fun questionJson(fieldId: String, path: String): JsonElement? {
        val node = form.fields[fieldId]?.node ?: return null
        val state = instance.states[path] ?: return null
        val inside = path != fieldId
        return buildJsonObject {
            put("path", JsonPrimitive(path))
            put("id", JsonPrimitive(fieldId))
            put("dataType", JsonPrimitive(node.dataType))
            // Inside a row the engine's label renderer scopes to the first
            // instance (see CollectionViewModel.questionUi), so the plain label
            // is used there — the same reading the handset makes.
            val label = (if (inside) null else instance.renderedLabel(fieldId, language))
                ?: node.label?.get(language) ?: node.label?.values?.firstOrNull() ?: fieldId
            put("label", JsonPrimitive(label))
            val hint = node.hint?.get(language) ?: node.hint?.values?.firstOrNull()
            put("hint", hint?.let { JsonPrimitive(it) } ?: JsonNull)
            put("required", JsonPrimitive(state.required))
            put("readOnly", JsonPrimitive(state.readOnly))
            put("relevant", JsonPrimitive(state.relevant))
            put("value", formValueToJson(state.value))
            put("valid", JsonPrimitive(state.valid))
            put("errors", JsonArray(state.errors.map { err ->
                buildJsonObject {
                    put("kind", JsonPrimitive(err.kind))
                    put("severity", JsonPrimitive(err.severity))
                    val message = if (err.kind == "required") null
                    else instance.renderedConstraintMessage(fieldId, language)
                    put("message", message?.let { JsonPrimitive(it) } ?: JsonNull)
                }
            }))
            put("choices", JsonArray(instance.choices(fieldId).map { choice ->
                buildJsonObject {
                    put("value", JsonPrimitive(choice.value))
                    put("label", JsonPrimitive(choice.label?.get(language) ?: choice.label?.values?.firstOrNull() ?: choice.value))
                }
            }))
        }
    }

    /**
     * The roster as §11.3 has it: the rows in order, an add control where §2.3
     * permits adding, a delete control where it permits deleting. The same
     * reading of the node the handset's `rosterUi` makes, and `PreviewSessionTest`
     * holds it beside the engine's own refusals so the two cannot drift.
     */
    private fun rosterJson(repeatId: String): JsonElement {
        val node = form.repeats[repeatId] ?: return JsonNull
        val order = instance.instances[repeatId].orEmpty()
        val source = node.rowSource
        val deletable = node.countExpr == null &&
            (source == null || source.allowDelete) &&
            (source != null || order.size > (node.minInstances ?: 0))
        val addable = node.countExpr == null &&
            (source == null || source.allowAdd) &&
            (node.maxInstances?.let { order.size < it } ?: true)
        return buildJsonObject {
            put("repeatId", JsonPrimitive(repeatId))
            put("title", JsonPrimitive(node.label?.get(language) ?: node.label?.values?.firstOrNull() ?: repeatId))
            put("rows", JsonArray(order.map { id ->
                buildJsonObject {
                    put("instanceId", JsonPrimitive(id))
                    put("label", JsonPrimitive(instance.summaryLabel(repeatId, id, language)))
                    put("canDelete", JsonPrimitive(deletable))
                }
            }))
            put("canAdd", JsonPrimitive(addable))
            put("addLabel", instance.renderedAddLabel(repeatId, language)?.let { JsonPrimitive(it) } ?: JsonNull)
        }
    }
}

/** The open sessions, by the handle the console holds. */
object PreviewSessions {
    private val sessions = mutableMapOf<String, PreviewSession>()
    private var counter = 0

    fun open(irJson: String, today: String): String = try {
        val session = PreviewSession.open(irJson, today)
        val handle = "s${++counter}"
        sessions[handle] = session
        buildJsonObject { put("handle", JsonPrimitive(handle)) }.toString()
    } catch (refused: CompileException) {
        failure(refused.message ?: "the form does not compile")
    } catch (malformed: Exception) {
        failure(malformed.message ?: "the document could not be read")
    }

    fun close(handle: String): String {
        sessions.remove(handle)
        return "{}"
    }

    fun with(handle: String, action: (PreviewSession) -> String): String =
        sessions[handle]?.let(action) ?: failure("no open preview '$handle'")

    private fun failure(message: String): String =
        buildJsonObject { put("error", JsonPrimitive(message)) }.toString()
}
