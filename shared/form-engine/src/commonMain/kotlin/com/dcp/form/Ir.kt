package com.dcp.form

/**
 * Typed IR model and JSON parsing.
 *
 * Mirrors the document structure in specs/form-ir-v0.1.md sections 1–3. The
 * expression AST (section 4) is parsed into [Expr] by [ExprSerializer]; a bare
 * JSON boolean is accepted where the spec allows `<expr|bool>` and becomes a
 * literal.
 */

import kotlinx.serialization.KSerializer
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.SerializationException
import kotlinx.serialization.descriptors.SerialDescriptor
import kotlinx.serialization.encoding.Decoder
import kotlinx.serialization.encoding.Encoder
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonDecoder
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonEncoder
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.longOrNull

/** The Json configuration every IR document is parsed with. */
val IrJson: Json = Json {
    ignoreUnknownKeys = true
    classDiscriminator = "type"
}

/** The IR version this engine implements (spec §9). */
val SUPPORTED_IR_VERSION: Pair<Int, Int> = 0 to 1

/**
 * Spec §9 and §10.1. Refuse a version this engine does not implement.
 *
 * Not advisory, and not only about the major number: v0.2 may define an
 * expression node or a node kind this engine would silently ignore, producing
 * a form that looks correct and evaluates by the wrong rules. The enumerator
 * whose device is a version behind has to be told to update, and a form that
 * opens and quietly misbehaves tells them nothing.
 *
 * Kept beside [FormIr] rather than in Document.kt because this is the one
 * document error that survives decoding: the field is present and it is a
 * string, so a typed FormIr built in code can still carry a version this
 * engine cannot read. [CompiledForm] therefore calls it again.
 */
fun checkIrVersion(raw: String) {
    val (supportedMajor, supportedMinor) = SUPPORTED_IR_VERSION
    val parts = raw.split(".")
    val major = parts.getOrNull(0)?.toIntOrNull()
    val minor = parts.getOrNull(1)?.toIntOrNull()

    if (major == null || minor == null) {
        throw DocumentException(
            "unknown_ir_version",
            "irVersion",
            "'$raw' is not a version number. This engine implements " +
                "$supportedMajor.$supportedMinor.",
        )
    }
    if (major != supportedMajor || minor > supportedMinor) {
        throw DocumentException(
            "unknown_ir_version",
            "irVersion",
            "this engine implements Form IR $supportedMajor.$supportedMinor and cannot " +
                "read $raw. Reading what it recognises would produce a form that " +
                "evaluates by the wrong rules.",
        )
    }
}

@Serializable
data class FormIr(
    val irVersion: String,
    val formId: String,
    val version: Int,
    val title: Map<String, String> = emptyMap(),
    val defaultLanguage: String? = null,
    val languages: List<String> = emptyList(),
    val children: List<FormNode> = emptyList(),
) {
    companion object {
        fun parse(json: String): FormIr = parse(IrJson.parseToJsonElement(json))

        /**
         * §10.1 runs over the raw JSON first, so a malformed document is
         * refused with a reason and a location rather than with whatever the
         * deserialiser says about a Kotlin field. Decoding is the backstop.
         */
        fun parse(element: JsonElement): FormIr {
            checkDocument(element)
            return IrJson.decodeFromJsonElement(serializer(), element)
        }
    }
}

@Serializable
sealed interface FormNode {
    val id: String
    val label: Map<String, String>?
}

/** A node that owns children and passes its relevance down to them. */
sealed interface ContainerNode : FormNode {
    val relevant: Expr?
    val children: List<FormNode>
}

@Serializable
@SerialName("question")
data class QuestionNode(
    override val id: String,
    val dataType: String,
    override val label: Map<String, String>? = null,
    val hint: Map<String, String>? = null,
    @Serializable(ExprSerializer::class) val required: Expr? = null,
    @Serializable(ExprSerializer::class) val relevant: Expr? = null,
    @Serializable(ExprSerializer::class) val constraint: Expr? = null,
    val constraintMessage: Map<String, String>? = null,
    @Serializable(ExprSerializer::class) val calculate: Expr? = null,
    @Serializable(ExprSerializer::class) val default: Expr? = null,
    @Serializable(ExprSerializer::class) val readOnly: Expr? = null,
    /**
     * Spec 2.1. Marks a field whose VALUE carries personal or health
     * information; the input to field_level encryption (encryption envelope
     * §5.2). Fixed in the IR, never an expression — sensitivity is a property
     * of the field, not of the answer.
     */
    val sensitive: Boolean = false,
    val appearance: String? = null,
    val severity: String? = null,
    val choices: Choices? = null,
) : FormNode

@Serializable
@SerialName("group")
data class GroupNode(
    override val id: String,
    override val label: Map<String, String>? = null,
    @Serializable(ExprSerializer::class) override val relevant: Expr? = null,
    val appearance: String? = null,
    override val children: List<FormNode> = emptyList(),
) : ContainerNode

@Serializable
@SerialName("repeat")
data class RepeatNode(
    override val id: String,
    override val label: Map<String, String>? = null,
    @Serializable(ExprSerializer::class) override val relevant: Expr? = null,
    @Serializable(ExprSerializer::class) val countExpr: Expr? = null,
    val minInstances: Int? = null,
    val maxInstances: Int? = null,
    override val children: List<FormNode> = emptyList(),
) : ContainerNode

