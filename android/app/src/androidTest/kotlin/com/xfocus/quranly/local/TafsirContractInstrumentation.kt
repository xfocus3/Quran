package com.xfocus.quranly.local

import android.app.Activity
import android.app.Instrumentation
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import java.io.ByteArrayOutputStream
import android.os.Bundle
import android.system.Os
import org.json.JSONObject
import java.io.ByteArrayInputStream
import java.io.File
import java.io.FileNotFoundException
import java.io.FilterInputStream
import java.io.IOException
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.file.Files
import java.nio.file.attribute.FileTime
import java.security.MessageDigest
import java.time.Instant

/** Parent runs this explicitly on API35. No SQLite/Android mocks, no JUnit
 * runner dependency and no diagnostic entry point in the production APK.
 * am instrument -w com.xfocus.quranly.local.test/.TafsirContractInstrumentation
 */
class TafsirContractInstrumentation : Instrumentation() {
    override fun onCreate(arguments: Bundle?) {
        super.onCreate(arguments)
        start()
    }

    override fun onStart() {
        val results = Bundle()
        val directory = File(targetContext.cacheDir, "phase4-contract")
        directory.deleteRecursively()
        try {
            val source = { targetContext.assets.open(TafsirStore.ASSET) }
            val quran = JSONObject(targetContext.assets.open("flutter_assets/.local/handoff/app/quran.json")
                .bufferedReader().use { it.readText() })
            val surahs = quran.getJSONArray("surahs")
            val expectedHashes = mapOf(
                "ibn_kathir" to "9ccd21c5706542735f5c2927d9415160b1e638508cab6ce34c52f06e30c8b54e",
                "al_tabari" to "499f32e52e1f90d5c01e003b99926ecc18b8fbe5eb730de8837ad6bdcaef46ee",
                "al_saadi" to "f6eeb49365b3fad1342b06b126da643f734a1439ef7109b9ac5a94e59edf4377")
            var count = 0
            var sourceBomCount = 0
            TafsirStore(directory, source).use { store ->
                for ((book, expectedHash) in expectedHashes) {
                    val hash = MessageDigest.getInstance("SHA-256")
                    var bookCount = 0
                    var emptyCount = 0
                    for (s in 0 until surahs.length()) {
                        val metadata = surahs.getJSONObject(s)
                        for (a in 1..metadata.getInt("ayah_count")) {
                            val entry = store.lookup(book, s + 1, a)
                            check(entry.surah == s + 1 && entry.ayah == a && entry.book == book)
                            check(entry.status in setOf("source_text", "empty_markup"))
                            val bytes = entry.rawText.toByteArray(Charsets.UTF_8)
                            // Parent independent contract: big endian uint32 s/a,
                            // uint64 raw UTF8 byte length, then exact UTF8 bytes.
                            hash.update(ByteBuffer.allocate(16).putInt(s + 1).putInt(a).putLong(bytes.size.toLong()).array())
                            hash.update(bytes)
                            results.putString("stage", "display $book ${s + 1}:$a")
                            assertDisplay(entry)
                            sourceBomCount += entry.rawText.count { it == '\uFEFF' }
                            if (entry.status == "empty_markup") {
                                emptyCount++
                                check(entry.rawText == "<br>" && entry.displayText.isBlank())
                                check(entry.context != null)
                            }
                            bookCount++
                        }
                    }
                    check(bookCount == 6236)
                    check(emptyCount == if (book == "al_tabari") 7 else 0)
                    val actualHash = hex(hash.digest())
                    check(actualHash == expectedHash) { "Raw digest differs for $book: $actualHash" }
                    results.putString("raw_sha256_$book", actualHash)
                    count += bookCount
                }
                check(count == 18708)
                check(sourceBomCount == 113)
                results.putInt("source_bom_characters", sourceBomCount)
                results.putString("stage", "seven contexts")
                checkContexts(store)
                results.putString("stage", "source edge cases")
                val leadingBom = store.lookup("al_tabari", 2, 1)
                check(sha(leadingBom.rawText) == "f932fb230eee899e9e4ffead08d216842f31f4e7f4214efef6de7d1d09fb3cb5")
                check(leadingBom.rawText.startsWith("\uFEFF<br>"))
                check(leadingBom.displayText.startsWith("\uFEFF\nالقولُ"))
                val tabari = store.lookup("al_tabari", 2, 196)
                check(tabari.rawText.length == 169857)
                val saadi = store.lookup("al_saadi", 12, 111)
                check(saadi.rawText.length == 18983)
                val wordBreak = store.lookup("al_tabari", 1, 1)
                check(wordBreak.rawText.contains("عن<br>دَ"))
                check(wordBreak.displayText.contains("عن\nدَ"))
                val literal = store.lookup("al_tabari", 2, 282)
                check(literal.rawText.contains("<<br>"))
                check(literal.displayText.contains("<\n"))
                val unmatched = store.lookup("al_tabari", 74, 9)
                check(unmatched.rawText.count { it == '¬' } == 10)
                check(unmatched.rawText.count { it == '¥' } == 9)
                val continuation = store.lookup("al_tabari", 74, 10)
                check(continuation.rawText.count { it == '¬' } == 0)
                check(continuation.rawText.count { it == '¥' } == 1)
                expectFailure("invalidBook") { store.lookup("unknown", 1, 1) }
                val first = store.lookup("ibn_kathir", 1, 1)
                check(first.rawText.length == 131238)
                check(first.rawText.contains("\r\nقال ابن عطية"))
                check(first.displayText.contains("\nقال ابن عطية"))
                check(sha(first.rawText) == "2482e89fb073e6f66d4d12272a56f7f7111189e96aebcdb052395d43405222f3")
                check(first.displayText.contains("ولم ترد هذه قراءةً عن أحد فيما علمت."))
                check(first.displayText.contains("¬في \"تفسيره\" (1/ 93).¥"))
                check(store.lookup("ibn_kathir", 20, 125).rawText == "أي: في الدنيا.")
                check(sha(store.lookup("ibn_kathir", 114, 6).rawText) == "c6fff5604e01734c193c92f51cbd42090e25a227f530c576c2a2ad634b3140b4")
                for ((s, a) in listOf(0 to 1, 115 to 1, 1 to 8, 114 to 7, 20 to 0)) {
                    expectFailure("invalidReference") { store.lookup("ibn_kathir", s, a) }
                }
                repeat(20) { check(store.lookup("ibn_kathir", 20, 125).rawText == "أي: في الدنيا.") }
            }
            results.putString("stage", "immutable installation/cache recovery")
            // Interrupted installation leaves only a disposable partial; it must
            // never replace the valid installed content on the next opening.
            File(directory, "${TafsirStore.SHA256}.part").writeText("interrupted")
            // Reopen installed bytes, then recover corrupted installed content.
            TafsirStore(directory) { error("Verified installed pack should be reused") }.use {
                check(it.lookup("ibn_kathir", 20, 125).rawText == "أي: في الدنيا.")
            }
            val installed = File(directory, "${TafsirStore.SHA256}.sqlite")
            // Active cached handles must not hide same-size content edits, even
            // if mtime is restored. A failed repair remains retryable in-place.
            var repairAvailable = true
            TafsirStore(directory) {
                if (repairAvailable) source() else throw FileNotFoundException()
            }.use { store ->
                check(store.lookup("ibn_kathir", 20, 125).rawText == "أي: في الدنيا.")
                val originalStat = Os.stat(installed.path)
                check(installed.setWritable(true))
                RandomAccessFile(installed, "rw").use { file ->
                    // SQLite user_version, leaving file size and target row intact.
                    file.seek(63)
                    file.writeByte(2)
                }
                check(installed.setReadOnly())
                Files.setLastModifiedTime(installed.toPath(), FileTime.from(
                    Instant.ofEpochSecond(originalStat.st_mtim.tv_sec, originalStat.st_mtim.tv_nsec)))
                repairAvailable = false
                expectFailure("missingAsset") { store.lookup("ibn_kathir", 20, 125) }
                check(!File(directory, "${TafsirStore.SHA256}.part").exists())
                repairAvailable = true
                check(store.lookup("ibn_kathir", 1, 1).rawText.length == 131238)
                // Replace the inode, then delete the path with the DB still open.
                val replacement = File(directory, "replacement.sqlite")
                replacement.writeText("invalid replacement")
                check(replacement.renameTo(installed))
                check(store.lookup("ibn_kathir", 20, 125).rawText == "أي: في الدنيا.")
                check(installed.delete())
                check(store.lookup("ibn_kathir", 114, 6).rawText.isNotEmpty())
            }
            installed.setWritable(true)
            RandomAccessFile(installed, "rw").use { it.writeByte(0) }
            TafsirStore(directory, source).use { check(it.lookup("ibn_kathir", 20, 125).rawText == "أي: في الدنيا.") }
            directory.deleteRecursively()
            var mode = "missing"
            TafsirStore(directory) {
                when (mode) {
                    "missing" -> throw FileNotFoundException()
                    "corrupt" -> ByteArrayInputStream(byteArrayOf(1, 2, 3))
                    "interrupted" -> object : FilterInputStream(source()) {
                        private var readOnce = false
                        override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
                            if (readOnce) throw IOException("Interrupted source read")
                            readOnce = true
                            return super.read(buffer, offset, length)
                        }
                    }
                    else -> source()
                }
            }.use {
                expectFailure("missingAsset") { it.lookup("ibn_kathir", 1, 1) }
                mode = "corrupt"
                expectFailure("corruptPack") { it.lookup("ibn_kathir", 1, 1) }
                mode = "interrupted"
                expectFailure("storage") { it.lookup("ibn_kathir", 1, 1) }
                check(!File(directory, "${TafsirStore.SHA256}.part").exists())
                check(!File(directory, "${TafsirStore.SHA256}.sqlite").exists())
                mode = "valid"
                check(it.lookup("ibn_kathir", 1, 1).rawText.length == 131238)
            }
            directory.deleteRecursively()
            directory.writeText("not a directory")
            expectFailure("storage") {
                TafsirStore(directory, source).use { it.lookup("ibn_kathir", 1, 1) }
            }
            directory.delete()
            results.putString("stage", "personal integrity/corruption/rollback")
            checkPersonalStore()
            results.putString("stage", "image share URI/identity")
            checkImageShare()
            results.putString("image_share_contract", "passed")
            results.putString("stage", "complete")
            results.putString("result", "passed")
            results.putInt("identities", count)
            results.putInt("contexts", 7)
            results.putString("coverage", "real SQLite/source-format display; all 18708 keys and three independent raw digests; seven ordered complete contexts; CRLF/br-inside-word/literal markup/113 source BOMs/cross-entry footnotes; personal version/first-launch/write/reopen/rollback/corrupt bytes and companions preserved/read-write retry/unreadable/orphan evidence; long/short/end; invalid keys; repeated/reopen; cached edit/restored mtime/replace/delete/failed repair; missing/corrupt/interrupted source/retry")
            finish(Activity.RESULT_OK, results)
        } catch (error: Throwable) {
            results.putString("result", "FAILED")
            results.putString("error", error.stackTraceToString())
            finish(Activity.RESULT_CANCELED, results)
        } finally {
            directory.deleteRecursively()
        }
    }

    /** Independent literal oracle for the fully inventoried, digest-pinned pack.
     * No production formatter calls or Unicode stripping. Every row and context
     * retains the non-whitespace/marker checks plus exact breaks/whitespace. */
    private fun assertDisplay(entry: TafsirEntry) {
        val visible = entry.rawText.replace("\r\n", "\n").replace("\r", "\n")
            .replace("<br>", "\n").replace("</div>", "\n")
            .replace("<p>", "\n").replace("</p>", "\n").replace("&nbsp;", "\u00a0")
        fun compact(text: String) = text.filterNot { it.isWhitespace() || it == '\u00a0' }
        check(compact(visible) == compact(entry.displayText)) { displayMismatch(entry, visible) }
        check(visible == entry.displayText) { displayMismatch(entry, visible) }
        check(!entry.displayText.contains('\r'))
        for (marker in listOf('¬', '¥')) {
            check(entry.rawText.count { it == marker } == entry.displayText.count { it == marker }) {
                "Footnote U+%04X differs: %s".format(marker.code, displayMismatch(entry, visible))
            }
        }
    }

    private fun displayMismatch(entry: TafsirEntry, expected: String): String {
        val actual = entry.displayText
        val limit = minOf(expected.length, actual.length)
        var offset = 0
        while (offset < limit && expected[offset] == actual[offset]) offset++
        // Bounded code-point windows expose invisible characters without dumping
        // long private source rows. Offsets/lengths are explicitly UTF-16 units.
        fun window(text: String): String = text.substring(maxOf(0, offset - 6), minOf(text.length, offset + 12))
            .codePoints().toArray().joinToString(" ") { "U+%04X".format(it) }
        return "Display differs at ${entry.book} ${entry.surah}:${entry.ayah} status=${entry.status}; " +
            "first_utf16_offset=$offset raw_length=${entry.rawText.length} expected_length=${expected.length} actual_length=${actual.length}; " +
            "raw_sha256=${sha(entry.rawText)} expected_sha256=${sha(expected)} actual_sha256=${sha(actual)}; " +
            "expected=[${window(expected)}] actual=[${window(actual)}]"
    }

    private fun checkContexts(store: TafsirStore) {
        // Values pinned from parent lookup-contract.json, never computed by the
        // adapter or by querying the database under test to obtain expectations.
        val cases = JSONObject("""
{
  "contexts": [
    {
      "book": "al_tabari",
      "surah": 4,
      "selected": 168,
      "from": 168,
      "to": 169,
      "heading": 169,
      "basis": "Source-derived numbered passage heading in neighboring row; context, not a replacement standalone verse commentary",
      "heading_sha256": "f2162786a1103ba03bada8fb199adee17e3d1b275e3eeb5c034b17ca4a73df21",
      "source_rows": [
        {
          "ayah": 168,
          "status": "empty_markup",
          "characters": 4,
          "sha256": "65aef1adba8672a5fe7932d9f9f0dc35c2435893f65112acac628d2dc17a0bcf"
        },
        {
          "ayah": 169,
          "status": "source_text",
          "characters": 1667,
          "sha256": "267c3f0c1508aa69a6528163432aea48e11696646afae02dfef6f88d88e22f45"
        }
      ]
    },
    {
      "book": "al_tabari",
      "surah": 26,
      "selected": 16,
      "from": 15,
      "to": 17,
      "heading": 15,
      "basis": "Source-derived numbered passage heading in neighboring row; context, not a replacement standalone verse commentary",
      "heading_sha256": "e48439c118c53708d91ba77cc2f90d29c02ef87ba9080c4518e464614ed1e7ff",
      "source_rows": [
        {
          "ayah": 15,
          "status": "source_text",
          "characters": 480,
          "sha256": "a5e68d82fc80a804682ad725c2e8060ec5e7696f2e3a6aed0de3fb0184a14eca"
        },
        {
          "ayah": 16,
          "status": "empty_markup",
          "characters": 4,
          "sha256": "65aef1adba8672a5fe7932d9f9f0dc35c2435893f65112acac628d2dc17a0bcf"
        },
        {
          "ayah": 17,
          "status": "source_text",
          "characters": 854,
          "sha256": "a1060dd8a550e7a1d8135d886826646d3ecffe29ce0223f8952dfdacd5371be1"
        }
      ]
    },
    {
      "book": "al_tabari",
      "surah": 26,
      "selected": 205,
      "from": 205,
      "to": 207,
      "heading": 206,
      "basis": "Source-derived numbered passage heading in neighboring row; context, not a replacement standalone verse commentary",
      "heading_sha256": "3d91d9e225d5fd9142c682650e1ab075d39e5e8d19a6960ccf8933d9529224ad",
      "source_rows": [
        {
          "ayah": 205,
          "status": "empty_markup",
          "characters": 4,
          "sha256": "65aef1adba8672a5fe7932d9f9f0dc35c2435893f65112acac628d2dc17a0bcf"
        },
        {
          "ayah": 206,
          "status": "source_text",
          "characters": 285,
          "sha256": "985eb8756cf39a2bb7414ef213c732d0ab639f1c97d4b8e1bc54eb54b2cbf335"
        },
        {
          "ayah": 207,
          "status": "source_text",
          "characters": 630,
          "sha256": "8eef8659082d29fb97f82ede96e6ba28febe028841dd95049e05d4b03ec48c0a"
        }
      ]
    },
    {
      "book": "al_tabari",
      "surah": 37,
      "selected": 25,
      "from": 24,
      "to": 27,
      "heading": 24,
      "basis": "Source-derived numbered passage heading in neighboring row; context, not a replacement standalone verse commentary",
      "heading_sha256": "a899bf7580bd6c51151c185cdf53fd3c1aa4ee1a48557e04d33a9c0761ae467a",
      "source_rows": [
        {
          "ayah": 24,
          "status": "source_text",
          "characters": 2100,
          "sha256": "4940bc168482d24c935f7178f43dee481045bcf7d93f9ec37bd43ce3a8b21f53"
        },
        {
          "ayah": 25,
          "status": "empty_markup",
          "characters": 4,
          "sha256": "65aef1adba8672a5fe7932d9f9f0dc35c2435893f65112acac628d2dc17a0bcf"
        },
        {
          "ayah": 26,
          "status": "source_text",
          "characters": 666,
          "sha256": "259d8df43c987d9a46348aea6326176f18393418b5840b20dcd28815abbdc329"
        },
        {
          "ayah": 27,
          "status": "source_text",
          "characters": 308,
          "sha256": "26a39fba11d8d2a05594855194861dbac2c0cdd2a484f36f02894825272b21d0"
        }
      ]
    },
    {
      "book": "al_tabari",
      "surah": 37,
      "selected": 62,
      "from": 62,
      "to": 66,
      "heading": 63,
      "basis": "Source-derived numbered passage heading in neighboring row; context, not a replacement standalone verse commentary",
      "heading_sha256": "f4eabb15092f60b9ac867b446f14dadd6a49d4e22560da7b26606982c23c5de2",
      "source_rows": [
        {
          "ayah": 62,
          "status": "empty_markup",
          "characters": 4,
          "sha256": "65aef1adba8672a5fe7932d9f9f0dc35c2435893f65112acac628d2dc17a0bcf"
        },
        {
          "ayah": 63,
          "status": "source_text",
          "characters": 752,
          "sha256": "2a7a78f7e681de55bdd0cad523a92f5b94f07d3bd5f642f5064c9df19abf8f3f"
        },
        {
          "ayah": 64,
          "status": "source_text",
          "characters": 1601,
          "sha256": "e858edc8f68f4d731906fc8ae68ce3402653c0bbb7e1638ac166701240990cc4"
        },
        {
          "ayah": 65,
          "status": "source_text",
          "characters": 2010,
          "sha256": "1358da400bceebeb31942384f318b343fbeea68c9998436fb9331634306053ea"
        },
        {
          "ayah": 66,
          "status": "source_text",
          "characters": 346,
          "sha256": "abe672ea8ef18cd62aff4698f7055f45e35c24c9da898dce2b36ec01b1ea4720"
        }
      ]
    },
    {
      "book": "al_tabari",
      "surah": 37,
      "selected": 103,
      "from": 103,
      "to": 106,
      "heading": 104,
      "basis": "Source-derived numbered passage heading in neighboring row; context, not a replacement standalone verse commentary",
      "heading_sha256": "6b8feb431d2b220058569357b37cb2a2ab31cc92aa9920a45098b64659c21d2d",
      "source_rows": [
        {
          "ayah": 103,
          "status": "empty_markup",
          "characters": 4,
          "sha256": "65aef1adba8672a5fe7932d9f9f0dc35c2435893f65112acac628d2dc17a0bcf"
        },
        {
          "ayah": 104,
          "status": "source_text",
          "characters": 4708,
          "sha256": "afb984896b7e2a4076ccc2b52fbcefa8e4f5eab8c7e849d4f0eee0f8d8b4bacf"
        },
        {
          "ayah": 105,
          "status": "source_text",
          "characters": 643,
          "sha256": "c0664c1e7d0a167ebacd7a0bb413163b2e3773b49b2cc60c8b59727b678772a4"
        },
        {
          "ayah": 106,
          "status": "source_text",
          "characters": 627,
          "sha256": "84054680cfbeedd14121e0f98ddd62e0339b43df284ba248346831cb9c8b45ed"
        }
      ]
    },
    {
      "book": "al_tabari",
      "surah": 50,
      "selected": 13,
      "from": 12,
      "to": 14,
      "heading": 12,
      "basis": "Source-derived numbered passage heading in neighboring row; context, not a replacement standalone verse commentary",
      "heading_sha256": "1a49ffee449653c11788defc94da1751f3ef244c6904dbf5d75ae2ffcf2f0e4a",
      "source_rows": [
        {
          "ayah": 12,
          "status": "source_text",
          "characters": 1247,
          "sha256": "9c61e471925d4885978fdc3ee6e6decd4c4900fd3f5fa649ee7304e18153dabc"
        },
        {
          "ayah": 13,
          "status": "empty_markup",
          "characters": 4,
          "sha256": "65aef1adba8672a5fe7932d9f9f0dc35c2435893f65112acac628d2dc17a0bcf"
        },
        {
          "ayah": 14,
          "status": "source_text",
          "characters": 6026,
          "sha256": "767e3366cccf492d0e34dc6f65c1c0520c45e5e4ba6c2b19b0b174e4da0dd60d"
        }
      ]
    }
  ]
}
""").getJSONArray("contexts")
        for (i in 0 until cases.length()) {
            val expected = cases.getJSONObject(i)
            val s = expected.getInt("surah")
            val a = expected.getInt("selected")
            val entry = store.lookup("al_tabari", s, a)
            check(entry.book == "al_tabari" && entry.surah == s && entry.ayah == a)
            check(entry.rawText == "<br>" && entry.status == "empty_markup")
            val context = checkNotNull(entry.context)
            check(context.fromAyah == expected.getInt("from"))
            check(context.toAyah == expected.getInt("to"))
            check(context.headingAyah == expected.getInt("heading"))
            check(sha(context.headingText) == expected.getString("heading_sha256"))
            check(context.basis == expected.getString("basis"))
            val rows = expected.getJSONArray("source_rows")
            check(context.rows.size == rows.length())
            for (j in 0 until rows.length()) {
                val row = context.rows[j]
                val pinned = rows.getJSONObject(j)
                check(row.book == entry.book && row.surah == s && row.ayah == pinned.getInt("ayah"))
                check(row.status == pinned.getString("status"))
                check(row.rawText.length == pinned.getInt("characters"))
                check(sha(row.rawText) == pinned.getString("sha256"))
                assertDisplay(row)
            }
            val original = context.rows.single { it.ayah == a }
            check(original.rawText == entry.rawText && original.status == entry.status)
            check(original.context == null)
        }
    }

    private fun checkPersonalStore() {
        val root = File(targetContext.cacheDir, "phase4-personal-contract")
        root.deleteRecursively()
        val file = File(root, "personal.sqlite")
        fun expect(code: String, block: () -> Unit) {
            try { block(); error("Expected personal $code") }
            catch (error: PersonalFailure) { check(error.code == code) }
        }
        try {
            PersonalStore(file).use { store ->
                check(store.readTafsirBook() == "ibn_kathir")
                store.writeTafsirBook("al_tabari")
                check(store.readTafsirBook() == "al_tabari")
                expect("invalidData") { store.writeTafsirBook("unknown") }
                check(store.readTafsirBook() == "al_tabari")
            }
            PersonalStore(file).use { check(it.readTafsirBook() == "al_tabari"); it.writeTafsirBook("al_saadi") }
            PersonalStore(file).use { check(it.readTafsirBook() == "al_saadi") }
            // Fail an actual update of existing personal state, after DELETE
            // inside the transaction. Neither failure nor reopening may lose
            // the old author; removing the fault permits the same owner to retry.
            fun faultSql(sql: String) {
                android.database.sqlite.SQLiteDatabase.openDatabase(file.path, null, 0).use { it.execSQL(sql) }
            }
            faultSql("""CREATE TRIGGER reject_author BEFORE INSERT ON preferences
                BEGIN DELETE FROM preferences WHERE key=NEW.key;
                SELECT RAISE(ABORT, 'injected write failure'); END""")
            PersonalStore(file).use { store ->
                expect("storage") { store.writeTafsirBook("al_tabari") }
                check(store.readTafsirBook() == "al_saadi")
                PersonalStore(file).use { check(it.readTafsirBook() == "al_saadi") }
                faultSql("DROP TRIGGER reject_author")
                store.writeTafsirBook("al_tabari")
                check(store.readTafsirBook() == "al_tabari")
            }
            PersonalStore(file).use { check(it.readTafsirBook() == "al_tabari"); it.writeTafsirBook("al_saadi") }
            android.database.sqlite.SQLiteDatabase.openDatabase(file.path, null, 0).use { it.version = 2 }
            val futureBytes = file.readBytes()
            PersonalStore(file).use { store ->
                expect("unsupportedVersion") { store.readTafsirBook() }
                expect("unsupportedVersion") { store.writeTafsirBook("al_tabari") }
            }
            check(file.readBytes().contentEquals(futureBytes))
            android.database.sqlite.SQLiteDatabase.openDatabase(file.path, null, 0).use {
                check(it.version == 2)
                it.rawQuery("SELECT value FROM preferences WHERE key='tafsir_book'", null).use { row ->
                    check(row.moveToFirst() && row.getString(0) == "al_saadi")
                }
                it.version = 1
                it.execSQL("UPDATE preferences SET value='unknown' WHERE key='tafsir_book'")
            }
            PersonalStore(file).use {
                expect("invalidData") { it.readTafsirBook() }
                it.writeTafsirBook("al_tabari")
                check(it.readTafsirBook() == "al_tabari")
            }
            // Production API only: malformed existing DB + companion evidence
            // must survive both operations, repeated failure and a new owner.
            // Recovery below is explicit test-fixture restoration, never store code.
            val goodBytes = file.readBytes()
            for (damageOffset in listOf(0, 100)) {
                val damaged = File(root, "corrupt-$damageOffset.sqlite")
                val corruptBytes = goodBytes.copyOf().apply { this[damageOffset] = 0x7f }
                damaged.writeBytes(corruptBytes)
                val evidence = listOf(damaged) + listOf("-journal", "-wal", "-shm").map { suffix ->
                    File(damaged.path + suffix).apply { writeText("retained companion $suffix") }
                }
                val before = evidence.associateWith { it.readBytes() }
                fun unchanged() {
                    for ((path, bytes) in before) {
                        check(path.isFile && path.readBytes().contentEquals(bytes)) {
                            "Personal corruption recovery changed ${path.name}"
                        }
                    }
                }
                PersonalStore(damaged).use { store ->
                    repeat(2) {
                        expect("storage") { store.readTafsirBook() }
                        unchanged()
                        expect("storage") { store.writeTafsirBook("al_saadi") }
                        unchanged()
                    }
                    PersonalStore(damaged).use {
                        expect("storage") { it.readTafsirBook() }
                        expect("storage") { it.writeTafsirBook("al_saadi") }
                    }
                    unchanged()
                    damaged.writeBytes(goodBytes)
                    evidence.drop(1).forEach { check(it.delete()) }
                    check(store.readTafsirBook() == "al_tabari")
                    store.writeTafsirBook("al_saadi")
                    check(store.readTafsirBook() == "al_saadi")
                }
                PersonalStore(damaged).use { check(it.readTafsirBook() == "al_saadi") }
            }
            // Existing zero-byte / valid unversioned files are not first launch.
            for (empty in listOf(true, false)) {
                val unknown = File(root, "version-zero-$empty.sqlite")
                if (empty) unknown.writeBytes(byteArrayOf()) else {
                    android.database.sqlite.SQLiteDatabase.openOrCreateDatabase(unknown, null).use {
                        it.execSQL("CREATE TABLE retained (value TEXT)")
                        it.execSQL("INSERT INTO retained VALUES ('keep')")
                        check(it.version == 0)
                    }
                }
                val bytes = unknown.readBytes()
                PersonalStore(unknown).use { store ->
                    repeat(2) {
                        expect("unsupportedVersion") { store.readTafsirBook() }
                        expect("unsupportedVersion") { store.writeTafsirBook("al_saadi") }
                        check(unknown.readBytes().contentEquals(bytes))
                    }
                }
            }
            // Absence accompanied by recovery evidence cannot create a new DB.
            val absent = File(root, "absent.sqlite")
            val orphan = File(absent.path + "-wal").apply { writeText("recover me") }
            PersonalStore(absent).use { store ->
                repeat(2) {
                    expect("storage") { store.readTafsirBook() }
                    expect("storage") { store.writeTafsirBook("al_saadi") }
                    check(!absent.exists() && orphan.readText() == "recover me")
                }
                check(orphan.delete()) // explicit fixture cleanup allows genuine first launch
                check(store.readTafsirBook() == "ibn_kathir")
            }
            // Inaccessible existing data is storage failure, never absence.
            val unreadable = File(root, "unreadable.sqlite").apply { writeBytes(goodBytes) }
            Os.chmod(unreadable.path, 0)
            try {
                PersonalStore(unreadable).use { store ->
                    expect("storage") { store.readTafsirBook() }
                    expect("storage") { store.writeTafsirBook("al_saadi") }
                    Os.chmod(unreadable.path, 384) // 0600, restore fixture access for retry
                    check(unreadable.readBytes().contentEquals(goodBytes))
                    check(store.readTafsirBook() == "al_tabari")
                }
            } finally { Os.chmod(unreadable.path, 384) }
            val blocked = File(root, "blocked")
            blocked.writeText("not a directory")
            PersonalStore(File(blocked, "personal.sqlite")).use {
                expect("storage") { it.readTafsirBook() }
                expect("storage") { it.writeTafsirBook("al_saadi") }
                check(blocked.delete() && blocked.mkdir())
                it.writeTafsirBook("al_saadi")
                check(it.readTafsirBook() == "al_saadi")
            }
        } finally { root.deleteRecursively() }
    }

    // Real Android provider/intent boundaries, no chooser recipient or delivery.
    private fun checkImageShare() {
        val bitmap = Bitmap.createBitmap(3, 2, Bitmap.Config.ARGB_8888)
        val png = ByteArrayOutputStream().use { out ->
            check(bitmap.compress(Bitmap.CompressFormat.PNG, 100, out))
            out.toByteArray()
        }
        bitmap.recycle()
        val share = ReaderImageShare(targetContext)
        val uris = mutableListOf<Uri>()
        try {
            for ((surah, ayah) in listOf(1 to 1, 27 to 59, 114 to 6)) {
                val send = share.prepare(surah, ayah, png)
                check(send.action == Intent.ACTION_SEND && send.type == "image/png")
                check(send.`package` == null && send.component == null)
                check(send.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION != 0)
                check(send.flags and Intent.FLAG_GRANT_WRITE_URI_PERMISSION == 0)
                check(send.getStringExtra(Intent.EXTRA_TEXT) ==
                    "Verse $ayah, Surah $surah shared via https://quranly.app !")
                val uri = send.getParcelableExtra(Intent.EXTRA_STREAM, Uri::class.java)!!
                check(uri.scheme == "content" && uri.authority == "${targetContext.packageName}.reader.share_provider")
                check(send.clipData!!.getItemAt(0).uri == uri)
                check(targetContext.contentResolver.getType(uri) == "image/png")
                check(targetContext.contentResolver.openInputStream(uri)!!.use { it.readBytes() }.contentEquals(png))
                check(uri !in uris)
                uris += uri
            }
            val directory = File(targetContext.cacheDir, "reader-share")
            val before = directory.listFiles()!!.map { it.name }.toSet()
            for ((s, a, bytes) in listOf(Triple(1, 8, png), Triple(115, 1, png),
                Triple(1, 1, byteArrayOf()), Triple(1, 1, "not png".toByteArray()))) {
                var rejected = false
                try { share.prepare(s, a, bytes) } catch (error: IllegalArgumentException) { rejected = true }
                check(rejected && directory.listFiles()!!.map { it.name }.toSet() == before)
            }
            var outsideRejected = false
            try {
                androidx.core.content.FileProvider.getUriForFile(targetContext,
                    "${targetContext.packageName}.reader.share_provider", File(targetContext.cacheDir, "outside.png"))
            } catch (error: IllegalArgumentException) { outsideRejected = true }
            check(outsideRejected)
        } finally {
            // Delete only this probe's exports; never a reader-created image.
            uris.forEach { targetContext.contentResolver.delete(it, null, null) }
        }
    }

    private fun expectFailure(code: String, body: () -> Unit) {
        try { body(); error("Expected $code") } catch (error: TafsirFailure) { check(error.code == code) }
    }
    private fun hex(bytes: ByteArray) = bytes.joinToString("") { "%02x".format(it) }
    private fun sha(text: String) = hex(MessageDigest.getInstance("SHA-256").digest(text.toByteArray(Charsets.UTF_8)))
}
