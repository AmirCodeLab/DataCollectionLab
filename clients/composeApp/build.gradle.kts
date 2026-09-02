import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidMultiplatformLibrary)
    alias(libs.plugins.composeMultiplatform)
    alias(libs.plugins.composeCompiler)
}

kotlin {
    listOf(
        iosArm64(),
        iosSimulatorArm64()
    ).forEach { iosTarget ->
        iosTarget.binaries.framework {
            baseName = "Shared"
            isStatic = true
        }
    }
    
    jvm()
    
    android {
       namespace = "com.amr.data_collection_lab.shared"
       compileSdk = libs.versions.android.compileSdk.get().toInt()
       minSdk = libs.versions.android.minSdk.get().toInt()
    
       compilerOptions {
           jvmTarget = JvmTarget.JVM_11
       }
       androidResources {
           enable = true
       }
       withHostTest {
           isIncludeAndroidResources = true
       }
       withDeviceTestBuilder {
           sourceSetTreeName = "test"
       }.configure {
           instrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
       }
    }
    
    sourceSets {
        androidMain.dependencies {
            implementation(libs.compose.uiToolingPreview)
            implementation(libs.compose.uiTooling)

            // The viewfinder. PreviewView is the only UI class in the CameraX
            // family, so it belongs here rather than in :shared:core, which
            // owns the capture pipeline and hands out a SurfaceProvider sink.
            implementation(libs.androidx.camera.view)
            // rememberLauncherForActivityResult, for the camera permission and
            // the system photo picker.
            implementation(libs.androidx.activity.compose)
        }
        commonMain.dependencies {
            // Shared, platform-independent engine and core. Core is api() so the
            // thin launchers can construct the platform DatabaseDriverFactory.
            implementation(project(":shared:form-engine"))
            api(project(":shared:core"))
            implementation(libs.kotlinx.coroutines.core)

            implementation(libs.compose.runtime)
            implementation(libs.compose.foundation)
            implementation(libs.compose.material3)
            implementation(libs.compose.ui)
            implementation(libs.compose.components.resources)
            implementation(libs.compose.uiToolingPreview)
            implementation(libs.androidx.lifecycle.viewmodelCompose)
            implementation(libs.androidx.lifecycle.runtimeCompose)
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
        jvmTest.dependencies {
            // Drives the shared collection screen through a real composition on
            // the desktop target, so a widget that only misbehaves there is
            // reproducible without a device and without synthesised OS events.
            @OptIn(org.jetbrains.compose.ExperimentalComposeLibrary::class)
            implementation(compose.uiTest)
            implementation(compose.desktop.currentOs)
            // A real local database, so the form-version binding can be tested
            // against the same stores the app builds rather than against fakes
            // that would agree with whatever the code does.
            implementation(libs.sqldelight.sqlite.driver)
        }
    }
}

dependencies {
    androidRuntimeClasspath(libs.compose.uiTooling)
}
/*
 * `CollectableTypesTest` reads two committed files from `specs/` at run time —
 * the collectable-types registry and the Form IR spec's dataType table. Gradle
 * cannot see that, so without this the test task is UP-TO-DATE (or FROM-CACHE)
 * after an edit to either, and the build goes green having run nothing.
 *
 * That was observed, not feared: removing `select_multiple` from the registry
 * and re-running produced `> Task :clients:composeApp:jvmTest FROM-CACHE` and
 * BUILD SUCCESSFUL, while the same edit with `--rerun-tasks` failed the test it
 * was supposed to fail. A stale green on a mirror test is the same failure the
 * suites guard exists for: paperwork over nothing.
 *
 * Declaring them as inputs makes an edit to either file re-run the tests that
 * read it.
 */
tasks.withType<org.gradle.api.tasks.testing.Test>().configureEach {
    inputs.files(
        rootProject.layout.projectDirectory.file("specs/collectable-types-v0.1.json"),
        rootProject.layout.projectDirectory.file("specs/form-ir-v0.1.md"),
    )
        .withPropertyName("formIrSpecFiles")
        .withPathSensitivity(PathSensitivity.RELATIVE)
}
