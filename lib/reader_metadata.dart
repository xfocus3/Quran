import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'content.dart';

/// Immutable original chapter labels and juz membership. Independent of personal
/// progress, completion/reward policy, mushaf pages and rendered glyph strings.
class ReaderMetadata {
  ReaderMetadata._(this._surahs, this._juzStarts);
  final List<Map<String, dynamic>> _surahs;
  final List<int> _juzStarts;
  static const asset = '.local/reader/metadata.json';
  static const _sha256 =
      'b382bd791a7c4ce4c742856d5b6017f80136a9289716e0e4d90822ae01bc6fc7';

  static Future<ReaderMetadata> load(AssetBundle bundle) async {
    try {
      final text = await bundle.loadString(asset, cache: false);
      if (sha256.convert(utf8.encode(text)).toString() != _sha256) {
        throw const FormatException('Reader metadata identity mismatch');
      }
      final value = jsonDecode(text) as Map<String, dynamic>;
      final surahs = (value['surahs'] as List).cast<Map<String, dynamic>>();
      final juz = (value['juz_starts'] as List).cast<Map<String, dynamic>>();
      return ReaderMetadata._(
        List.unmodifiable(surahs),
        List.unmodifiable(juz.map((j) => j['offset'] as int)),
      );
    } on FormatException {
      throw const ContentException(ContentFailure.invalidContent);
    } on FlutterError {
      throw const ContentException(ContentFailure.missingAsset);
    }
  }

  String latinName(AyahKey key) => _surahs[key.surah - 1]['latin'] as String;
  String englishName(AyahKey key) =>
      _surahs[key.surah - 1]['english'] as String;

  /// Inclusive remaining count matches the retained 27:59/juz20/168 state.
  /// This is passage context only; it never records a reading/completion event.
  ({int juz, int remaining}) context(QuranCatalog catalog, AyahKey key) {
    catalog.ayah(key); // Validate before using labels or offsets.
    final offset =
        catalog.surahs
            .take(key.surah - 1)
            .fold(0, (sum, surah) => sum + surah.ayahCount) +
        key.ayah -
        1;
    final index = _juzStarts.lastIndexWhere((start) => start <= offset);
    final end = index == 29 ? 6236 : _juzStarts[index + 1];
    return (juz: index + 1, remaining: end - offset);
  }
}
