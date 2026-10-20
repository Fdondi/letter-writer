import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// google-services.json is gitignored and produced by scripts/firebase/setup_android_firebase.sh.
// Without it the app still builds and tells the user at sign-in that Firebase is not configured.
if (file("google-services.json").exists()) {
    apply(plugin = libs.plugins.google.services.get().pluginId)
}

val repoRoot: File = rootDir.parentFile

// Same string the web UI reads at runtime from the first line of this changelog.
val appVersionFile = repoRoot.resolve("letter_writer_web/public/app-version.txt")
val appVersion = appVersionFile.useLines { lines ->
    lines.map { it.trim() }.firstOrNull { it.isNotEmpty() }
}?.substringBefore(" - ")?.trim().orEmpty()
require(Regex("""\d+\.\d+\.\d+""").matches(appVersion)) {
    "First line of $appVersionFile must be \"<major.minor.patch> - <text>\", found: ${appVersion.ifEmpty { "(empty)" }}"
}
val appVersionParts = appVersion.split(".").map { it.toInt() }
// 0.75.0 -> 75000, 0.76.1 -> 76001.
val appVersionCode = appVersionParts[0] * 100_000 + appVersionParts[1] * 1_000 + appVersionParts[2]

val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "io.github.fdondi.letterwriter"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "io.github.fdondi.letterwriter"
        minSdk = 29
        targetSdk = 37
        versionCode = appVersionCode
        versionName = appVersion

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField(
            "String",
            "WEB_CLIENT_ID",
            "\"${localProps.getProperty("letterwriter.webClientId", "")}\"",
        )
        buildConfigField("String", "GCP_PROJECT", "\"gen-lang-client-0535858734\"")
        buildConfigField("String", "FIRESTORE_DATABASE", "\"letter\"")
        buildConfigField("String", "BIGQUERY_DATASET", "\"letter_writer\"")
    }

    buildTypes {
        release {
            // Same certificate already registered in Firebase, so Google sign-in
            // works. The release build type is still not debuggable.
            signingConfig = signingConfigs.getByName("debug")
            optimization {
                enable = false
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
    testOptions {
        unitTests.isReturnDefaultValues = true
    }
}

// Shared prompts and model catalogs come straight from the Python package, so the
// desktop and the phone always ship the same text. Only data files are copied.
abstract class SyncSharedAssets : DefaultTask() {
    @get:InputDirectory
    abstract val promptsDir: DirectoryProperty

    @get:InputDirectory
    abstract val clientsDir: DirectoryProperty

    @get:OutputDirectory
    abstract val outputDir: DirectoryProperty

    @get:Inject
    abstract val fs: FileSystemOperations

    @TaskAction
    fun sync() {
        fs.sync {
            from(promptsDir) {
                include("**/*.txt", "**/*.json")
                exclude("golden/**")
                into("prompts")
            }
            from(clientsDir) {
                include("*.json")
                into("catalogs")
            }
            into(outputDir)
        }
    }
}

val syncSharedAssets = tasks.register<SyncSharedAssets>("syncSharedAssets") {
    promptsDir.set(repoRoot.resolve("letter_writer/prompts"))
    clientsDir.set(repoRoot.resolve("letter_writer/clients"))
}

/** Fixture replies for the debug harness. Packaged only into debug builds, under assets/fixtures/. */
abstract class SyncDebugFixtures : DefaultTask() {
    @get:InputDirectory
    abstract val fixturesDir: DirectoryProperty

    @get:OutputDirectory
    abstract val outputDir: DirectoryProperty

    @get:Inject
    abstract val fs: FileSystemOperations

    @TaskAction
    fun sync() {
        fs.sync {
            from(fixturesDir)
            into(outputDir.get().dir("fixtures"))
        }
    }
}

val syncDebugFixtures = tasks.register<SyncDebugFixtures>("syncDebugFixtures") {
    fixturesDir.set(rootDir.resolve("debug/fixtures"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.assets?.addGeneratedSourceDirectory(syncSharedAssets, SyncSharedAssets::outputDir)
        if (variant.name.contains("debug")) {
            variant.sources.assets?.addGeneratedSourceDirectory(syncDebugFixtures, SyncDebugFixtures::outputDir)
        }
    }
}

tasks.withType<Test>().configureEach {
    systemProperty("letterwriter.repoRoot", repoRoot.absolutePath)
}

dependencies {
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.compose.material.icons.core)
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.process)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.datastore.preferences)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.kotlinx.coroutines.play.services)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.okhttp)
    implementation(libs.jsoup)
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.auth)
    implementation(libs.firebase.firestore)
    implementation(libs.androidx.credentials)
    implementation(libs.androidx.credentials.play.services)
    implementation(libs.googleid)
    implementation(libs.play.services.auth)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(libs.androidx.junit)
    debugImplementation(libs.androidx.compose.ui.test.manifest)
    debugImplementation(libs.androidx.compose.ui.tooling)
}
