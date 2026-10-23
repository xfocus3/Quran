package com.xfocus.quranly.local

import android.content.ContentValues
import android.database.DatabaseErrorHandler
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteDatabaseCorruptException
import android.database.sqlite.SQLiteException
import android.system.ErrnoException
import android.system.Os
import android.system.OsConstants
import java.io.Closeable
import java.io.File

class PersonalFailure(val code: String, cause: Throwable? = null) : Exception(code, cause)

/** Sole writable personal-data owner. Version 1 begins with preferences; later
 * personal schemas migrate here transactionally, never in the immutable pack.
 * Single activity worker serializes reads/writes/close. No auto-destructive
 * downgrade, reset, fallback file or SharedPreferences mirror on failure. */
class PersonalStore(private val file: File) : Closeable {
    private var database: SQLiteDatabase? = null
    private var ready = false

    // Throwing stops Android's corruption retry as well as its default deletion
    // of the DB, attached DBs and journal/WAL companions. Recovery belongs to
    // an explicit future repair flow, never a read or preference write.
    private val preserveCorruption = DatabaseErrorHandler {
        throw SQLiteDatabaseCorruptException("Personal database requires recovery")
    }

    /** File.exists() conflates absence with inaccessible/unknown storage. */
    private fun exists(path: File): Boolean = try {
        Os.lstat(path.path)
        true
    } catch (error: ErrnoException) {
        if (error.errno == OsConstants.ENOENT) false else throw error
    }

    private fun open(): SQLiteDatabase {
        database?.let { if (ready) return it }
        // A failed close retains ownership; retry cleanup before opening anew.
        close()
        val parent = file.parentFile ?: throw PersonalFailure("storage")
        if (!parent.isDirectory && !parent.mkdirs()) throw PersonalFailure("storage")
        val firstLaunch = !exists(file)
        if (firstLaunch && listOf("-journal", "-wal", "-shm").any { exists(File(file.path + it)) }) {
            throw PersonalFailure("storage")
        }
        try {
            if (!firstLaunch) {
                // Inspect versions without a writable open creating SQLite
                // metadata in an empty/unknown existing file. Never migrate v0
                // just because an existing file happens to report that version.
                database = SQLiteDatabase.openDatabase(file.path, null,
                    SQLiteDatabase.OPEN_READONLY or SQLiteDatabase.NO_LOCALIZED_COLLATORS,
                    preserveCorruption)
                if (database!!.version != 1) throw PersonalFailure("unsupportedVersion")
                close()
            }
            val opened = SQLiteDatabase.openDatabase(file.path, null,
                SQLiteDatabase.NO_LOCALIZED_COLLATORS or
                    (if (firstLaunch) SQLiteDatabase.CREATE_IF_NECESSARY else SQLiteDatabase.OPEN_READWRITE),
                preserveCorruption)
            database = opened
            if (firstLaunch && opened.version == 0) {
                opened.beginTransaction()
                try {
                    opened.execSQL("CREATE TABLE preferences (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL) WITHOUT ROWID")
                    opened.version = 1
                    opened.setTransactionSuccessful()
                } finally {
                    opened.endTransaction()
                }
            } else if (opened.version != 1) {
                throw PersonalFailure("unsupportedVersion")
            }
            ready = true
            return opened
        } catch (error: Exception) {
            closeAfterFailure(error)
            throw error
        }
    }

    private fun closeAfterFailure(error: Exception) {
        try { close() } catch (cleanup: Exception) { error.addSuppressed(cleanup) }
    }

    private fun storageFailure(error: Exception): Nothing {
        val failure = PersonalFailure("storage", error)
        closeAfterFailure(failure)
        throw failure
    }

    private fun <T> access(block: (SQLiteDatabase) -> T): T = try {
        block(open())
    } catch (error: SQLiteException) {
        storageFailure(error)
    } catch (error: SecurityException) {
        storageFailure(error)
    } catch (error: ErrnoException) {
        storageFailure(error)
    }

    /** Absence alone means first launch. Unknown saved authors are errors. */
    fun readTafsirBook(): String = access { db ->
        db.rawQuery("SELECT value FROM preferences WHERE key=?", arrayOf("tafsir_book")).use {
            if (!it.moveToFirst()) "ibn_kathir" else it.getString(0).also { book ->
                if (book !in TafsirBooks.ids) throw PersonalFailure("invalidData")
            }
        }
    }

    fun writeTafsirBook(book: String) {
        if (book !in TafsirBooks.ids) throw PersonalFailure("invalidData")
        access { db ->
            db.beginTransaction()
            try {
                val values = ContentValues().apply { put("key", "tafsir_book"); put("value", book) }
                if (db.insertWithOnConflict("preferences", null, values, SQLiteDatabase.CONFLICT_REPLACE) == -1L) {
                    throw PersonalFailure("storage")
                }
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }
    }

    override fun close() {
        ready = false
        database?.close()
        database = null
    }
}
