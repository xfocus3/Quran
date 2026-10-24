import 'dart:convert';
import 'dart:io';
import 'package:compatibility/content.dart';
import 'package:compatibility/main.dart';
import 'package:compatibility/reader_metadata.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'content_test.dart' show StringBundle;

late String _bundledQuran;
late ReaderMetadata _metadata;

Future<void> openReader(WidgetTester tester, {AssetBundle? bundle}) async {
  await tester.pumpWidget(
    MainApp(bundle: bundle ?? _WidgetBundle(), metadata: _metadata),
  );
  await tester.pumpAndSettle();
}

Future<void> tapVisible(WidgetTester tester, Finder finder) async {
  if (finder.evaluate().isEmpty) {
    await tester.scrollUntilVisible(
      finder,
      180,
      scrollable: find.byType(Scrollable).last,
    );
  }
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
  final screen = Offset.zero & tester.getSize(find.byType(Scaffold).first);
  final visible = tester.getRect(finder).intersect(screen);
  await tester.tapAt(visible.center);
  await tester.pumpAndSettle();
}

// A constrained sheet can scroll its header as well as its list. Drag the
// visible part, as a user does, rather than the off-screen center of a long
// nested scrollable in a large-text landscape viewport.
Future<void> revealChapter(WidgetTester tester, Finder finder) async {
  for (var i = 0; i < 114 && finder.evaluate().isEmpty; i++) {
    final viewport = Offset.zero & tester.getSize(find.byType(Scaffold).first);
    final list = tester
        .getRect(find.byType(Scrollable).last)
        .intersect(viewport);
    await tester.dragFrom(list.center, const Offset(0, -600));
    await tester.pumpAndSettle();
  }
  await tester.ensureVisible(finder);
  await tester.pumpAndSettle();
}

Future<void> jump(WidgetTester tester, String surah, String ayah) async {
  await readerEntry(tester);
  await tapVisible(
    tester,
    find.byWidgetPredicate(
      (w) => w is Semantics && w.properties.label == 'السور',
    ),
  );
  await tester.enterText(find.byType(TextField), surah);
  await tester.pumpAndSettle();
  String digits(String value) => String.fromCharCodes(
    value.runes.map((r) => r >= 0x660 && r <= 0x669 ? r - 0x660 + 0x30 : r),
  );
  await tapVisible(
    tester,
    find.byWidgetPredicate(
      (w) =>
          w is Semantics &&
          (w.properties.label?.endsWith('السورة ${digits(surah)}') ?? false),
    ),
  );
  await tapVisible(tester, find.text('Start from Verse'));
  await tester.enterText(find.byType(TextField), ayah);
  await tester.pumpAndSettle();
  await tapVisible(
    tester,
    find.byWidgetPredicate(
      (w) => w is Semantics && w.properties.label == 'Verse ${digits(ayah)}',
    ),
  );
  await tapVisible(tester, find.text('Start Reading Quran'));
}

Finder readerKey(String key) => find.byWidgetPredicate(
  (widget) =>
      widget is Semantics &&
      (widget.properties.label?.startsWith('الآية $key ') ?? false),
);

Future<void> readerEntry(WidgetTester tester) async {
  if (find.text('Reading').evaluate().isEmpty) {
    await tapVisible(
      tester,
      find.bySemanticsLabel('العودة إلى اختيار القراءة'),
    );
  }
}

