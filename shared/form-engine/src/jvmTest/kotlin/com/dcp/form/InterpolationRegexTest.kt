package com.dcp.form

import java.io.File
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * §7.1's slot pattern must be legal on **Android's** regex engine, not only on
 * the host's.
 *
 * `java.util.regex` accepts a bare `}`; `com.android.icu` does not. The pattern
 * `\{\{|}}|\{(\d+)}` compiled everywhere this repository can test and threw
 * `PatternSyntaxException` on a real device — and because [Interpolation.SLOT]
 * is a `val` on an object, that surfaced as `ExceptionInInitializerError` from
 * the class initialiser: **the app died the moment it compiled any form**, on
 * the form-picker tap, with no message.
 *
 * Nothing in the suite could see it. `jvmTest` and `testAndroidHostTest` both
 * run on the JVM's engine — "androidHost" is the host, which is the point of it
 * — and `wasmJsNodeTest` runs on JavaScript's. The only engine that rejects
 * this is the one on a phone, and the only thing that runs it is a handset run
 * (`docs/e2e-run-2026-09-14-rows.md`, where this was found).
 *
 * So this is a **source check**, and it has to be: a test that compiled the
 * pattern would pass here for the same reason the bug shipped. What it asserts
 * is the rule that keeps ICU happy — every brace escaped, opening and closing —
 * which is stricter than Java needs and legal in both.
 *
 * The §7.1 behaviour itself is asserted by `conformance/vectors/label-*` on all
 * three targets; this file is only about the pattern being *compilable* on a
 * fourth.
 */
class InterpolationRegexTest {

    private val text: File by lazy {
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null) {
            val candidate =
                dir.resolve("shared/form-engine/src/commonMain/kotlin/com/dcp/form/Text.kt")
            if (candidate.isFile) return@lazy candidate
            dir = dir.parentFile
        }
        error("Text.kt not found above ${System.getProperty("user.dir")}")
    }

    /** The raw-string body of `private val SLOT = Regex("""…""")`. */
    private fun slotPattern(): String {
        val source = text.readText()
        val marker = "private val SLOT = Regex(\"\"\""
        val start = source.indexOf(marker)
        assertTrue(start > 0, "SLOT not found — this test is reading the wrong thing")
        val from = start + marker.length
        val end = source.indexOf("\"\"\"", from)
        assertTrue(end > from, "SLOT's raw string is not terminated")
        return source.substring(from, end)
    }

    @Test
    fun `every brace in the slot pattern is escaped`() {
        val pattern = slotPattern()
        val offenders = pattern.mapIndexedNotNull { index, ch ->
            if (ch != '{' && ch != '}') null
            else if (index > 0 && pattern[index - 1] == '\\') null
            else "$ch at $index"
        }
        assertEquals(
            emptyList(),
            offenders,
            "an unescaped brace in $pattern: Android's ICU regex engine refuses it and " +
                "the object's initialiser throws on the first form the app compiles. " +
                "Escape it — `\\}` means the same thing to every engine",
        )
    }

    @Test
    fun `the pattern still does what 7 dot 1 says`() {
        // The escaping must not have changed the grammar: `{{` and `}}` are
        // literal braces and are not slots, `{0}` is slot zero.
        assertEquals(setOf(0, 1), Interpolation.slotIndices("{0} — {1}"))
        assertEquals(emptySet(), Interpolation.slotIndices("{{0}}"))
        assertEquals("{0}", Interpolation.render("{{0}}", listOf("never")))
    }
}
