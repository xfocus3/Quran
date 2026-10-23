import 'package:compatibility/content.dart';
import 'package:compatibility/reader.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test(
    'jump/adjacent selection copies the same canonical ayah through Clipboard',
    () async {
      final catalog = await QuranCatalog.load(rootBundle);
      final reader = ReaderController(catalog);
      addTearDown(reader.dispose);
      String? copied;
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(SystemChannels.platform, (call) async {
            if (call.method == 'Clipboard.setData') {
              copied = call.arguments['text'] as String;
            }
            return null;
          });
      addTearDown(
        () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
            .setMockMethodCallHandler(SystemChannels.platform, null),
      );
      expect(await reader.copySelected(), isNull);
      for (final key in [
        const AyahKey(1, 7),
        const AyahKey(2, 281),
        const AyahKey(2, 282),
        const AyahKey(114, 6),
      ]) {
        reader.open(key);
        expect(reader.selected, isNull);
        expect(reader.selectCurrent().key, key);
        expect(await reader.copySelected(), key);
        expect(copied, '${catalog.ayah(key).text}\n${key.reference}');
        expect(copied!.runes.any((r) => r >= 0xe000 && r <= 0xf8ff), false);
      }
      reader.open(const AyahKey(1, 7));
      reader.selectCurrent();
      reader.goNext();
      expect(reader.current.key, const AyahKey(2, 1));
      expect(reader.selected, isNull);
      expect(await reader.copySelected(), isNull);
      reader.selectCurrent();
      reader.goPrevious();
      expect(reader.selectCurrent().key, const AyahKey(1, 7));
      expect(await reader.copySelected(), const AyahKey(1, 7));
      expect(copied, '${catalog.ayah(const AyahKey(1, 7)).text}\n1:7');
      expect(
        () => reader.open(const AyahKey(1, 8)),
        throwsA(isA<ReferenceException>()),
      );
      expect(reader.current.key, const AyahKey(1, 7));
      reader.open(const AyahKey(1, 1));
      reader.goPrevious();
      expect(reader.current.key, const AyahKey(1, 1));
      reader.open(const AyahKey(114, 6));
      reader.goNext();
      expect(reader.current.key, const AyahKey(114, 6));
    },
  );
}
