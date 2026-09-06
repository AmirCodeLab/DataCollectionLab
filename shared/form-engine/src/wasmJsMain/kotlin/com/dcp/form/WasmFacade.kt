package com.dcp.form

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject

/*
 * SPIKE FACADE (2026-09-06). Not a supported API.
 *
 * This exists to answer one question honestly — what does the engine cost in a
 * browser — and it cannot be answered without it. A Kotlin/Wasm library with
 * nothing exported is optimised to 490 bytes, because binaryen is entitled to
 * delete a module nobody can call. A size measured that way is a measurement
 * of the export list and not of the engine.
 *
 * The shape is the one a console would actually use: JSON in, JSON out. Only
 * primitives and strings cross the @JsExport boundary on wasmJs, and the IR is
 * already JSON on the wire, so this is not a concession to the spike — it is
 * the same boundary `POST /forms/compile` has.
 */

private val json = Json { ignoreUnknownKeys = true }

/*
 * Top-level functions, not an object: on wasmJs `@JsExport` is applicable to
 * functions only. A JS-facing facade is therefore a flat list of names, which
 * is a real constraint on how a console would consume this.
 */

/** Compile, and report the screen plan and warnings the console renders. */
@JsExport
fun previewCompile(irJson: String): String {
    val ir = FormIr.parse(json.parseToJsonElement(irJson) as JsonObject)
    val form = CompiledForm(ir)
    val plan = buildScreenPlan(ir)
    val screens = plan.screens.joinToString(",") { screen ->
        """{"index":${screen.index},"kind":"${screen.kind}","questionIds":""" +
            screen.questionIds.joinToString(",", "[", "]") { "\"$it\"" } + "}"
    }
    val warnings = form.warnings.joinToString(",") { "\"${it.replace("\"", "\\\"")}\"" }
    return """{"screens":[$screens],"warnings":[$warnings]}"""
}

/**
     * Answer a question and report what moved: relevance, validity, and the
     * roster labels. This is the call a preview makes on every keystroke, so
     * it is the one that decides whether a wasm preview feels like an engine
     * or like a network round trip.
     */
@JsExport
fun previewEvaluate(irJson: String, path: String, value: String, today: String): String {
    val ir = FormIr.parse(json.parseToJsonElement(irJson) as JsonObject)
    val form = CompiledForm(ir)
    val instance = FormInstance(form, today = today)
    instance.recalculate()
    if (path.isNotEmpty()) instance.set(path, FormValue.Text(value))
    val relevant = form.order.joinToString(",") { id ->
        "\"$id\":${instance.states[id]?.relevant ?: true}"
    }
    val labels = form.repeats.keys.joinToString(",") { repeatId ->
        val rows = instance.instances.getValue(repeatId).joinToString(",") { iid ->
            "\"${instance.summaryLabel(repeatId, iid, ir.defaultLanguage ?: "en").replace("\"", "\\\"")}\""
        }
        "\"$repeatId\":[$rows]"
    }
    return """{"relevant":{$relevant},"summaryLabels":{$labels}}"""
}

/** The publish-time sensitivity check, so the builder can show it early. */
@JsExport
fun previewSensitivity(irJson: String): String {
    val ir = FormIr.parse(json.parseToJsonElement(irJson) as JsonObject)
    val violations = checkSensitivityPropagation(CompiledForm(ir))
    return violations.joinToString(",", "[", "]") { "\"${it.replace("\"", "\\\"")}\"" }
}
