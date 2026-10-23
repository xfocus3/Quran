package com.xfocus.quranly.local

import android.content.Intent
import android.os.Handler
import android.os.Looper
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.util.concurrent.Executors

class MainActivity : FlutterActivity() {
    private var channel: MethodChannel? = null
    private var personalChannel: MethodChannel? = null
    private var shareChannel: MethodChannel? = null
    private val imageShare by lazy { ReaderImageShare(applicationContext) }
    private val worker = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private var attached = false
    private val store by lazy {
        TafsirStore(File(applicationContext.noBackupFilesDir, "immutable-tafsir")) {
            applicationContext.assets.open(TafsirStore.ASSET)
        }
    }

    private val personal by lazy {
        PersonalStore(File(applicationContext.noBackupFilesDir, "personal/personal.sqlite"))
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        attached = true
        channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "quranly/tafsir")
        channel!!.setMethodCallHandler { call, result ->
            if (call.method != "lookup") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val arguments = call.arguments as? Map<*, *>
            val book = arguments?.get("book")
            if (book !is String || book !in TafsirBooks.ids) {
                result.error("invalidBook", null, null)
                return@setMethodCallHandler
            }
            val surah = arguments?.get("surah")
            val ayah = arguments?.get("ayah")
            if (surah !is Int || ayah !is Int) {
                result.error("invalidReference", null, null)
                return@setMethodCallHandler
            }
            worker.execute {
                try {
                    val payload = store.lookup(book, surah, ayah).payload()
                    main.post { if (attached) result.success(payload) }
                } catch (error: TafsirFailure) {
                    main.post { if (attached) result.error(error.code, null, null) }
                }
            }
        }

        shareChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "quranly/share")
        shareChannel!!.setMethodCallHandler { call, result ->
            if (call.method != "shareImage") {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val args = call.arguments as? Map<*, *>
            val surah = args?.get("surah")
            val ayah = args?.get("ayah")
            val png = args?.get("png")
            if (surah !is Int || ayah !is Int || png !is ByteArray) {
                result.error("invalidData", null, null)
                return@setMethodCallHandler
            }
            worker.execute {
                try {
                    val intent = imageShare.prepare(surah, ayah, png)
                    main.post {
                        if (!attached) return@post
                        try {
                            startActivity(Intent.createChooser(intent, "Share"))
                            result.success(null)
                        } catch (error: Exception) {
                            result.error("unavailable", null, null)
                        }
                    }
                } catch (error: Exception) {
                    main.post { if (attached) result.error("unavailable", null, null) }
                }
            }
        }

        personalChannel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, "quranly/personal")
        personalChannel!!.setMethodCallHandler { call, result ->
            if (call.method !in setOf("readTafsirBook", "writeTafsirBook")) {
                result.notImplemented()
                return@setMethodCallHandler
            }
            val book = (call.arguments as? Map<*, *>)?.get("book")
            if (call.method == "writeTafsirBook" && (book !is String || book !in TafsirBooks.ids)) {
                result.error("invalidData", null, null)
                return@setMethodCallHandler
            }
            worker.execute {
                try {
                    val value = if (call.method == "readTafsirBook") personal.readTafsirBook() else {
                        personal.writeTafsirBook(book as String)
                        null
                    }
                    main.post { if (attached) result.success(value) }
                } catch (error: PersonalFailure) {
                    main.post { if (attached) result.error(error.code, null, null) }
                }
            }
        }
    }

    override fun cleanUpFlutterEngine(flutterEngine: FlutterEngine) {
        attached = false
        channel?.setMethodCallHandler(null)
        channel = null
        personalChannel?.setMethodCallHandler(null)
        personalChannel = null
        shareChannel?.setMethodCallHandler(null)
        shareChannel = null
        // Finish an atomic installation already in progress, then close its DB.
        // A disposed Dart route ignores its result; no reader state is mutated.
        worker.execute {
            try { store.close() } finally { personal.close() }
        }
        worker.shutdown()
        super.cleanUpFlutterEngine(flutterEngine)
    }
}