@Serializable
data class Choices(
    val kind: String,
    val items: List<ChoiceItem> = emptyList(),
    val dataset: String? = null,
    val valueColumn: String? = null,
    val labelColumn: Map<String, String>? = null,
    @Serializable(ExprSerializer::class) val filter: Expr? = null,
)

@Serializable
data class ChoiceItem(
    val value: String,
    val label: Map<String, String>? = null,
)

// --------------------------------------------------------------------------
// Expression AST <-> JSON
// --------------------------------------------------------------------------

object ExprSerializer : KSerializer<Expr> {
    override val descriptor: SerialDescriptor =
        SerialDescriptor("com.dcp.form.Expr", JsonElement.serializer().descriptor)

    override fun deserialize(decoder: Decoder): Expr {
        val input = decoder as? JsonDecoder
            ?: throw SerializationException("Expr can only be decoded from JSON")
        return exprFromJson(input.decodeJsonElement())
    }

    override fun serialize(encoder: Encoder, value: Expr) {
        val output = encoder as? JsonEncoder
            ?: throw SerializationException("Expr can only be encoded to JSON")
        output.encodeJsonElement(exprToJson(value))
    }
}

fun exprFromJson(element: JsonElement): Expr {
    if (element is JsonPrimitive) {
        // `required` and `readOnly` are <expr|bool>; a bare boolean is a literal.
        val bool = element.booleanOrNull
        if (!element.isString && bool != null) return Expr.Lit(FormValue.Bool(bool))
        throw CompileException("malformed expression node: $element")
    }
    val obj = element as? JsonObject
        ?: throw CompileException("malformed expression node: $element")
    val op = (obj["op"] as? JsonPrimitive)?.takeIf { it.isString }?.content
        ?: throw CompileException("malformed expression node: $element")
    return when (op) {
        "lit" -> Expr.Lit(formValueFromJson(obj["value"] ?: JsonNull))
        "ref" -> {
            val path = (obj["path"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                ?: throw CompileException("ref node without a path: $element")
            Expr.Ref(path)
        }
        "call" -> {
            val fn = (obj["fn"] as? JsonPrimitive)?.takeIf { it.isString }?.content
                ?: throw CompileException("call node without fn: $element")
            Expr.Call(fn, (obj["args"] as? JsonArray).orEmpty().map(::exprFromJson))
        }
        else -> Expr.Op(op, (obj["args"] as? JsonArray).orEmpty().map(::exprFromJson))
    }
}

fun exprToJson(expr: Expr): JsonElement = when (expr) {
    is Expr.Lit -> buildJsonObject {
        put("op", JsonPrimitive("lit"))
        put("value", formValueToJson(expr.value))
    }
    is Expr.Ref -> buildJsonObject {
        put("op", JsonPrimitive("ref"))
        put("path", JsonPrimitive(expr.path))
    }
    is Expr.Op -> buildJsonObject {
        put("op", JsonPrimitive(expr.op))
        put("args", JsonArray(expr.args.map(::exprToJson)))
    }
    is Expr.Call -> buildJsonObject {
        put("op", JsonPrimitive("call"))
        put("fn", JsonPrimitive(expr.fn))
        put("args", JsonArray(expr.args.map(::exprToJson)))
    }
}

/**
 * Converts a raw JSON value (a literal, an answer, an expected value) into a
 * [FormValue]. A number without a fraction or exponent that fits a 64-bit
 * signed integer is an [FormValue.Integer]; everything else numeric is a
 * [FormValue.Decimal] — matching how the Python reference reads JSON.
 */
fun formValueFromJson(element: JsonElement): FormValue = when (element) {
    is JsonNull -> FormValue.Null
    is JsonPrimitive -> when {
        element.isString -> FormValue.Text(element.content)
        element.booleanOrNull != null -> FormValue.Bool(element.booleanOrNull!!)
        else -> {
            val integral = element.content.none { it == '.' || it == 'e' || it == 'E' }
            val long = if (integral) element.longOrNull else null
            if (long != null) FormValue.Integer(long)
            else FormValue.Decimal(
                element.doubleOrNull
                    ?: throw CompileException("unsupported literal value: $element")
            )
        }
    }
    is JsonArray -> FormValue.Sequence(element.map(::formValueFromJson))
    is JsonObject -> {
        val lat = (element["lat"] as? JsonPrimitive)?.doubleOrNull
        val lon = (element["lon"] as? JsonPrimitive)?.doubleOrNull
        if (lat != null && lon != null) FormValue.GeoPoint(lat, lon)
        else throw CompileException("unsupported literal value: $element")
    }
}

fun formValueToJson(value: FormValue): JsonElement = when (value) {
    is FormValue.Null -> JsonNull
    is FormValue.Text -> JsonPrimitive(value.value)
    is FormValue.Integer -> JsonPrimitive(value.value)
    is FormValue.Decimal -> JsonPrimitive(value.value)
    is FormValue.Bool -> JsonPrimitive(value.value)
    is FormValue.DateValue -> JsonPrimitive(value.iso)
    is FormValue.Sequence -> JsonArray(value.items.map(::formValueToJson))
    is FormValue.GeoPoint -> buildJsonObject {
        put("lat", JsonPrimitive(value.lat))
        put("lon", JsonPrimitive(value.lon))
    }
}
