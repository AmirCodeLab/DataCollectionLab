package com.amr.data_collection_lab.collection

import androidx.compose.ui.test.ExperimentalTestApi
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.runComposeUiTest
import java.io.File
import kotlin.test.Test
import kotlin.test.assertTrue

/**
 * `specs/collectable-types-v0.1.json` and this app agree, in **both**
 * directions.
 *
 * The file is what the XLSForm importer reads to tell an author whether their
 * question will work in the field. It is therefore a claim this app has to
 * keep, and the two ways it can be broken are not symmetric:
 *
 * - **Listed, but no branch.** The importer reports the question as
 *   collectable, the form publishes, and the enumerator gets a message saying
 *   their app is too old for a type we said was fine. This is the worse one.
 * - **A branch, but not listed.** A type quietly works while the report tells
 *   the author it is unavailable, so they redesign a form around a limitation
 *   that is not there.
 *
 * Both are drift, and a test comparing two Kotlin lists would catch neither —
 * it would only prove that one hand-written copy matches another. So this
 * drives the **real composable** and asserts on what is rendered: a listed type
 * must not produce the unsupported message, and an unlisted one must.
 *
 * That also makes the test survive the widgets changing. It never names
 * `Checkbox` or `RadioButton`; it asks the only question that matters, which is
 * whether the app admits it cannot ask this.
 *
 * This is above the line the conformance vectors reach (docs/project-conventions.md). Break 36.
 */
@OptIn(ExperimentalTestApi::class)
class CollectableTypesTest {

    private val registry: File by lazy {
        var dir: File? = File(System.getProperty("user.dir")).absoluteFile
        while (dir != null) {
            val candidate = dir.resolve("specs/collectable-types-v0.1.json")
            if (candidate.isFile) return@lazy candidate
            dir = dir.parentFile
        }
        error("specs/collectable-types-v0.1.json not found above ${System.getProperty("user.dir")}")
    }

    /**
     * Read with a regex rather than a JSON parser, so this test needs no
     * serialization dependency on the UI module's test classpath. The file's
     * shape is fixed and committed; if it stops matching, the first assertion
     * below fails loudly rather than the list silently coming back empty.
     */
    private fun collectable(): List<String> {
        val array = Regex("\"collectable\"\\s*:\\s*\\[([^]]*)]")
            .find(registry.readText())?.groupValues?.get(1)
            ?: error("no \"collectable\" array in ${registry.name}")
        return Regex("\"([a-z_]+)\"").findAll(array).map { it.groupValues[1] }.toList()
    }

    /** Every dataType in the IR spec's §2.1 table, parsed from the spec itself. */
    private fun specDataTypes(): List<String> {
        val spec = registry.parentFile.resolve("form-ir-v0.1.md").readText()
        val table = spec.substringAfter("**Data types**").substringBefore("### 2.2")
        return table.lines()
            .filter { it.startsWith("| `") }
            .flatMap { Regex("`([a-z_]+)`").findAll(it.substringAfter("|").substringBefore("|")).map { m -> m.groupValues[1] } }
            .distinct()
    }

    private fun state(dataType: String) = CollectionState(
        isLoading = false,
        formTitle = "Household Survey",
        language = "en",
        languages = listOf("en"),
        questions = listOf(
            QuestionUi(
                path = "q",
                dataType = dataType,
                label = "A question",
                hint = null,
                required = false,
                readOnly = false,
                displayText = "",
                selectedValue = null,
                choices = listOf(ChoiceUi("a", "Option A"), ChoiceUi("b", "Option B")),
                dateIso = null,
                error = null,
            ),
        ),
        progressPosition = 1,
        progressTotal = 1,
    )

    private fun unsupportedMessage(dataType: String) =
        UiStrings.unsupportedQuestionType("en", dataType)

    @Test
    fun `the registry lists only real dataTypes from the IR spec`() {
        // A typo here would silently promise a type that cannot exist.
        val spec = specDataTypes()
        assertTrue(spec.isNotEmpty(), "parsed no dataTypes out of form-ir-v0.1.md §2.1")
        assertTrue(collectable().isNotEmpty(), "parsed no types out of ${registry.name}")
        val unknown = collectable() - spec.toSet()
        assertTrue(
            unknown.isEmpty(),
            "collectable-types lists $unknown, which are not dataTypes in Form IR §2.1",
        )
    }

    @Test
    fun `every type the registry lists can actually be answered`() = runComposeUiTest {
        // Direction 1, and the worse failure: the importer tells an author their
        // question is fine, and the phone tells the enumerator the app is too
        // old for it.
        collectable().forEach { dataType ->
            setContent { CollectionScreen(state = state(dataType), onAction = {}) }
            onNodeWithText("A question").assertIsDisplayed()
            onNodeWithText(unsupportedMessage(dataType)).assertDoesNotExist()
        }
    }

    @Test
    fun `every spec type the registry omits says so on screen`() = runComposeUiTest {
        // Direction 2, and the one defect 7 was: falling through the `when` with
        // no `else` drew a label and empty space. The enumerator could not tell
        // "nothing to do here" from "this app cannot ask you this".
        val omitted = specDataTypes() - collectable().toSet()
        assertTrue(omitted.isNotEmpty(), "if nothing is omitted this test proves nothing")

        omitted.forEach { dataType ->
            setContent { CollectionScreen(state = state(dataType), onAction = {}) }
            onNodeWithText("A question").assertIsDisplayed()
            onNodeWithText(unsupportedMessage(dataType)).assertIsDisplayed()
        }
    }

    @Test
    fun `an unknown type from a newer app version also says so`() = runComposeUiTest {
        // The case the `else` exists for, and it is not hypothetical: once
        // customers author their own forms, a server will deploy one built for
        // a newer client than the phone is running.
        setContent { CollectionScreen(state = state("holographic_capture"), onAction = {}) }

        onNodeWithText(unsupportedMessage("holographic_capture")).assertIsDisplayed()
    }

    @Test
    fun `the unsupported message is not a control that takes input`() = runComposeUiTest {
        // Defect 2's mistake in a different place: a widget that looks usable
        // and drops what it is given. There must be nothing to type into and
        // nothing to tick.
        setContent { CollectionScreen(state = state("barcode"), onAction = {}) }

        onNodeWithText(unsupportedMessage("barcode")).assertIsDisplayed()
        onNodeWithText("Option A").assertDoesNotExist()
        onNodeWithText("Option B").assertDoesNotExist()
    }
}
