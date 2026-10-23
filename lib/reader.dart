import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'content.dart';

/// In-memory reader state only; durable resume/history belongs to phase 7.
class ReaderController extends ChangeNotifier {
  ReaderController(this.catalog) : _current = catalog.ayah(const AyahKey(1, 1));
  final QuranCatalog catalog;
  QuranAyah _current;
  QuranAyah? _selected;
  QuranAyah get current => _current;
  QuranAyah? get selected => _selected;
  AyahKey? get previous => catalog.previous(_current.key);
  AyahKey? get next => catalog.next(_current.key);

  void open(AyahKey key) {
    final ayah = catalog.ayah(key); // Validate before changing any state.
    _current = ayah;
    _selected = null;
    notifyListeners();
  }

  void goPrevious() {
    final key = previous;
    if (key != null) open(key);
  }

  void goNext() {
    final key = next;
    if (key != null) open(key);
  }

  QuranAyah selectCurrent() {
    _selected = _current;
    return _current;
  }

  void clearSelection() => _selected = null;

  /// Snapshot selection before awaiting the system; a jump cannot change it.
  /// OS errors propagate so the UI must not report a failed copy as success.
  Future<AyahKey?> copySelected() async {
    final ayah = _selected;
    if (ayah == null) return null;
    await Clipboard.setData(ClipboardData(text: ayah.copyText));
    return ayah.key;
  }
}
