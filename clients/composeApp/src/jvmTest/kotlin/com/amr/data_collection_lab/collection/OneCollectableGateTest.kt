package com.amr.data_collection_lab.collection

import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue

/**
 * **One place decides whether a question type can be presented, and it is the
 * `when` in `CollectionScreen`.**
 *
 * `CollectionViewModel` used to hold a second list — `SUPPORTED_TYPES` — and
 * `questionUi` returned null for anything outside it. It had drifted from
 * `specs/collectable-types-v0.1.json`: `select_multiple` and `note` were
 * missing, so those questions were dropped before a widget was ever asked for,
 * and the screen rendered **nothing at all**. Not the label, not the
 * "this build cannot ask you this" message the composable's `else` branch
 * exists to show — an empty page under a section heading, with Next still
 * working. `docs/known-defects.md` 30, break 230.
 *
 * Three things had to line up for that to survive:
 *
 * - The seed form has no `select_multiple` and no `note`, so five end-to-end
 *   runs walked past it.
 * - `CollectableTypesTest` drives the real composable, which is the right idea,
 *   but it constructs its own `QuestionUi` — and `questionUi` is the function
 *   that decides whether a `QuestionUi` exists at all. The gap was between two
 *   tested things, which is break 57's shape exactly.
 * - The registry lists `select_multiple`, so the importer told authors the
 *   question was fine. It was fine everywhere except on the screen.
 *
 * The fix was to delete the list rather than to synchronise it — break 57's
 * lesson, that removing the choice beats testing it. This is what stops it
 * coming back: a **lint**, because the thing being asserted is that a piece of
 * code does not exist, and no behavioural test can say that.
 *
 * It is deliberately narrow. `CollectionViewModel` legitimately names single
 * types where the *behaviour* differs — parsing an integer, staging media —
 * and those are not gates. What it may not do is hold a **collection** of type
 * names, because that is only ever a second answer to a question already
 * answered in one place.
 */
class OneCollectableGateTest {

    private val root: File by lazy {
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null) {
            if (dir.resolve("specs/collectable-types-v0.1.json").isFile) return@lazy dir
            dir = dir.parentFile
        }
        error("repository root not found above ${System.getProperty("user.dir")}")
    }

    /**
     * Read with a regex rather than a JSON parser, for the reason
     * `CollectableTypesTest` gives: the UI module's test classpath carries no
     * serialization dependency, and the file's shape is committed. An empty
     * result is an error rather than a quietly passing lint.
     */
    private val registryTypes: Set<String> by lazy {
        val text = root.resolve("specs/collectable-types-v0.1.json").readText()
        val array = Regex("\"collectable\"\\s*:\\s*\\[([^]]*)]")
            .find(text)?.groupValues?.get(1)
            ?: error("no \"collectable\" array in collectable-types-v0.1.json")
        val found = Regex("\"([a-z_]+)\"").findAll(array).map { it.groupValues[1] }.toSet()
        check(found.isNotEmpty()) { "parsed no collectable types" }
        found
    }

    private val viewModelSource: String by lazy {
        val file = root.resolve(
            "clients/composeApp/src/commonMain/kotlin/com/amr/data_collection_lab/" +
                "collection/CollectionViewModel.kt",
        )
        check(file.isFile) { "CollectionViewModel.kt not found at $file" }
        file.readText()
    }

    /** Source with `//` comments and KDoc removed — the lint is about code. */
    private fun codeOnly(source: String): String {
        val withoutBlocks = source.replace(Regex("/\\*.*?\\*/", RegexOption.DOT_MATCHES_ALL), " ")
        return withoutBlocks.lines().joinToString("\n") { it.substringBefore("//") }
    }

    @Test
    fun `the view model declares no second list of question types`() {
        val code = codeOnly(viewModelSource)
        val collections = Regex("(setOf|listOf|arrayOf|setOfNotNull)\\s*\\(([^)]*)\\)")
            .findAll(code)
            .map { it.value }
            .filter { literal ->
                registryTypes.count { type -> "\"$type\"" in literal } >= 2
            }
            .toList()

        assertTrue(
            collections.isEmpty(),
            "CollectionViewModel names ${collections.size} collection(s) of question types:\n" +
                collections.joinToString("\n\n") +
                "\n\nThat is a second answer to 'which types can this app present'. The first " +
                "is the `when` in CollectionScreen, whose `else` branch tells an enumerator " +
                "the build cannot ask them this; a list here drops the question before any " +
                "widget is chosen and renders a blank screen. See docs/known-defects.md 30.",
        )
    }

    @Test
    fun `the collection screen has a branch for every collectable type`() {
        // CollectableTypesTest already asserts this by rendering, and asserts it
        // in both directions. This is the cheap textual half, kept because it
        // names the file to edit when the registry gains a type — and because a
        // reader of this file should be able to see that the *other* list, the
        // one that is allowed to exist, is checked.
        val screen = root.resolve(
            "clients/composeApp/src/commonMain/kotlin/com/amr/data_collection_lab/" +
                "collection/CollectionScreen.kt",
        ).readText()
        val missing = registryTypes.filter { "\"$it\" ->" !in screen }
        assertTrue(
            missing.isEmpty(),
            "collectable types with no branch in CollectionScreen's `when`: $missing",
        )
    }
}
