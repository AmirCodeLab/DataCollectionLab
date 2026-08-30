import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidMultiplatformLibrary)
    alias(libs.plugins.kotlinSerialization)
    alias(libs.plugins.sqldelight)
}

/*
 * Shared non-UI core: sync engine, storage, networking, security.
 * Networking (Ktor) and DI (Koin) are added as those subsystems land — see the
 * TODO in gradle/libs.versions.toml.
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
            implementation(project(":shared:form-engine"))

            implementation(libs.kotlinx.coroutines.core)
            implementation(libs.kotlinx.serialization.json)
            // CryptographyProvider appears in the public envelope API.
            api(libs.cryptography.core)
            implementation(libs.cryptography.provider.optimal)

            implementation(libs.sqldelight.runtime)
            implementation(libs.sqldelight.coroutines)

            implementation(libs.ktor.client.core)
            implementation(libs.ktor.client.cio)
            implementation(libs.ktor.serialization.json)
            implementation(libs.ktor.client.contentNegotiation)
        }
        jvmMain.dependencies {
            // Plain JCA cannot derive an X25519 public key from a private key,
            // which unwrapping needs; BouncyCastle backs the JDK provider.
            implementation(libs.cryptography.provider.jdk.bc)

            implementation(libs.sqldelight.sqlite.driver)
            // The cipher for the local database (envelope §14). Substituted
            // for org.xerial:sqlite-jdbc below, not added alongside it.
            implementation(libs.sqlite.jdbc.mc)
        }
        androidMain.dependencies {
            // Platform JCA has no X25519 below API 33; BouncyCastle backs the
            // JDK provider so the envelope works from minSdk 24.
            implementation(libs.cryptography.provider.jdk.bc)

            implementation(libs.sqldelight.android.driver)
            implementation(libs.sqlcipher.android)
        }
        iosMain.dependencies {
            implementation(libs.sqldelight.native.driver)
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
        jvmTest.dependencies {
            implementation(libs.kotlin.testJunit)
            implementation(libs.ktor.client.mock)
        }
    }
}

sqldelight {
    databases {
        create("DcpDatabase") {
            packageName.set("com.dcp.core.db")
        }
    }
}

/*
 * The local database is encrypted (encryption envelope §14), and on the JVM the
 * cipher comes from SQLite3 Multiple Ciphers — a fork of org.xerial:sqlite-jdbc
 * with the SQLCipher codec compiled into its bundled native library.
 *
 * A substitution rather than an extra dependency, because the two register the
 * same `org.sqlite.JDBC` driver under the same class name. With both on the
 * classpath the winner is whichever the class loader reaches first, and if that
 * is the stock one then `PRAGMA key` is an unknown pragma, SQLite ignores it
 * without error, and the op log is written in cleartext. Substituting makes
 * that outcome impossible instead of unlikely — `sqldelight-sqlite-driver`
 * pulls the stock driver in transitively, so it would otherwise arrive without
 * anyone naming it.
 */
configurations.configureEach {
    resolutionStrategy.dependencySubstitution {
        substitute(module("org.xerial:sqlite-jdbc"))
            .using(module("io.github.willena:sqlite-jdbc:${libs.versions.sqlite.jdbc.mc.get()}"))
            .because("SQLCipher for the local database at rest — encryption envelope §14")
    }
}