void main() {
  setUpAll(() async {
    TestWidgetsFlutterBinding.ensureInitialized();
    _metadata = await ReaderMetadata.load(rootBundle);
    _bundledQuran = await rootBundle.loadString(
      QuranCatalog.asset,
      cache: false,
    );
    await (FontLoader('quranlyReaderIcons')..addFont(
          rootBundle.load('.local/reader/MaterialIcons-Regular.otf'),
        ))
        .load();
    await (FontLoader('madina2')..addFont(
          rootBundle.load('.local/handoff/app/UthmanicHafs1_Ver16.ttf'),
        ))
        .load();
    await (FontLoader('inter')
          ..addFont(rootBundle.load('.local/reader/Inter-Regular.ttf'))
          ..addFont(rootBundle.load('.local/reader/Inter-SemiBold.ttf')))
        .load();
  });
  testWidgets(
    'reader arrows expose one actionable button each and preserve entry state',
    (tester) async {
      tester.view.physicalSize = const Size(1220, 2712);
      tester.view.devicePixelRatio = 3;
      addTearDown(tester.view.reset);
      final semantics = tester.ensureSemantics();
      await openReader(tester);

      void expectArrow(String label, {bool enabled = true}) {
        final stops = tester.semantics.simulatedAccessibilityTraversal().where((
          node,
        ) {
          final data = node.getSemanticsData();
          return data.label.contains(label) || data.tooltip.contains(label);
        });
        expect(stops, hasLength(1), reason: '$label has one traversal stop');
        expect(
          stops.single,
          containsSemantics(
            label: label,
            isButton: true,
            isImage: false,
            hasEnabledState: true,
            isEnabled: enabled,
            hasTapAction: enabled,
          ),
        );
        expect(stops.single.rect.width, greaterThanOrEqualTo(48));
        expect(stops.single.rect.height, greaterThanOrEqualTo(48));
      }

      Future<void> activate(String label) async {
        tester.semantics.tap(find.semantics.byLabel(label));
        await tester.pumpAndSettle();
      }

      expectArrow('العودة إلى اختيار القراءة');
      expectArrow('الآية السابقة', enabled: false);
      expectArrow('الآية التالية');
      await activate('الآية التالية');
      expect(readerKey('1:2'), findsOneWidget);
      expectArrow('الآية السابقة');
      await activate('الآية السابقة');
      expect(readerKey('1:1'), findsOneWidget);
      expectArrow('الآية السابقة', enabled: false);

      await jump(tester, '27', '59');
      expectArrow('العودة إلى اختيار القراءة');
      expectArrow('الآية السابقة');
      expectArrow('الآية التالية');
      await activate('العودة إلى اختيار القراءة');
      expect(find.text('Reading'), findsOneWidget);
      expect(find.text('An-Naml'), findsOneWidget);
      expect(find.text('59 Verse'), findsOneWidget);
      await activate('Start Reading Quran');
      expect(readerKey('27:59'), findsOneWidget);

      await jump(tester, '114', '6');
      expectArrow('الآية التالية', enabled: false);
      expectArrow('الآية السابقة');
      await activate('الآية السابقة');
      expect(readerKey('114:5'), findsOneWidget);
      expectArrow('الآية التالية');
      await activate('الآية التالية');
      expect(readerKey('114:6'), findsOneWidget);
      expectArrow('الآية التالية', enabled: false);
      semantics.dispose();
    },
  );
  testWidgets(
    'entry explains separate reading and exposes an accessible start',
    (tester) async {
      await openReader(tester);
      await jump(tester, '27', '59');
      final semantics = tester.ensureSemantics();
      expect(
        tester.getSemantics(find.bySemanticsLabel('27. An-Naml\n59/93')),
        matchesSemantics(
          label: '27. An-Naml\n59/93',
          isButton: true,
          hasTapAction: true,
          hasFocusAction: true,
          isFocusable: true,
        ),
      );
      await readerEntry(tester);
      expect(
        find.text(
          'This is a separate Qur’an — your main daily Quran stays untouched',
        ),
        findsOneWidget,
      );
      final start = find.bySemanticsLabel('Start Reading Quran');
      expect(
        tester.getSemantics(start),
        matchesSemantics(
          label: 'Start Reading Quran',
          isButton: true,
          hasTapAction: true,
          hasFocusAction: true,
          isFocusable: true,
        ),
      );
      expect(tester.getSize(start).height, greaterThanOrEqualTo(48));
      await tapVisible(tester, start);
      expect(readerKey('27:59'), findsOneWidget);
      semantics.dispose();
    },
  );
  testWidgets(
    'captured Madina passage keeps right aligned word rows and canonical actions',
    (tester) async {
      tester.view.physicalSize = const Size(1220, 2712);
      tester.view.devicePixelRatio = 3;
      // Host diagnostic insets, not authenticated original system insets.
      tester.view.padding = FakeViewPadding(top: 108, bottom: 48);
      addTearDown(tester.view.reset);
      await openReader(tester);
      await jump(tester, '27', '59');
      final catalog = await QuranCatalog.load(_WidgetBundle());
      final ayah = catalog.ayah(const AyahKey(27, 59));
      final words = ayah.text.split(' ');
      final rendered = find.descendant(
        of: readerKey('27:59'),
        matching: find.byType(Text),
      );
      expect(
        tester.widgetList<Text>(rendered).map((w) => w.data).join(' '),
        ayah.text,
      );
      final first = tester.getRect(find.text(words.first));
      final lastOnFirst = tester.getRect(find.text(words[6]));
      final firstOnSecond = tester.getRect(find.text(words[7]));
      final last = tester.getRect(find.text(words.last));
      // Original PNG/XML bounds / density3. Allow rounding, not a similarity score.
      expect(first.top, closeTo(404, 1));
      expect(first.right, closeTo(368, 1));
      expect(lastOnFirst.top, closeTo(first.top, .1));
      expect(lastOnFirst.left, closeTo(116 / 3, 1));
      expect(firstOnSecond.top, closeTo(1394 / 3, 1));
      expect(firstOnSecond.right, closeTo(first.right, .1));
      expect(last.top, closeTo(firstOnSecond.top, .1));
      expect(last.left, closeTo(269 / 3, 1));
      final semantics = tester.ensureSemantics();
      expect(find.bySemanticsLabel('الآية 27:59 ${ayah.text}'), findsOneWidget);
      await tapVisible(tester, readerKey('27:59'));
      expect(find.text('27:59'), findsOneWidget);
      semantics.dispose();
    },
  );
  testWidgets(
    'first ayah preserves source font, exact Unicode semantics and disabled previous',
    (tester) async {
      await openReader(tester);
      final catalog = await QuranCatalog.load(_WidgetBundle());
      final first = catalog.ayah(const AyahKey(1, 1));
      final semantics = tester.ensureSemantics();
      await tester.pump();
      await tester.ensureVisible(readerKey('1:1'));
      await tester.pumpAndSettle();
      expect(find.bySemanticsLabel('الآية 1:1 ${first.text}'), findsOneWidget);
      final words = tester.widgetList<Text>(
        find.descendant(of: readerKey('1:1'), matching: find.byType(Text)),
      );
      expect(words.map((w) => w.data).join(' '), first.text);
      for (final text in words) {
        expect(text.style!.fontFamily, 'madina2');
        expect(text.textDirection, TextDirection.rtl);
      }
      expect(find.text('1/7'), findsOneWidget);
      expect(
        tester
            .widget<OutlinedButton>(
              find.byWidgetPredicate(
                (w) => w is OutlinedButton && w.onPressed == null,
              ),
            )
            .onPressed,
        isNull,
      );
      final page = jsonDecode(
        File('.local/handoff/source/page-1.json').readAsStringSync(),
      );
      for (final glyph in page['suras'][0]['texts']) {
        expect(find.text(glyph as String), findsNothing);
      }
      semantics.dispose();
    },
  );
  testWidgets('jump, next, previous and selection copy the visible ayah', (
    tester,
  ) async {
    String? clipboard;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData') {
          clipboard = call.arguments['text'] as String;
        }
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );
    await openReader(tester);
    await jump(tester, '1', '7');
    expect(readerKey('1:7'), findsOneWidget);
    await tapVisible(tester, find.byTooltip('الآية التالية'));
    expect(readerKey('2:1'), findsOneWidget);
    await tapVisible(tester, find.byTooltip('الآية السابقة'));
    expect(readerKey('1:7'), findsOneWidget);
    final catalog = await QuranCatalog.load(_WidgetBundle());
    for (final key in [
      const AyahKey(1, 7),
      const AyahKey(2, 281),
      const AyahKey(114, 6),
    ]) {
      await jump(tester, '${key.surah}', '${key.ayah}');
      final ayah = catalog.ayah(key);
      await tapVisible(tester, readerKey(key.reference));
      expect(find.text(key.reference), findsOneWidget);
      await tapVisible(tester, find.text('نسخ الآية مع المرجع'));
      expect(clipboard, '${ayah.text}\n${key.reference}');
    }
    expect(
      tester
          .widget<FilledButton>(
            find.ancestor(
              of: find.byTooltip('الآية التالية'),
              matching: find.byType(FilledButton),
            ),
          )
          .onPressed,
      isNull,
    );
    expect(tester.takeException(), isNull);
  });
  testWidgets('invalid selector searches never alter the selected passage', (
    tester,
  ) async {
    await openReader(tester);
    await jump(tester, '27', '59');
    await readerEntry(tester);
    await tapVisible(tester, find.text('Start from Verse'));
    for (final query in ['94', '999', '1.5']) {
      await tester.enterText(find.byType(TextField), query);
      await tester.pumpAndSettle();
      expect(
        find.byWidgetPredicate(
          (w) =>
              w is Semantics &&
              (w.properties.label?.startsWith('Verse ') ?? false),
        ),
        findsNothing,
      );
    }
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    await tapVisible(tester, find.text('Start Reading Quran'));
    expect(readerKey('27:59'), findsOneWidget);
    await jump(tester, '٢', '٢٨١');
    expect(readerKey('2:281'), findsOneWidget);
  });
  testWidgets(
    'surah list reaches the final surah and returns to its first ayah',
    (tester) async {
      await openReader(tester);
      await readerEntry(tester);
      await tapVisible(
        tester,
        find.byWidgetPredicate(
          (w) => w is Semantics && w.properties.label == 'السور',
        ),
      );
      final semantics = tester.ensureSemantics();
      await tester.pump();
      expect(
        find.bySemanticsLabel('فتح سورة الفاتحة، 7 آية، السورة 1'),
        findsOneWidget,
      );
      await revealChapter(tester, find.text('114. An-Nas'));
      await tapVisible(tester, find.text('114. An-Nas'));
      await tapVisible(tester, find.text('Start Reading Quran'));
      expect(readerKey('114:1'), findsOneWidget);
      expect(find.text('1/6'), findsOneWidget);
      semantics.dispose();
    },
  );
  for (final size in [const Size(320, 568), const Size(568, 320)]) {
    testWidgets('large text reader, jump, actions and surah list fit $size', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(size);
      tester.platformDispatcher.textScaleFactorTestValue = 2.5;
      addTearDown(() async {
        tester.platformDispatcher.clearTextScaleFactorTestValue();
        await tester.binding.setSurfaceSize(null);
      });
      await openReader(tester);
      await jump(tester, '2', '282');
      expect(readerKey('2:282'), findsOneWidget);
      await tapVisible(tester, find.byTooltip('إجراءات الآية'));
      await tapVisible(tester, find.text('إغلاق'));
      await tapVisible(tester, find.byTooltip('الآية التالية'));
      expect(readerKey('2:283'), findsOneWidget);
      await readerEntry(tester);
      await tapVisible(
        tester,
        find.byWidgetPredicate(
          (w) => w is Semantics && w.properties.label == 'السور',
        ),
      );
      await revealChapter(tester, find.text('114. An-Nas'));
      await tapVisible(tester, find.text('114. An-Nas'));
      await tapVisible(tester, find.text('Start Reading Quran'));
      expect(readerKey('114:1'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets('missing and corrupt local content have distinct retry states', (
    tester,
  ) async {
    final bundle = _RetryBundle();
    await openReader(tester, bundle: bundle);
    expect(find.text('ملف القرآن المحلي غير متاح.'), findsOneWidget);
    await tapVisible(tester, find.text('إعادة المحاولة'));
    expect(
      find.text('تعذّر فتح القرآن: المحتوى المحلي غير صالح.'),
      findsOneWidget,
    );
    await tapVisible(tester, find.text('إعادة المحاولة'));
    expect(readerKey('1:1'), findsOneWidget);
  });
  testWidgets('copy failure stays actionable and retry succeeds', (
    tester,
  ) async {
    var attempts = 0;
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        if (call.method == 'Clipboard.setData' && attempts++ == 0) {
          throw PlatformException(code: 'unavailable');
        }
        return null;
      },
    );
    addTearDown(
      () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        null,
      ),
    );
    await openReader(tester);
    await tapVisible(tester, find.byTooltip('إجراءات الآية'));
    await tapVisible(tester, find.text('نسخ الآية مع المرجع'));
    expect(find.text('تعذّر النسخ إلى الحافظة. أعد المحاولة.'), findsOneWidget);
    await tapVisible(tester, find.text('نسخ الآية مع المرجع'));
    expect(find.text('تم نسخ الآية مع المرجع'), findsOneWidget);
    expect(attempts, 2);
  });
}

class _RetryBundle extends CachingAssetBundle {
  var attempts = 0;
  @override
  Future<ByteData> load(String key) => rootBundle.load(key);
  @override
  Future<String> loadString(String key, {bool cache = true}) async {
    if (attempts++ == 0) return StringBundle(null).loadString(key);
    if (attempts == 2) return '{}';
    return _WidgetBundle().loadString(key, cache: false);
  }
}

// Preloaded actual asset bytes at the OS boundary. Large asset I/O and UTF-8
// isolates use real time; widget tests run in fake time. No content module is
// replaced, and the default rootBundle loader has its own full contract tests.
class _WidgetBundle extends CachingAssetBundle {
  @override
  Future<ByteData> load(String key) => rootBundle.load(key);
  @override
  Future<String> loadString(String key, {bool cache = true}) async =>
      _bundledQuran;
}
