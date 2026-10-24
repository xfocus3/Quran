import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'content.dart';
import 'reader.dart';
import 'reader_metadata.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'tafsir_view.dart';
import 'passage_picker.dart';
import 'reader_share.dart';
import 'package:flutter/rendering.dart';
import 'dart:ui' as ui;

part 'reader_view.dart';

void main() => runApp(const MainApp());

// Sampled retained light reader; background itself is the original APK asset.
const readerPurple = Color(0xFF50308C);
const readerCard = Color(0xFFFAF7FF);
// UI ink is distinct from the observed plain Madina Quran foreground.
const readerInk = Color(0xFF0D0D0D);
const readerPlainQuranInk = Color(0xFF181818);
const readerLightArrow = readerCard;

class MainApp extends StatefulWidget {
  const MainApp({super.key, this.bundle, this.metadata});
  final AssetBundle? bundle;
  final ReaderMetadata? metadata;
  @override
  State<MainApp> createState() => _MainAppState();
}

class _MainAppState extends State<MainApp> {
  late Future<(QuranCatalog, ReaderMetadata)> _catalog;
  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    _catalog = _load();
    // A retry may fail before the next frame attaches FutureBuilder. Keep the
    // error handled during that interval; FutureBuilder still receives it.
    _catalog.ignore();
  }

  Future<(QuranCatalog, ReaderMetadata)> _load() async => (
    await QuranCatalog.load(widget.bundle ?? rootBundle),
    widget.metadata ?? await ReaderMetadata.load(rootBundle),
  );

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'القرآن الكريم',
    theme: ThemeData(
      scaffoldBackgroundColor: readerPurple,
      fontFamily: 'inter',
      bottomSheetTheme: const BottomSheetThemeData(
        dragHandleColor: Color(0xFFE2DFE9),
        dragHandleSize: Size(36, 4),
      ),
      colorScheme: const ColorScheme.light(
        primary: readerPurple,
        onPrimary: Colors.white,
        surface: readerCard,
        onSurface: readerInk,
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(minimumSize: const Size(48, 48)),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(minimumSize: const Size(48, 48)),
      ),
    ),
    builder: (context, child) =>
        Directionality(textDirection: TextDirection.rtl, child: child!),
    home: FutureBuilder<(QuranCatalog, ReaderMetadata)>(
      future: _catalog,
      builder: (context, snapshot) {
        if (snapshot.hasError) {
          final error = snapshot.error;
          final missing =
              error is ContentException &&
              error.reason == ContentFailure.missingAsset;
          return Scaffold(
            body: SafeArea(
              child: Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.all(24),
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            missing
                                ? 'ملف القرآن المحلي غير متاح.'
                                : 'تعذّر فتح القرآن: المحتوى المحلي غير صالح.',
                          ),
                          TextButton(
                            onPressed: () => setState(_reload),
                            child: const Text('إعادة المحاولة'),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          );
        }
        final catalog = snapshot.data;
        if (catalog == null) {
          return const Scaffold(
            body: Center(
              child: CircularProgressIndicator(
                color: Colors.white,
                semanticsLabel: 'جارٍ فتح القرآن المحلي',
              ),
            ),
          );
        }
        return ReaderView(catalog: catalog.$1, metadata: catalog.$2);
      },
    ),
  );
}

class _AyahActions extends StatefulWidget {
  const _AyahActions({required this.reader, required this.ayah});
  final ReaderController reader;
  final QuranAyah ayah;
  @override
  State<_AyahActions> createState() => _AyahActionsState();
}

class _AyahActionsState extends State<_AyahActions> {
  bool _copying = false;
  bool _failed = false;
  Future<void> _copy() async {
    setState(() {
      _copying = true;
      _failed = false;
    });
    try {
      final key = await widget.reader.copySelected();
      if (!mounted) return;
      if (key != null) {
        Navigator.pop(context);
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('تم نسخ الآية مع المرجع')));
      }
    } on PlatformException {
      if (mounted) setState(() => _failed = true);
    } on MissingPluginException {
      if (mounted) setState(() => _failed = true);
    } finally {
      if (mounted) setState(() => _copying = false);
    }
  }

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Semantics(
            header: true,
            child: const Text('إجراءات الآية', style: TextStyle(fontSize: 22)),
          ),
          Text(
            widget.ayah.key.reference,
            textDirection: TextDirection.ltr,
            textAlign: TextAlign.right,
          ),
          const SizedBox(height: 16),
          FilledButton.icon(
            onPressed: _copying ? null : _copy,
            icon: const Icon(Icons.copy),
            label: const Text('نسخ الآية مع المرجع'),
          ),
          OutlinedButton.icon(
            onPressed: _copying ? null : () => Navigator.pop(context, true),
            icon: const Icon(Icons.menu_book),
            label: const Text('فتح التفسير'),
          ),
          if (_failed)
            Semantics(
              liveRegion: true,
              child: const Text('تعذّر النسخ إلى الحافظة. أعد المحاولة.'),
            ),
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('إغلاق'),
          ),
        ],
      ),
    ),
  );
}
