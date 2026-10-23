import 'package:flutter/services.dart';
import 'package:flutter/foundation.dart';
import 'package:crypto/crypto.dart';
import 'dart:convert';
import 'content.dart';

enum TafsirFailure {
  invalidBook,
  invalidReference,
  missingAsset,
  corruptPack,
  invalidSchema,
  missingEntry,
  invalidContent,
  storage,
  unavailable,
}

class TafsirException implements Exception {
  const TafsirException(this.reason);
  final TafsirFailure reason;
}

enum TafsirBook {
  ibnKathir('ibn_kathir', 'تفسير القرآن العظيم', 'ابن كثير'),
  alTabari('al_tabari', 'جامع البيان عن تأويل آي القرآن', 'الطبري'),
  alSaadi('al_saadi', 'تيسير الكريم الرحمن في تفسير كلام المنان', 'السعدي');

  const TafsirBook(this.id, this.title, this.author);
  final String id;
  final String title;
  final String author;
  static TafsirBook? fromId(Object? id) {
    for (final book in values) {
      if (book.id == id) return book;
    }
    return null;
  }
}

enum TafsirStatus { sourceText, emptyMarkup }

class TafsirContextRange {
  const TafsirContextRange({
    required this.fromAyah,
    required this.toAyah,
    required this.headingAyah,
    required this.headingText,
    required this.basis,
    required this.rows,
  });
  final int fromAyah, toAyah, headingAyah;
  final String headingText, basis;
  final List<TafsirEntry> rows;
}

class TafsirEntry {
  const TafsirEntry({
    required this.key,
    required this.book,
    required this.status,
    required this.rawText,
    required this.displayText,
    this.context,
  });
  final AyahKey key;
  final TafsirBook book;
  final TafsirStatus status;
  final TafsirContextRange? context;

  /// Exact source, including CRLF, break-inside-word and unmatched footnotes.
  final String rawText;

  /// Inert native source-format Unicode, never written back into the corpus.
  final String displayText;
}

/// Native content owner supplies grouping once. Flutter validates transport
/// identity; it never infers ranges, redirects rows or parses source markup.
class TafsirContent {
  const TafsirContent();
  static const channel = MethodChannel('quranly/tafsir');

  Future<TafsirEntry> lookup(AyahKey key, {required TafsirBook book}) async {
    try {
      final response = await channel.invokeMethod<Object?>('lookup', {
        'book': book.id,
        'surah': key.surah,
        'ayah': key.ayah,
      });
      Never invalid() =>
          throw const TafsirException(TafsirFailure.invalidContent);
      Map<Object?, Object?> transportMap(Object? value) {
        if (value is! Map || value.keys.any((key) => key is! String)) invalid();
        return value;
      }

      TafsirEntry parse(Map<Object?, Object?> value, AyahKey expected) {
        if (value['book'] != book.id ||
            value['surah'] != expected.surah ||
            value['ayah'] != expected.ayah ||
            value['rawText'] is! String ||
            (value['rawText'] as String).isEmpty ||
            value['displayText'] is! String) {
          invalid();
        }
        final status = switch (value['status']) {
          'source_text' => TafsirStatus.sourceText,
          'empty_markup' => TafsirStatus.emptyMarkup,
          _ => invalid(),
        };
        if (status == TafsirStatus.sourceText &&
            (value['displayText'] as String).trim().isEmpty) {
          invalid();
        }
        return TafsirEntry(
          key: expected,
          book: book,
          status: status,
          rawText: value['rawText'] as String,
          displayText: value['displayText'] as String,
        );
      }

      final row = transportMap(response);
      final selected = parse(row, key);
      TafsirContextRange? context;
      final contextValue = row['context'];
      if (contextValue != null) {
        final group = transportMap(contextValue);
        if (group['fromAyah'] is! int ||
            group['toAyah'] is! int ||
            group['headingAyah'] is! int ||
            group['headingText'] is! String ||
            group['basis'] is! String ||
            group['rows'] is! List) {
          invalid();
        }
        final from = group['fromAyah'] as int;
        final to = group['toAyah'] as int;
        final heading = group['headingAyah'] as int;
        final rows = group['rows'] as List;
        if (from < 1 ||
            from > key.ayah ||
            to < key.ayah ||
            to - from > 4 ||
            heading < from ||
            heading > to ||
            rows.length != to - from + 1) {
          invalid();
        }
        final entries = [
          for (var i = 0; i < rows.length; i++)
            parse(transportMap(rows[i]), AyahKey(key.surah, from + i)),
        ];
        final original = entries[key.ayah - from];
        if (original.rawText != selected.rawText ||
            original.status != selected.status ||
            original.displayText != selected.displayText) {
          invalid();
        }
        context = TafsirContextRange(
          fromAyah: from,
          toAyah: to,
          headingAyah: heading,
          headingText: group['headingText'] as String,
          basis: group['basis'] as String,
          rows: List.unmodifiable(entries),
        );
      }
      if (selected.status == TafsirStatus.emptyMarkup && context == null) {
        invalid();
      }
      return TafsirEntry(
        key: selected.key,
        book: selected.book,
        status: selected.status,
        rawText: selected.rawText,
        displayText: selected.displayText,
        context: context,
      );
    } on MissingPluginException {
      throw const TafsirException(TafsirFailure.unavailable);
    } on PlatformException catch (error) {
      throw TafsirException(
        TafsirFailure.values.firstWhere(
          (reason) => reason.name == error.code,
          orElse: () => TafsirFailure.unavailable,
        ),
      );
    }
  }
}

class TafsirNotice {
  const TafsirNotice(this.title, this.text);
  final String title;
  final String text;
}

/// Supplied attribution and conflicting license/source notices, byte checked
/// against the retained manifest, available without opening SQLite or network.
Future<List<TafsirNotice>> loadTafsirNotices(AssetBundle bundle) async {
  const files = {
    'ATTRIBUTION.txt': (
      'نسبة المصدر والتغييرات',
      'ccd380c03a7166efad3b10c27bfe181d3e6fc6e8b214f14c1824e5951ee9eeb9',
    ),
    'LICENSE-DATA.txt': (
      'الترخيص المعلن',
      'b286b84fe98f8dc422bbaabd0d10e8b03e4152bd63720b3f84728affc6efd9cb',
    ),
    'SOURCE-DATA-NOTICE.txt': (
      'إشعار المصدر',
      '9545c1bbe41e0374c91645a672847736e066b224b2ff64b43b6d7864f831072e',
    ),
    'READ-FIRST.txt': (
      'ملاحظات الحزمة عند إعدادها',
      'e0b64da82428bf6c98b876c5e1fe66746017459aeed02e9f60ec24f9fdd4f0a7',
    ),
  };
  final notices = <TafsirNotice>[];
  for (final file in files.entries) {
    try {
      final bytes = await bundle.load('.local/handoff/tafsir/${file.key}');
      final data = bytes.buffer.asUint8List(
        bytes.offsetInBytes,
        bytes.lengthInBytes,
      );
      if (sha256.convert(data).toString() != file.value.$2) {
        throw const TafsirException(TafsirFailure.invalidContent);
      }
      notices.add(TafsirNotice(file.value.$1, utf8.decode(data)));
    } on FlutterError {
      throw const TafsirException(TafsirFailure.missingAsset);
    } on FormatException {
      throw const TafsirException(TafsirFailure.invalidContent);
    }
  }
  return List.unmodifiable(notices);
}
