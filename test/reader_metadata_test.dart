import 'dart:convert';
import 'dart:io';
import 'package:compatibility/content.dart';
import 'package:compatibility/reader_metadata.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'content_test.dart' show StringBundle;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test(
    'every reader label/juz/remaining count matches retained SQLite identities',
    () async {
      final catalog = await QuranCatalog.load(rootBundle);
      final metadata = await ReaderMetadata.load(rootBundle);
      // Independent SQL oracle uses the exact prepared original. Sparse juz_no
      // must never produce a fabricated juz0 or wrong count (notably27:59).
      final result = Process.runSync('python3', [
        '-c',
        '''
import sqlite3,json
c=sqlite3.connect('file:.local/handoff/source/offlinedb.db?mode=ro&immutable=1',uri=True)
print(json.dumps(c.execute("""SELECT surah,verse,surah_name_in_latin,
surah_name_in_english,cast(juz as integer),count(*) OVER (
PARTITION BY juz ORDER BY ID ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)
FROM Quran ORDER BY ID""").fetchall()))
''',
      ]);
      expect(result.exitCode, 0, reason: '${result.stderr}');
      final rows = jsonDecode(result.stdout as String) as List;
      expect(rows, hasLength(6236));
      for (final row in rows) {
        final key = AyahKey(row[0] as int, row[1] as int);
        expect(metadata.latinName(key), row[2], reason: key.reference);
        expect(metadata.englishName(key), row[3], reason: key.reference);
        final context = metadata.context(catalog, key);
        expect(context.juz, row[4], reason: key.reference);
        expect(context.remaining, row[5], reason: key.reference);
      }
      expect(metadata.context(catalog, const AyahKey(27, 59)), (
        juz: 20,
        remaining: 168,
      ));
      expect(metadata.context(catalog, const AyahKey(114, 6)), (
        juz: 30,
        remaining: 1,
      ));
      expect(
        () => metadata.context(catalog, const AyahKey(27, 94)),
        throwsA(isA<ReferenceException>()),
      );
    },
  );

  test(
    'structurally valid substituted presentation metadata is rejected',
    () async {
      final source = await rootBundle.loadString(ReaderMetadata.asset);
      final changed = source.replaceFirst('An-Naml', 'Al-Fatiha');
      expect(changed, isNot(source));
      await expectLater(
        ReaderMetadata.load(StringBundle(changed)),
        throwsA(
          isA<ContentException>().having(
            (e) => e.reason,
            'reason',
            ContentFailure.invalidContent,
          ),
        ),
      );
    },
  );
}
