import 'package:flutter/services.dart';
import 'content.dart';

/// Image snapshot and key travel together. Launching a chooser does not mean a
/// recipient was selected or that an image was sent. Copying uses ReaderController.
class AyahImageShare {
  static const channel = MethodChannel('quranly/share');
  static Future<void> share(QuranAyah ayah, Uint8List png) async {
    if (png.isEmpty) throw ArgumentError.value(png, 'png', 'Empty image');
    await channel.invokeMethod<void>('shareImage', {
      'surah': ayah.key.surah,
      'ayah': ayah.key.ayah,
      'png': png,
    });
  }
}
