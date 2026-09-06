package com.dcp.form

import java.io.File

/** Walks up from the working directory to the repo root holding the vectors. */
private fun vectorDir(): File {
    var dir: File? = File(System.getProperty("user.dir")).absoluteFile
    while (dir != null) {
        val candidate = dir.resolve("conformance/vectors")
        if (candidate.isDirectory) return candidate
        dir = dir.parentFile
    }
    error("conformance/vectors not found above ${System.getProperty("user.dir")}")
}

actual fun vectorNames(): List<String> =
    vectorDir().listFiles { f -> f.extension == "json" }!!
        .map { it.nameWithoutExtension }
        .sorted()

actual fun readVectorText(name: String): String = vectorDir().resolve("$name.json").readText()
