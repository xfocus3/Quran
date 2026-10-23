import 'dart:convert';
import 'dart:io';
import 'package:compatibility/content.dart';
import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'catalog reaches all independently retained keys and exact Unicode',
    () async {
      final catalog = await QuranCatalog.load(rootBundle);
      final ids = retainedRows('rea-quran-identifiers.json');
      final texts = {
        for (final r in retainedRows('rea-arabic-madina-all.json'))
          r['ID']: r['text_madina'],
      };
      final metadata = retainedRows('rea-surah-all.json');
      expect(catalog.surahs.length, 114);
      expect(ids.length, 6236);
      var index = 0;
      for (final surah in catalog.surahs) {
        final source = metadata.singleWhere(
          (m) => int.parse(m['id']!) == surah.number,
        );
        expect(surah.name, source['arabic']);
        expect(surah.ayahCount, int.parse(source['ayah']!));
        for (var a = 1; a <= surah.ayahCount; a++) {
          final id = ids[index++];
          final key = AyahKey(int.parse(id['surah']!), int.parse(id['verse']!));
          final ayah = catalog.ayah(AyahKey(surah.number, a));
          expect(ayah.key, key);
          expect(ayah.text, texts[id['ID']]);
        }
      }
      expect(index, 6236);
      expect(() => catalog.surahs.clear(), throwsUnsupportedError);
    },
  );

  test(
    'adjacent navigation covers every surah boundary without wrapping',
    () async {
      final catalog = await QuranCatalog.load(rootBundle);
      expect(catalog.previous(const AyahKey(1, 1)), isNull);
      expect(catalog.next(const AyahKey(114, 6)), isNull);
      for (final s in catalog.surahs) {
        for (var a = 1; a < s.ayahCount; a++) {
          final key = AyahKey(s.number, a);
          final next = catalog.next(key)!;
          expect(next, AyahKey(s.number, a + 1));
          expect(catalog.previous(next), key);
        }
        if (s.number < 114) {
          final last = AyahKey(s.number, s.ayahCount);
          final first = AyahKey(s.number + 1, 1);
          expect(catalog.next(last), first);
          expect(catalog.previous(first), last);
        }
      }
    },
  );
  test(
    'typed references validate whole numbers, ranges and Arabic keyboards',
    () async {
      final catalog = await QuranCatalog.load(rootBundle);
      for (final pair in [
        ['0', '1'],
        ['115', '1'],
        ['1', '0'],
        ['1', '8'],
        ['114', '7'],
        ['2', '287'],
        ['-1', '1'],
        ['1', '-1'],
        ['1.0', '1'],
        ['1', '1.5'],
        ['', '1'],
        ['a', '1'],
      ]) {
        expect(
          () => catalog.parseReference(pair[0], pair[1]),
          throwsA(isA<ReferenceException>()),
        );
      }
      for (final key in [
        const AyahKey(0, 1),
        const AyahKey(1, 0),
        const AyahKey(-1, 1),
        const AyahKey(114, 7),
      ]) {
        expect(() => catalog.ayah(key), throwsA(isA<ReferenceException>()));
        expect(() => catalog.next(key), throwsA(isA<ReferenceException>()));
        expect(() => catalog.previous(key), throwsA(isA<ReferenceException>()));
      }
      expect(catalog.parseReference(' ٢ ', '٢٨١'), const AyahKey(2, 281));
      expect(catalog.parseReference('۱۱۴', '۶'), const AyahKey(114, 6));
    },
  );
  test(
    'well-formed content substitutions cannot retain the source identity',
    () async {
      final encoded = File('.local/handoff/app/quran.json').readAsStringSync();
      final original = await QuranCatalog.load(rootBundle);
      final first = original.ayah(const AyahKey(1, 1)).text;
      final second = original.ayah(const AyahKey(1, 2)).text;
      for (final altered in [
        encoded.replaceFirst(first, second),
        encoded.replaceFirst(first, first.replaceFirst('ِ', '')),
        encoded.replaceFirst('سورة الفاتحة', 'سورة الناس'),
      ]) {
        expect(altered, isNot(encoded));
        await expectLater(
          QuranCatalog.load(StringBundle(altered)),
          throwsA(
            isA<ContentException>().having(
              (e) => e.reason,
              'reason',
              ContentFailure.invalidContent,
            ),
          ),
        );
      }
      // A rejected candidate cannot change an already loaded catalog.
      expect(original.ayah(const AyahKey(1, 1)).text, first);
      expect(original.surahs.first.name, 'سورة الفاتحة');
    },
  );
  test(
    'malformed catalog fails through the loading boundary with typed reasons',
    () async {
      final encoded = File('.local/handoff/app/quran.json').readAsStringSync();
      for (final change in <void Function(dynamic)>[
        (j) => j['schema_version'] = 1,
        (j) => j['ayahs'].removeLast(),
        (j) => j['surahs'][1]['ayah_count'] = 285,
        (j) => j['surahs'][1]['name'] = '',
        (j) => j['ayahs'][7]['ayah'] = 2,
        (j) => j['ayahs'][0]['surah'] = 1.0,
        (j) => j['ayahs'][6235]['unicode'] = '',
        (j) => j['ayahs'][0]['unicode'] = '\ue001',
      ]) {
        final j = jsonDecode(encoded);
        change(j);
        await expectLater(
          QuranCatalog.load(StringBundle(jsonEncode(j))),
          throwsA(
            isA<ContentException>().having(
              (e) => e.reason,
              'reason',
              ContentFailure.invalidContent,
            ),
          ),
        );
      }
      for (final text in ['{', 'null', '[]']) {
        await expectLater(
          QuranCatalog.load(StringBundle(text)),
          throwsA(
            isA<ContentException>().having(
              (e) => e.reason,
              'reason',
              ContentFailure.invalidContent,
            ),
          ),
        );
      }
      await expectLater(
        QuranCatalog.load(StringBundle(null)),
        throwsA(
          isA<ContentException>().having(
            (e) => e.reason,
            'reason',
            ContentFailure.missingAsset,
          ),
        ),
      );
      await expectLater(
        QuranCatalog.load(_InvalidEncodingBundle()),
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

List<Map<String, String>> retainedRows(String name) {
  final j = jsonDecode(
    File('.local/handoff/inventory/content-followup/$name').readAsStringSync(),
  );
  final r = j['normalized_result']['rows'];
  expect(r['truncated'], false);
  return [
    for (final row in r['values'])
      {
        for (var i = 0; i < r['columns'].length; i++)
          r['columns'][i] as String: row[i]['value'] as String,
      },
  ];
}

// Only the system asset boundary is substituted; the catalog remains real.
class StringBundle extends CachingAssetBundle {
  StringBundle(this.text);
  final String? text;
  @override
  Future<ByteData> load(String key) async =>
      throw FlutterError('Missing asset');
  @override
  Future<String> loadString(String key, {bool cache = true}) async {
    if (text == null) throw FlutterError('Missing asset');
    return text!;
  }
}

class _InvalidEncodingBundle extends CachingAssetBundle {
  @override
  Future<ByteData> load(String key) async => ByteData(1)..setUint8(0, 0xff);
}
