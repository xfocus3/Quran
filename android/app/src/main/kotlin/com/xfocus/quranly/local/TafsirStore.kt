package com.xfocus.quranly.local

import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteException
import android.system.ErrnoException
import android.system.Os
import android.system.OsConstants
import java.io.Closeable
import java.io.File
import java.io.FileNotFoundException
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest

class TafsirFailure(val code: String) : Exception(code)

object TafsirBooks {
    val ids = setOf("ibn_kathir", "al_tabari", "al_saadi")
}

data class TafsirContextRange(
    val fromAyah: Int, val toAyah: Int, val headingAyah: Int,
    val headingText: String, val basis: String, val rows: List<TafsirEntry>
) {
    fun payload() = mapOf("fromAyah" to fromAyah, "toAyah" to toAyah,
        "headingAyah" to headingAyah, "headingText" to headingText,
        "basis" to basis, "rows" to rows.map { it.payload() })
}

data class TafsirEntry(
    val book: String, val surah: Int, val ayah: Int, val rawText: String,
    val status: String, val context: TafsirContextRange? = null
) {
    // One source-format boundary; raw bytes and inert Unicode stay independent.
    val displayText: String by lazy { TafsirDisplay.render(rawText) }
    fun payload(): Map<String, Any?> = mapOf(
        "book" to book, "surah" to surah, "ayah" to ayah, "status" to status,
        "rawText" to rawText, "displayText" to displayText, "context" to context?.payload())
}

/** Owns immutable content installation/validation, never personal data.
 * Calls must be serialized by the owner. A failed install is retryable on the
 * next lookup; .part is never opened and is removed after errors/process death.
 * Only the selected entry and at most five context rows are materialized,
 * through the existing composite primary keys.
 */
class TafsirStore(private val directory: File, private val source: () -> InputStream) : Closeable {
    companion object {
        const val SHA256 = "2422b6e57acb21184e14c15a86b36b23e58a140c78e3e7a17b45863524fb9150"
        const val BYTES = 100519936L
        const val ASSET = "flutter_assets/.local/handoff/app/arabic-three-tafsirs.sqlite"
    }
    private var database: SQLiteDatabase? = null
    private var validatedFile: FileIdentity? = null

    // Cache validity belongs to the content owner, not to SQLite's page cache.
    // Nanosecond ctime also detects same-size writes with restored mtime; inode
    // identity detects path replacement while an old SQLite handle is open.
    private data class FileIdentity(
        val device: Long, val inode: Long, val size: Long, val mode: Int,
        val modifiedSeconds: Long, val modifiedNanos: Long,
        val changedSeconds: Long, val changedNanos: Long
    )

    private fun identity(file: File): FileIdentity? = try {
        val stat = Os.stat(file.path)
        FileIdentity(stat.st_dev, stat.st_ino, stat.st_size, stat.st_mode,
            stat.st_mtim.tv_sec, stat.st_mtim.tv_nsec,
            stat.st_ctim.tv_sec, stat.st_ctim.tv_nsec)
    } catch (error: ErrnoException) {
        if (error.errno == OsConstants.ENOENT) null else throw TafsirFailure("storage")
    }

