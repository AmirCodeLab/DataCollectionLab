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
kotlin {
    jvm()

    listOf(iosArm64(), iosSimulatorArm64()).forEach { it.binaries.framework { baseName = "FormEngine" } }

    android {
        namespace = "com.dcp.form"
        compileSdk = libs.versions.android.compileSdk.get().toInt()
        minSdk = libs.versions.android.minSdk.get().toInt()
        compilerOptions { jvmTarget = JvmTarget.JVM_11 }
    }

    sourceSets {
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
