import 'package:flutter/foundation.dart';
import 'content.dart';
import 'personal.dart';
import 'tafsir.dart';

/// Coordinates selected identity, content and durable author choice. Content
/// generations and preference generations are independent: a slow/failed old
/// lookup or write cannot relabel the current selection. No default until the
/// personal owner has successfully resolved first launch vs saved preference.
class TafsirSession extends ChangeNotifier {
  TafsirSession(this.key);
  AyahKey key;
  TafsirBook? book;
  TafsirEntry? entry;
  TafsirException? contentError;
  PersonalException? preferenceError;
  bool saving = false;
  bool _disposed = false;
  int _lookupGeneration = 0, _preferenceGeneration = 0;

  void _changed() {
    if (!_disposed) notifyListeners();
  }

  Future<void> initialize() async {
    final generation = ++_preferenceGeneration;
    preferenceError = null;
    _changed();
    try {
      final stored = await const PersonalStore().readTafsirBook();
      if (_disposed || generation != _preferenceGeneration) return;
      book = stored;
      await reload();
    } on PersonalException catch (error) {
      if (_disposed || generation != _preferenceGeneration) return;
      preferenceError = error;
      _changed();
    }
  }

  void choose(TafsirBook chosen) {
    book = chosen;
    reload();
    _save(chosen);
  }

  Future<void> _save(TafsirBook chosen) async {
    final generation = ++_preferenceGeneration;
    saving = true;
    preferenceError = null;
    _changed();
    try {
      await const PersonalStore().writeTafsirBook(chosen);
    } on PersonalException catch (error) {
      if (!_disposed && generation == _preferenceGeneration) {
        preferenceError = error;
      }
    } finally {
      if (!_disposed && generation == _preferenceGeneration) {
        saving = false;
        _changed();
      }
    }
  }

  Future<void> retryPreference() => book == null ? initialize() : _save(book!);

  void changeKey(AyahKey chosen) {
    key = chosen;
    reload();
  }

  Future<void> reload() async {
    final generation = ++_lookupGeneration;
    final requestedBook = book;
    final requestedKey = key;
    entry = null;
    contentError = null;
    _changed();
    if (requestedBook == null) return;
    try {
      final result = await const TafsirContent().lookup(
        requestedKey,
        book: requestedBook,
      );
      if (!_disposed && generation == _lookupGeneration) entry = result;
    } on TafsirException catch (error) {
      if (!_disposed && generation == _lookupGeneration) contentError = error;
    } finally {
      if (!_disposed && generation == _lookupGeneration) _changed();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
