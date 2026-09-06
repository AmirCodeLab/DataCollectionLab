package com.dcp.form

/*
 * Node's synchronous fs, reached through `process.getBuiltinModule`.
 *
 * Not `require`: the test runs as an ES module, where `require` is undefined —
 * the first attempt failed with `globalThis.require is not a function`. And not
 * an async `import('node:fs')`, because a `js()` body is an expression and the
 * runner is synchronous. `getBuiltinModule` is the one synchronous path, and it
 * is why a wasm conformance job is a CI step rather than a project.
 */
private fun readFileSync(path: String): String =
    js("globalThis.process.getBuiltinModule('fs').readFileSync(path, 'utf8')")

private fun readDirJoined(path: String): String =
    js("globalThis.process.getBuiltinModule('fs').readdirSync(path).join(',')")

/** Walks up from the test's working directory to the repo root. */
private fun vectorDir(): String =
    js(
        "(function(){var fs=globalThis.process.getBuiltinModule('fs');" +
            "var p=globalThis.process.cwd();for(var i=0;i<8;i++){" +
            "if(fs.existsSync(p+'/conformance/vectors'))return p+'/conformance/vectors';" +
            "p=p+'/..'}throw new Error('conformance/vectors not found')})()"
    )

actual fun vectorNames(): List<String> =
    readDirJoined(vectorDir())
        .split(",")
        .filter { it.endsWith(".json") }
        .map { it.removeSuffix(".json") }
        .sorted()

actual fun readVectorText(name: String): String = readFileSync("${vectorDir()}/$name.json")
