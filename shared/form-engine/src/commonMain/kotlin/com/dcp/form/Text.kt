package com.dcp.form

/**
 * Interpolated labels and constraint messages (Form IR §7.1).
 *
 * A label may carry positional slots — `{0}`, `{1}` — filled from expressions,
 * so a form can say what it computed. `label` itself is still
 * `Map<String, String>`; the expressions live beside it in `labelArgs`.
 *
 * ## The isolates are not cosmetic
 *
 * Every non-empty value is wrapped in U+2068 FIRST STRONG ISOLATE and U+2069
 * POP DIRECTIONAL ISOLATE, and **this is the part of the file most likely to be
 * deleted by somebody tidying up**, because two invisible codepoints look like
 * noise. They are the whole reason interpolation is safe to offer at all.
 *
 * A run of Latin digits inside Arabic text is directionally *neutral at its
 * edges*. The Unicode bidirectional algorithm therefore resolves it against the
 * surrounding paragraph rather than on its own, and can move it: `الشعاع 15 م`
 * renders with the number in the wrong place, and a string holding two numbers
 * reorders outright. That is precisely the bug that produced `25 / 5` for a
 * page indicator that read `5 / 25` — the same class, in the same product,
 * already once.
 *
 * An isolate makes the inserted run opaque to the paragraph's resolution. It is
 * the only fix that works for every value rather than for the ones somebody
 * happened to test with, and it belongs in the engine so that two engines
 * produce the same string and one vector can assert it.
 *
 * `conformance/vectors/label-004` asserts the codepoints by number. Removing
 * this fails loudly, which is the point.
 */
object Interpolation {

    /** U+2068 / U+2069, named so a search for either finds the reason above. */
    const val FIRST_STRONG_ISOLATE = '⁨'
    const val POP_DIRECTIONAL_ISOLATE = '⁩'

    /** `{0}`, with `{{` and `}}` for literal braces. */
    private val SLOT = Regex("""\{\{|}}|\{(\d+)}""")

    /** Every `{n}` the template refers to. `{{` is a literal and is not one. */
    fun slotIndices(template: String): Set<Int> =
        SLOT.findAll(template).mapNotNull { it.groupValues[1].toIntOrNull() }.toSet()

    /**
     * Wrap an interpolated value so bidi cannot drag it out of position.
     *
     * Empty stays empty: an isolate protects a run of text and there is no run.
     */
    fun isolate(text: String): String =
        if (text.isEmpty()) text
        else "$FIRST_STRONG_ISOLATE$text$POP_DIRECTIONAL_ISOLATE"

    /** Fill `{n}` slots, isolating each value, and unescape `{{` / `}}`. */
    fun render(template: String, values: List<String>): String =
        SLOT.replace(template) { match ->
            val index = match.groupValues[1].toIntOrNull()
            when {
                index == null -> if (match.value == "{{") "{" else "}"
                // Out of range is a compile error (§7.1); by here it cannot
                // happen, and empty is the only thing left that is not a crash.
                index < values.size -> isolate(values[index])
                else -> ""
            }
        }
}
