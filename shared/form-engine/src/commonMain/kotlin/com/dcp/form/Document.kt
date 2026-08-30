package com.dcp.form

/**
 * Document-shape validation — Form IR §10.1, run before anything else.
 *
 * This MUST refuse exactly what the Python reference refuses, with the same
 * `reason` and `where`, for every vector in conformance/malformed. It mirrors
 * backend/app/modules/form_engine/document.py.
 *
 * Why it exists when kotlinx would already refuse most of this. The
 * deserialiser does reject a document missing `formId` — but it rejects it with
 * a message about a Kotlin field of a Kotlin class, and it produces no reason
 * code at all. "Both engines refuse it" is a weaker contract than the one this
 * project holds itself to: rule 2 says a vector must pass identically on both
 * engines, and two engines that refuse the same document for reasons neither
 * can state in the same words have not been shown to agree about anything
 * except the outcome. It is also what a form builder needs — `missing_field` at
 * `children[0].id` is actionable; a serialization stack trace is not.
 *
 * So the check runs over the raw JSON, before decoding, and the deserialiser
 * becomes the backstop it should be rather than the gate.
 */

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.intOrNull

private val NODE_TYPES = listOf("question", "group", "repeat")

/**
 * A §10.1 document error: this is not a Form IR document.
 *
 * A [CompileException] subclass on purpose, so every caller that already
 * refuses a form on a compile failure refuses this too without being changed.
 * [reason] and [where] are for callers that want to say more than "invalid".
 */
class DocumentException(
    val reason: String,
    val where: String,
    val detail: String,
) : CompileException(if (where.isEmpty()) detail else "$where: $detail")

/** Raise [DocumentException] unless [element] is structurally a Form IR document. */
fun checkDocument(element: JsonElement) {
    val document = element as? JsonObject
        ?: throw DocumentException("not_an_object", "", "a form must be a JSON object")

    checkIrVersion(requireString(document, "irVersion", "", "irVersion"))
    requireString(document, "formId", "", "formId")
    requireInt(document, "version", "", "version")

    // Absent `children` is a form with no nodes, which compiles. That is not
    // the same as `children` present holding something that is not an array.
    document["children"]?.let { checkChildren(it, "children") }
}

private fun checkChildren(children: JsonElement, where: String) {
    val array = children as? JsonArray
        ?: throw DocumentException("wrong_type", where, "children must be an array")

    array.forEachIndexed { index, child ->
        val at = "$where[$index]"
        val node = child as? JsonObject
            ?: throw DocumentException("not_an_object", at, "a node must be a JSON object")

        val nodeType = requireString(node, "type", "$at.", "type")
        if (nodeType !in NODE_TYPES) {
            throw DocumentException(
                "unknown_node_type",
                "$at.type",
                "'$nodeType' is not a node type. Expected one of ${NODE_TYPES.joinToString(", ")}.",
            )
        }

        requireString(node, "id", "$at.", "id")

        if (nodeType == "question") {
            // A question with no dataType has no value representation (§2.1),
            // so there is nothing for the runtime to store or validate.
            requireString(node, "dataType", "$at.", "dataType")
        } else {
            node["children"]?.let { checkChildren(it, "$at.children") }
        }
    }
}

private fun requireString(node: JsonObject, key: String, where: String, label: String): String {
    val value = node[key]
        ?: throw DocumentException("missing_field", "$where$key", "$label is required")
    val primitive = value as? JsonPrimitive
    if (primitive == null || !primitive.isString) {
        throw DocumentException("wrong_type", "$where$key", "$label must be a string")
    }
    return primitive.content
}

private fun requireInt(node: JsonObject, key: String, where: String, label: String) {
    val value = node[key]
        ?: throw DocumentException("missing_field", "$where$key", "$label is required")
    val primitive = value as? JsonPrimitive
    // `isString` excludes "1", and intOrNull excludes true and 1.5. A quoted
    // version number would otherwise publish as the same number as the real
    // one, and a submission records the version it was collected against.
    if (primitive == null || primitive.isString || primitive.intOrNull == null) {
        throw DocumentException("wrong_type", "$where$key", "$label must be an integer")
    }
}
