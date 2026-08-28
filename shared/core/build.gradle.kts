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
            implementation(libs.kotlinx.serialization.json)
            // CryptographyProvider appears in the public envelope API.
            api(libs.cryptography.core)
            implementation(libs.cryptography.provider.optimal)
            implementation(project(":shared:form-engine"))
        }
        jvmMain.dependencies {
            // Plain JCA cannot derive an X25519 public key from a private key,
            // which unwrapping needs; BouncyCastle backs the JDK provider.
            implementation(libs.cryptography.provider.jdk.bc)
        }
        androidMain.dependencies {
            // Platform JCA has no X25519 below API 33; BouncyCastle backs the
            // JDK provider so the envelope works from minSdk 24.
            implementation(libs.cryptography.provider.jdk.bc)
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
        jvmTest.dependencies {
            implementation(libs.kotlin.testJunit)
        }
    }
}
