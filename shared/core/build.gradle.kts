import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidMultiplatformLibrary)
}

/*
 * Shared non-UI core: sync engine, storage, networking, security.
 * Networking (Ktor), storage (SQLDelight) and DI (Koin) are added as those
 * subsystems land — see the TODO in gradle/libs.versions.toml.
 */
kotlin {
    jvm()

    listOf(iosArm64(), iosSimulatorArm64()).forEach { it.binaries.framework { baseName = "Core" } }

    android {
        namespace = "com.dcp.core"
        compileSdk = libs.versions.android.compileSdk.get().toInt()
        minSdk = libs.versions.android.minSdk.get().toInt()
        compilerOptions { jvmTarget = JvmTarget.JVM_11 }
    }

    sourceSets {
        commonMain.dependencies {
            implementation(libs.kotlinx.coroutines.core)
            implementation(project(":shared:form-engine"))
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
    }
}
