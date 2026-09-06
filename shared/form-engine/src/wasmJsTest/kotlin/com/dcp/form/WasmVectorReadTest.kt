package com.dcp.form

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject

/*
 * SPIKE: can a wasmJs test read the conformance vectors from disk?
 *
 * If it can, a wasm conformance job is the same runner the JVM has and costs a
 * CI step. If it cannot, the vectors would have to be embedded in generated
 * source, and a wasm target would otherwise be a build nobody runs — defect 18
 * again, on a fifth platform.
 */
private fun readFile(path: String): String =
    js("globalThis.process.getBuiltinModule('fs').readFileSync(path, 'utf8')")

private fun listDir(path: String): String =
    js("globalThis.process.getBuiltinModule('fs').readdirSync(path).join(',')")

/** Walk up from the test's working directory until the corpus is found. */
private fun repoRoot(): String =
    js("(function(){var fs=globalThis.process.getBuiltinModule('fs');var p=globalThis.process.cwd();for(var i=0;i<8;i++){if(fs.existsSync(p+'/conformance/vectors'))return p;p=p+'/..'}return ''})()")

class WasmVectorReadTest {

    @Test
    fun everyVectorFormCompilesOnWasm() {
        val root = repoRoot() + "/conformance/vectors"
        val names = listDir(root).split(",").filter { it.endsWith(".json") }.sorted()
        assertTrue(names.size > 100, "expected the vector corpus, saw ${names.size}")

        var compiled = 0
        var screens = 0
        for (name in names) {
            val vector = Json.parseToJsonElement(readFile("$root/$name")).jsonObject
            val formJson = vector["form"] ?: continue
            val ir = FormIr.parse(formJson)
            CompiledForm(ir)
            compiled++
            screens += buildScreenPlan(ir).screens.size
        }
        // Every form in the corpus compiles here, and the screen plans are
        // built. This is the compile half of rule 2 running somewhere other
        // than the JVM for the first time.
        assertEquals(names.size, compiled, "every vector form should compile")
        assertTrue(screens > 100, "screen plans were built: $screens")
    }
}