    private fun sha256(file: File): String {
        val hash = MessageDigest.getInstance("SHA-256")
        file.inputStream().use { stream ->
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                hash.update(buffer, 0, count)
            }
        }
        return hash.digest().joinToString("") { "%02x".format(it) }
    }

    private fun verified(file: File) = file.isFile && file.length() == BYTES && sha256(file) == SHA256

    private fun open(): SQLiteDatabase {
        val target = File(directory, "$SHA256.sqlite")
        database?.let {
            if (validatedFile != null && identity(target) == validatedFile) return it
            // Never serve pages cached from changed/replaced/deleted content.
            close()
        }
        if (!directory.isDirectory && !directory.mkdirs()) throw TafsirFailure("storage")
        val partial = File(directory, "$SHA256.part")
        try {
            if (partial.exists() && !partial.delete()) throw TafsirFailure("storage")
            if (!verified(target)) {
                // Replace only our content file. No personal database shares this directory.
                if (target.exists() && !target.delete()) throw TafsirFailure("storage")
                val input = try {
                    source()
                } catch (_: FileNotFoundException) {
                    throw TafsirFailure("missingAsset")
                }
                input.use {
                    FileOutputStream(partial).use { output ->
                        val buffer = ByteArray(64 * 1024)
                        var copied = 0L
                        while (true) {
                            val count = input.read(buffer)
                            if (count < 0) break
                            copied += count
                            if (copied > BYTES) throw TafsirFailure("corruptPack")
                            output.write(buffer, 0, count)
                        }
                        output.fd.sync()
                    }
                }
                if (!verified(partial)) throw TafsirFailure("corruptPack")
                if (!partial.renameTo(target)) throw TafsirFailure("storage")
            }
            if (!target.setReadOnly()) throw TafsirFailure("storage")
            val validatingFile = identity(target) ?: throw TafsirFailure("corruptPack")
            // Check installed bytes too, including after copying/renaming.
            if (!verified(target)) throw TafsirFailure("corruptPack")
            val opened = SQLiteDatabase.openDatabase(target.path, null, SQLiteDatabase.OPEN_READONLY)
            try {
                fun scalar(sql: String): String = opened.rawQuery(sql, null).use {
                    if (!it.moveToFirst()) throw TafsirFailure("invalidSchema")
                    it.getString(0)
                }
                if (scalar("PRAGMA integrity_check") != "ok" ||
                    scalar("PRAGMA user_version") != "1" ||
                    scalar("SELECT value FROM metadata WHERE key='schema_version'") != "1" ||
                    scalar("SELECT value FROM metadata WHERE key='language'") != "ar" ||
                    scalar("SELECT title_ar FROM tafseer_books WHERE id='ibn_kathir' AND language='ar' AND source_table='tafsir_katheer'") != "تفسير القرآن العظيم — ابن كثير" ||
                    scalar("SELECT count(*) FROM surahs") != "114" ||
                    scalar("SELECT count(*) FROM tafseer_entries WHERE tafseer_id='ibn_kathir' AND content_status='source_text'") != "6236" ||
                    scalar("SELECT count(*) FROM tafseer_entries WHERE tafseer_id='al_tabari'") != "6236" ||
                    scalar("SELECT count(*) FROM tafseer_entries WHERE tafseer_id='al_saadi' AND content_status='source_text'") != "6236" ||
                    scalar("SELECT count(*) FROM tafseer_entries WHERE content_status='empty_markup'") != "7" ||
                    scalar("SELECT count(*) FROM tafseer_context_ranges") != "7") {
                    throw TafsirFailure("invalidSchema")
                }
                if (identity(target) != validatingFile) throw TafsirFailure("corruptPack")
                validatedFile = validatingFile
                database = opened
                return opened
            } catch (error: Exception) {
                opened.close()
                throw error
            }
        } finally {
            partial.delete()
        }
    }

    /** Selected identity never redirects to the heading. Context is additional
     * ordered source rows, with their original status and raw bytes intact. */
    fun lookup(book: String, surah: Int, ayah: Int): TafsirEntry {
        if (book !in TafsirBooks.ids) throw TafsirFailure("invalidBook")
        if (surah !in 1..114 || ayah < 1) throw TafsirFailure("invalidReference")
        try {
            val db = open()
            val maxAyah = db.rawQuery("SELECT ayah_count FROM surahs WHERE surah=?", arrayOf("$surah")).use {
                if (!it.moveToFirst() || ayah > it.getInt(0)) throw TafsirFailure("invalidReference")
                it.getInt(0)
            }
            fun row(a: Int, raw: String, status: String): TafsirEntry {
                if (raw.isEmpty() || status !in setOf("source_text", "empty_markup")) throw TafsirFailure("invalidContent")
                val entry = TafsirEntry(book, surah, a, raw, status)
                if (status == "source_text" && entry.displayText.isBlank()) throw TafsirFailure("invalidContent")
                return entry
            }
            val selected = db.rawQuery(
                "SELECT text,content_status FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah=? LIMIT 2",
                arrayOf(book, "$surah", "$ayah")
            ).use {
                if (!it.moveToFirst()) throw TafsirFailure("missingEntry")
                val entry = row(ayah, it.getString(0), it.getString(1))
                if (it.moveToNext()) throw TafsirFailure("invalidContent")
                entry
            }
            val context = db.rawQuery(
                "SELECT from_ayah,to_ayah,heading_ayah,heading_text,basis FROM tafseer_context_ranges WHERE tafseer_id=? AND surah=? AND ayah=? LIMIT 2",
                arrayOf(book, "$surah", "$ayah")
            ).use { cursor ->
                if (!cursor.moveToFirst()) null else {
                    val from = cursor.getInt(0)
                    val to = cursor.getInt(1)
                    val heading = cursor.getInt(2)
                    val headingText = cursor.getString(3)
                    val basis = cursor.getString(4)
                    if (from < 1 || to > maxAyah || ayah !in from..to ||
                        to - from > 4 || heading !in from..to || cursor.moveToNext()) {
                        throw TafsirFailure("invalidContent")
                    }
                    val rows = db.rawQuery(
                        "SELECT ayah,text,content_status FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah BETWEEN ? AND ? ORDER BY ayah LIMIT 6",
                        arrayOf(book, "$surah", "$from", "$to")
                    ).use { entries ->
                        val result = mutableListOf<TafsirEntry>()
                        while (entries.moveToNext()) {
                            val a = entries.getInt(0)
                            if (a != from + result.size) throw TafsirFailure("invalidContent")
                            result.add(row(a, entries.getString(1), entries.getString(2)))
                        }
                        if (result.size != to - from + 1 || result[ayah - from] != selected) {
                            throw TafsirFailure("invalidContent")
                        }
                        result.toList()
                    }
                    TafsirContextRange(from, to, heading, headingText, basis, rows)
                }
            }
            if (selected.status == "empty_markup" && context == null) throw TafsirFailure("invalidContent")
            // Preserve active-cache file tamper/lifecycle protection for the
            // complete selection and context, including every bounded query.
            if (identity(File(directory, "$SHA256.sqlite")) != validatedFile) {
                close()
                throw TafsirFailure("corruptPack")
            }
            return selected.copy(context = context)
        } catch (error: TafsirFailure) {
            throw error
        } catch (_: SQLiteException) {
            close()
            throw TafsirFailure("corruptPack")
        } catch (_: IOException) {
            close()
            throw TafsirFailure("storage")
        } catch (_: SecurityException) {
            close()
            throw TafsirFailure("storage")
        }
    }

    override fun close() {
        database?.close()
        database = null
        validatedFile = null
    }
}
