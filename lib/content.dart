import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

/// Identity never depends on labels, rendered text, or page-font glyphs.
class AyahKey {
  const AyahKey(this.surah, this.ayah);
  final int surah;
  final int ayah;
  String get reference => '$surah:$ayah';
  @override
  bool operator ==(Object other) =>
      other is AyahKey && surah == other.surah && ayah == other.ayah;
  @override
  int get hashCode => Object.hash(surah, ayah);
}

class QuranAyah {
  const QuranAyah(this.key, this.text);
  final AyahKey key;

  /// Exact retained text_madina. Never normalize even diacritics/spacing.
  final String text;
  String get copyText => '$text\n${key.reference}';
}

class Surah {
  const Surah(this.number, this.name, this.ayahCount);
  final int number;
  final String name;
  final int ayahCount;
}

enum ContentFailure { missingAsset, invalidContent }

class ContentException implements Exception {
  const ContentException(this.reason);
  final ContentFailure reason;
}

enum ReferenceFailure { wholeNumbersRequired, outOfRange }

class ReferenceException implements Exception {
  const ReferenceException(this.reason);
  final ReferenceFailure reason;
}

/// Sole owner of immutable catalog validation, lookup and adjacent order.
class QuranCatalog {
  QuranCatalog._(this.surahs, this._ayahs, this._offsets);
  final List<Surah> surahs;
  final List<QuranAyah> _ayahs;
  final List<int> _offsets;
  static const asset = '.local/handoff/app/quran.json';

  // Schema-2 artifact independently checked against all retained REA text/keys
  // and metadata. Source hash fields alone cannot authenticate the contents.
  // See docs/phase-2/source-provenance.md before changing this identity.
  static const _payloadSha256 =
      'b98ccebd59936fe204274abb36538802b9b3abfe55013ac6af1879350efe3a99';

  static Future<QuranCatalog> load(AssetBundle bundle) async {
    try {
      final encoded = await bundle.loadString(asset, cache: false);
      final catalog = _decode(jsonDecode(encoded));
      if (sha256.convert(utf8.encode(encoded)).toString() != _payloadSha256) {
        throw const FormatException('Quran artifact identity mismatch');
      }
      return catalog;
    } on FlutterError {
      throw const ContentException(ContentFailure.missingAsset);
    } on FormatException {
      throw const ContentException(ContentFailure.invalidContent);
    }
  }

  static QuranCatalog _decode(dynamic source) {
    void require(bool condition) {
      if (!condition) throw const FormatException('Invalid Quran catalog');
    }

    require(source is Map<String, dynamic>);
    require(
      source['schema_version'] == 2 &&
          source['unicode_column'] == 'text_madina' &&
          source['unicode_font'] == 'madina2' &&
          source['source_database_sha256'] ==
              '5f1e9cc30779a2a4b749de2f8bd4548b4fd7ca09a23457a44e6fea878bbc5dec' &&
          source['source_metadata_sha256'] ==
              '1c678bd3be55900c29056aef5e6a0f1a2909590a3eabc38aa28aac195b011031',
    );
    require(source['surahs'] is List && source['ayahs'] is List);
    final rows = source['ayahs'] as List;
    final metadata = source['surahs'] as List;
    require(metadata.length == 114 && rows.length == 6236);
    final surahs = <Surah>[];
    final ayahs = <QuranAyah>[];
    final offsets = <int>[];
    var index = 0;
    for (var s = 1; s <= 114; s++) {
      final m = metadata[s - 1];
      require(m is Map<String, dynamic>);
      require(
        m['surah'] is int &&
            m['surah'] == s &&
            m['name'] is String &&
            (m['name'] as String).trim().isNotEmpty &&
            m['ayah_count'] is int,
      );
      final count = m['ayah_count'] as int;
      require(count > 0 && index + count <= rows.length);
      offsets.add(index);
      surahs.add(Surah(s, m['name'] as String, count));
      for (var a = 1; a <= count; a++) {
        final row = rows[index++];
        require(row is Map<String, dynamic>);
        require(
          row['surah'] is int &&
              row['surah'] == s &&
              row['ayah'] is int &&
              row['ayah'] == a &&
              row['unicode'] is String,
        );
        final text = row['unicode'] as String;
        require(
          text.trim().isNotEmpty &&
              !text.runes.any((r) => r >= 0xe000 && r <= 0xf8ff),
        );
        ayahs.add(QuranAyah(AyahKey(s, a), text));
      }
    }
    require(index == 6236);
    return QuranCatalog._(
      List.unmodifiable(surahs),
      List.unmodifiable(ayahs),
      List.unmodifiable(offsets),
    );
  }

  int _index(AyahKey key) {
    if (key.surah < 1 ||
        key.surah > surahs.length ||
        key.ayah < 1 ||
        key.ayah > surahs[key.surah - 1].ayahCount) {
      throw const ReferenceException(ReferenceFailure.outOfRange);
    }
    return _offsets[key.surah - 1] + key.ayah - 1;
  }

  QuranAyah ayah(AyahKey key) => _ayahs[_index(key)];
  Surah surah(AyahKey key) {
    _index(key);
    return surahs[key.surah - 1];
  }

  AyahKey? previous(AyahKey key) {
    final index = _index(key);
    return index == 0 ? null : _ayahs[index - 1].key;
  }

  AyahKey? next(AyahKey key) {
    final index = _index(key);
    return index == _ayahs.length - 1 ? null : _ayahs[index + 1].key;
  }

  /// Accept ASCII, Arabic-Indic and Persian digits from Android keyboards.
  /// Parsing applies only to user input, never to Quran source strings.
  AyahKey parseReference(String surah, String ayah) {
    int number(String input) {
      final digits = String.fromCharCodes(
        input.trim().runes.map((r) {
          if (r >= 0x660 && r <= 0x669) return r - 0x660 + 48;
          if (r >= 0x6f0 && r <= 0x6f9) return r - 0x6f0 + 48;
          return r;
        }),
      );
      final parsed = RegExp(r'^[0-9]+$').hasMatch(digits)
          ? int.tryParse(digits)
          : null;
      if (parsed == null) {
        throw const ReferenceException(ReferenceFailure.wholeNumbersRequired);
      }
      return parsed;
    }

    final key = AyahKey(number(surah), number(ayah));
    _index(key);
    return key;
  }
}
