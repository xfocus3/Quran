package com.xfocus.quranly.local

import android.content.ClipData
import android.content.Context
import android.content.Intent
import android.graphics.BitmapFactory
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File

class ReaderShareProvider : FileProvider()

/** Owns only transient image exports. Never accepts a caller path or touches
 * immutable content/personal state. URI grants let the user-selected app read
 * the PNG after this activity backgrounds; chooser launch is not delivery.
 */
class ReaderImageShare(private val context: Context) {
    private val counts by lazy {
        val source = context.assets.open("flutter_assets/.local/handoff/app/quran.json")
            .bufferedReader().use { JSONObject(it.readText()).getJSONArray("surahs") }
        IntArray(source.length()) { source.getJSONObject(it).getInt("ayah_count") }
    }

    fun prepare(surah: Int, ayah: Int, png: ByteArray): Intent {
        require(surah in 1..counts.size && ayah in 1..counts[surah - 1]) { "invalidReference" }
        require(png.size in 8..16 * 1024 * 1024 &&
            png.take(8).toByteArray().contentEquals(byteArrayOf(-119, 80, 78, 71, 13, 10, 26, 10))) { "invalidImage" }
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(png, 0, png.size, bounds)
        require(bounds.outMimeType == "image/png" && bounds.outWidth > 0 && bounds.outHeight > 0 &&
            bounds.outWidth.toLong() * bounds.outHeight <= 32_000_000) { "invalidImage" }
        val directory = File(context.cacheDir, "reader-share")
        check(directory.isDirectory || directory.mkdirs()) { "storage" }
        // Only our expired exports, never other caches or an active export. Do
        // not delete on chooser return: a recipient may still be reading it.
        val cutoff = System.currentTimeMillis() - 24 * 60 * 60 * 1000L
        directory.listFiles()?.filter { it.isFile && it.name.startsWith("verse-") && it.lastModified() < cutoff }
            ?.forEach { it.delete() }
        val file = File.createTempFile("verse-$surah-$ayah-", ".png", directory)
        try {
            file.outputStream().use { it.write(png) }
            val uri = FileProvider.getUriForFile(context, "${context.packageName}.reader.share_provider", file)
            return Intent(Intent.ACTION_SEND).apply {
                type = "image/png"
                putExtra(Intent.EXTRA_STREAM, uri)
                putExtra(Intent.EXTRA_TEXT, "Verse $ayah, Surah $surah shared via https://quranly.app !")
                clipData = ClipData.newUri(context.contentResolver, "Verse $ayah, Surah $surah", uri)
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
        } catch (error: Exception) {
            file.delete()
            throw error
        }
    }
}
