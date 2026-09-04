import com.android.build.api.artifact.SingleArtifact
import java.io.File
import java.util.zip.ZipFile
import org.jetbrains.kotlin.gradle.dsl.JvmTarget

plugins {
    alias(libs.plugins.androidApplication)
    alias(libs.plugins.composeCompiler)
}

kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_11
    }
}
dependencies {
    implementation(project(":clients:composeApp"))

    implementation(libs.androidx.activity.compose)

    implementation(libs.compose.uiToolingPreview)
    debugImplementation(libs.compose.uiTooling)
}

android {
    namespace = "com.amr.data_collection_lab"
    compileSdk = libs.versions.android.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "com.amr.data_collection_lab"
        minSdk = libs.versions.android.minSdk.get().toInt()
        targetSdk = libs.versions.android.targetSdk.get().toInt()
        versionCode = 1
        versionName = "1.0"
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
    }
}

/*
 * ---------------------------------------------------------------------------
 * No form may ride in the APK.
 * ---------------------------------------------------------------------------
 *
 * Form delivery (sync §5) rests on a claim about a binary: this app contains no
 * questionnaire, so a form on a phone can only have come from the server. That
 * claim was checked once, by hand, on one build — and the way it fails is an
 * incremental build packaging a resource that is no longer in the source tree.
 * A stale `build/` directory is enough. Nothing about that failure is visible:
 * the app syncs, receives forms, and also happens to have shipped with one, and
 * the only symptom is that a device which never synced can still collect.
 *
 * So the claim gets a guard, and the guard is wired to the artifact rather than
 * to a person: every `assemble` of this module is finalised by it, and CI
 * assembles.
 *
 * ## What it looks for, and why not the obvious thing
 *
 * The hand check was `household_survey` appearing nowhere in the APK's bytes.
 * That check does not survive contact with the repository — it does not hold on
 * this tree, which has no bundled form, because `SubmissionListScreenPreview`
 * names the seed form in a `@Preview` literal and Compose previews compile into
 * the APK. A string is not a form, and a guard that cannot tell them apart gets
 * switched off in its first week.
 *
 * What is looked for instead is a **document**: the byte sequence `"irVersion"`
 * followed by a colon. Form IR §10.1 makes `irVersion` mandatory at the top
 * level of every form document, so nothing the engine will accept can omit it,
 * and the quotes are what separate data from code — a Kotlin literal or a
 * `@SerialName` is stored in the DEX string pool bare, as `irVersion`, while a
 * serialised document carries its own punctuation. That is why the pattern
 * includes the quotes and the colon, and why scanning the DEX files is not a
 * source of false positives.
 *
 * Every entry is scanned, decompressed, in UTF-8 and UTF-16LE — assets, DEX,
 * `resources.arsc`, native libraries, all of it. A form embedded as a string
 * constant is as much a bundled form as one sitting in `assets/`, and the point
 * of scanning the whole archive is that the guard does not have to guess which
 * route a form took to get in.
 *
 * Break 31 in docs/known-breaks.md is this task watched to fail.
 */

abstract class VerifyNoBundledForm : DefaultTask() {

    @get:InputFiles
    @get:PathSensitive(PathSensitivity.RELATIVE)
    abstract val apkDirectory: DirectoryProperty

    /**
     * Nothing reads this. It exists so Gradle can call the task up to date on
     * an unchanged APK — without an output there is no up-to-date check, and a
     * guard that re-reads 39 MB on every build is one somebody turns off.
     */
    @get:OutputFile
    abstract val report: RegularFileProperty

    @TaskAction
    fun verify() {
        val apks = apkDirectory.get().asFile.walkTopDown()
            .filter { it.isFile && it.extension == "apk" }
            .toList()
        // An empty artifact directory means the wiring broke, not that the APK
        // is clean. Reporting "no forms found" over nothing is the failure this
        // repository already knows by name — see scripts/check_ci_runs_every_suite.py.
        require(apks.isNotEmpty()) {
            "no APK in " + apkDirectory.get().asFile + " — this guard checked nothing"
        }

        val findings = apks.flatMap { apk -> scan(apk).map { apk.name to it } }
        if (findings.isNotEmpty()) {
            throw GradleException(
                buildString {
                    appendLine("A Form IR document is packaged in this APK.")
                    appendLine()
                    findings.forEach { (apk, entry) -> appendLine("    " + apk + " -> " + entry) }
                    appendLine()
                    appendLine("Forms reach a device over sync (specs/sync-protocol-v0.1.md §5),")
                    appendLine("never in the binary. If this is a stale incremental build, run")
                    appendLine("`./gradlew :clients:androidApp:clean` and assemble again; if the")
                    appendLine("document is genuinely in the source tree, it does not belong there.")
                },
            )
        }

        report.get().asFile.apply {
            parentFile.mkdirs()
            writeText(apks.joinToString("\n") { "no Form IR document in " + it.name } + "\n")
        }
    }

    /** Entry names inside [apk] whose bytes carry a Form IR document. */
    private fun scan(apk: File): List<String> {
        // Form IR §10.1: `irVersion` is required at the top level of every form
        // document. With its quotes and colon it is punctuation only a
        // serialised document has; the DEX string pool holds the bare identifier.
        val marker = Regex("\"irVersion\"\\s*:")
        val hits = mutableListOf<String>()
        ZipFile(apk).use { zip ->
            for (entry in zip.entries()) {
                if (entry.isDirectory) continue
                val bytes = zip.getInputStream(entry).use { it.readBytes() }
                // Both encodings, because a document reaching the APK through a
                // string resource lands in resources.arsc as UTF-16.
                val decoded = String(bytes, Charsets.UTF_8) + " " +
                    String(bytes, Charsets.UTF_16LE)
                if (marker.containsMatchIn(decoded)) hits += entry.name
            }
        }
        return hits
    }
}

androidComponents {
    onVariants { variant ->
        val suffix = variant.name.replaceFirstChar { it.uppercase() }
        val verify = tasks.register<VerifyNoBundledForm>("verifyNoBundledForm" + suffix) {
            group = "verification"
            description = "Fails if the " + variant.name + " APK carries a Form IR document."
            // Wiring the artifact, not a path: this also declares the dependency
            // on the packaging task, so the guard cannot run against last week's
            // APK.
            apkDirectory.set(
                variant.artifacts.get(SingleArtifact.APK),
            )
            report.set(
                layout.buildDirectory.file("reports/no-bundled-form/" + variant.name + ".txt"),
            )
        }

        // `assemble` and `install` both, and `matching` rather than `named`
        // because AGP has not registered either by the time onVariants runs.
        //
        // dependsOn, not finalizedBy: the guard already depends on the APK
        // artifact, so there is no cycle, and a dependency is what makes an
        // unchecked APK unreachable rather than merely reported. `installDebug`
        // is wired for the same reason — it packages without assembling, and
        // installing is exactly when an unnoticed bundled form would reach a
        // phone.
        tasks.matching { it.name == "assemble" + suffix || it.name == "install" + suffix }
            .configureEach { dependsOn(verify) }
    }
}