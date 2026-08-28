rootProject.name = "DataCollectionLab"

pluginManagement {
    repositories {
        google {
            mavenContent {
                includeGroupAndSubgroups("androidx")
                includeGroupAndSubgroups("com.android")
                includeGroupAndSubgroups("com.google")
            }
        }
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositories {
        google {
            mavenContent {
                includeGroupAndSubgroups("androidx")
                includeGroupAndSubgroups("com.android")
                includeGroupAndSubgroups("com.google")
            }
        }
        mavenCentral()
    }
}

plugins {
    id("org.gradle.toolchains.foojay-resolver-convention") version "1.0.0"
}

// Platform-independent engine and core. No UI, no Android framework dependency —
// these must stay consumable by the server and by a Wasm web build.
include(":shared:form-engine")
include(":shared:core")

// Field clients. composeApp holds the shared UI; androidApp/desktopApp are thin
// launchers; iosApp is an Xcode project consuming the composeApp framework.
include(":clients:composeApp")
include(":clients:androidApp")
include(":clients:desktopApp")
