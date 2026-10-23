plugins {
    id("com.android.application")
    id("kotlin-android")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

android {
    namespace = "com.xfocus.quranly.local"
    compileSdk = 36
    buildToolsVersion = "36.0.0"
    // Flutter 3.38.5 forceNdkDownload adds an empty CMake project during plugin
    // application. This path has no native sources/hooks, so clear that placeholder.
    // Reevaluate this override before introducing a native plugin or code asset.
    externalNativeBuild.cmake.path = null
    // No C/C++ sources or native plugins in this provisional path. Keep the
    // shipped Flutter engine symbols instead of downloading an NDK to strip them.
    packaging.jniLibs.keepDebugSymbols.add("**/*.so")

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = JavaVersion.VERSION_17.toString()
    }

    defaultConfig {
        // Provisional local review identity; final ownership remains a HITL choice.
        applicationId = "com.xfocus.quranly.local"
        testInstrumentationRunner = "com.xfocus.quranly.local.TafsirContractInstrumentation"
        minSdk = 35
        targetSdk = 36
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    buildTypes {
        debug {
            // Android's standard disposable debug key is authorized for local review.
            signingConfig = signingConfigs.getByName("debug")
        }
        release {
            signingConfig = null
        }
    }
}

flutter {
    source = "../.."
}
