import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.kotlinSerialization)
    alias(libs.plugins.androidMultiplatformLibrary)
}

/*
 * The form engine is a PURE library.
 *
 * No Compose, no Android framework calls, no UI. It must remain consumable by:
 *   - the field clients (Android, iOS, desktop)
 *   - a browser build via Wasm (web forms)
 *   - potentially the server (decision O-2)
 *
 * Adding a UI or platform dependency here breaks that. Don't.
 */
/*
 * One test function per conformance vector, generated from the directory.
 *
 * The runner itself is `commonTest`, so it compiles for every target. This
 * exists for the report rather than the run: a single test that loops over the
 * corpus reports "1 passed" whether it executed 113 vectors or none, and a
 * count nobody compares against anything is exactly what break 41 and break 82
 * are about. With a function per vector, `how many vectors ran on this target`
 * is a number in the test XML rather than a claim in a build log.
 *
 * Generated from the directory on every build and never committed, so it cannot
 * drift from the corpus the way a hand-maintained list would.
 */
val generateVectorTests = tasks.register("generateVectorTests") {
    val vectors = rootProject.layout.projectDirectory.dir("conformance/vectors")
    val outputDir = layout.buildDirectory.dir("generated/vectorTests")
    inputs.dir(vectors).withPathSensitivity(PathSensitivity.RELATIVE)
    outputs.dir(outputDir)
    doLast {
        val names = vectors.asFile.listFiles { f -> f.extension == "json" }
            .orEmpty()
            .map { it.nameWithoutExtension }
            .sorted()
        check(names.isNotEmpty()) { "no conformance vectors found in $vectors" }
        val target = outputDir.get().asFile.resolve("com/dcp/form/GeneratedVectorTests.kt")
        target.parentFile.mkdirs()
        target.writeText(
            buildString {
                appendLine("package com.dcp.form")
                appendLine()
                appendLine("// GENERATED from conformance/vectors. Do not edit.")
                appendLine("// ${names.size} vectors.")
                appendLine()
                appendLine("import kotlin.test.Test")
                appendLine()
                appendLine("/** What this file was generated from, for [VectorCoverageTest]. */")
                appendLine("val GENERATED_VECTOR_IDS: List<String> = listOf(")
                names.forEach { appendLine("    \"$it\",") }
                appendLine(")")
                appendLine()
                appendLine("class GeneratedVectorTests {")
                appendLine("    private val runner = VectorRunner()")
                names.forEach { appendLine("    @Test fun `$it`() = runner.runVector(\"$it\")") }
                appendLine("}")
            }
        )
    }
}

kotlin {
    sourceSets.commonTest.get().kotlin.srcDir(generateVectorTests)

    jvm()

    /*
     * SPIKE (2026-09-06). Browser preview for the visual form builder needs the
     * engine the handset runs, not an approximation — scope doc §2.1. This is
     * the target that would make that possible; whether it is kept depends on
     * what the spike found, which is written up in docs/wasm-spike.md.
     */
    @OptIn(org.jetbrains.kotlin.gradle.ExperimentalWasmDsl::class)
    wasmJs {
        browser()
        nodejs()
        binaries.executable()
    }

    listOf(iosArm64(), iosSimulatorArm64()).forEach { it.binaries.framework { baseName = "FormEngine" } }

    android {
        namespace = "com.dcp.form"
        compileSdk = libs.versions.android.compileSdk.get().toInt()
        minSdk = libs.versions.android.minSdk.get().toInt()
        compilerOptions { jvmTarget = JvmTarget.JVM_11 }
        withHostTestBuilder {}.configure {}
    }

    sourceSets {
        /*
         * The vector reader is one implementation for two JVM-shaped targets.
         *
         * `jvmTest` and `androidHostTest` both run on a host JVM and both read
         * the corpus with java.io, so the `actual` lives once in an
         * intermediate source set they share. Copying it into each would be two
         * things to keep in step for no reason, and the second copy is the one
         * that would quietly stop matching.
         */
        val jvmSharedTest by creating { dependsOn(commonTest.get()) }
        jvmTest.get().dependsOn(jvmSharedTest)
        getByName("androidHostTest").dependsOn(jvmSharedTest)

        commonMain.dependencies {
            implementation(libs.kotlinx.serialization.json)
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
        jvmTest.dependencies {
            implementation(libs.kotlin.testJunit)
        }
    }
}

/*
 * The normative files these tests read at run time, declared so Gradle can see
 * them.
 *
 * Without this the test task is UP-TO-DATE after a vector is added or edited,
 * and the build goes green having run the *old* set. That is not hypothetical
 * and it is not rare: it has now happened three times in this repository — for
 * the collectable-types registry, for the cross-module mirror reference, and
 * here, where adding nine conformance vectors left `:shared:form-engine:jvmTest`
 * reporting 39 tests and BUILD SUCCESSFUL.
 *
 * This one matters most of the three. Rule 2 — every vector passes identically
 * on both engines — is the strongest guarantee in this repository, and it rests
 * entirely on the vectors actually being run. A vector that is not executed is
 * indistinguishable from a vector that passes.
 *
 * Directories rather than named files, deliberately: a new vector must not need
 * a build change to be noticed, which is the same mistake one level up.
 */
tasks.withType<org.gradle.api.tasks.testing.Test>().configureEach {
    inputs.dir(rootProject.layout.projectDirectory.dir("conformance"))
        .withPropertyName("conformanceVectors")
        .withPathSensitivity(PathSensitivity.RELATIVE)
    inputs.dir(rootProject.layout.projectDirectory.dir("specs"))
        .withPropertyName("normativeSpecs")
        .withPathSensitivity(PathSensitivity.RELATIVE)
}
