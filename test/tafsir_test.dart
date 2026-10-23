import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' show ImageByteFormat;
import 'package:compatibility/content.dart';
import 'package:compatibility/main.dart';
import 'package:compatibility/reader.dart';
import 'package:compatibility/reader_metadata.dart';
import 'reader_test.dart' show readerKey, readerEntry, jump;
import 'package:compatibility/tafsir.dart';
import 'package:compatibility/personal.dart';
import 'package:compatibility/tafsir_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'content_test.dart' show StringBundle;

// Only the Android platform channel is substituted here. These are Flutter
// semantics/lifecycle tests, NOT Android SQLite or Html.fromHtml execution.
// Input comes from real prepared SQLite, not generated commentary/own mocks.
late Map<String, dynamic> samples;
late ReaderMetadata readerMetadata;
Map<String, dynamic> payload(AyahKey key) {
  final raw = samples[key.reference] as String;
  return {
    'book': 'ibn_kathir',
    'surah': key.surah,
    'ayah': key.ayah,
    'status': 'source_text',
    'rawText': raw,
    'displayText': raw,
  };
}

Future<void> tap(WidgetTester tester, String label) async {
  if (label == 'الانتقال إلى آية' || label == 'السور') {
    await readerEntry(tester);
  }
  if (label == 'العودة إلى القراءة' || label == 'المصدر والترخيص') {
    final list = tester.widget<ListView>(
      find
          .descendant(
            of: find.byType(TafsirView),
            matching: find.byType(ListView),
          )
          .last,
    );
    list.controller!.jumpTo(0);
    await tester.pumpAndSettle();
  }
  final target = find.text(label).evaluate().isNotEmpty
      ? find.text(label).first
      : find.byTooltip(label).evaluate().isNotEmpty
      ? find.byTooltip(label).first
      : find.bySemanticsLabel(label).first;
  await tester.ensureVisible(target);
  await tester.pumpAndSettle();
  final screen = Offset.zero & tester.getSize(find.byType(Scaffold).first);
  await tester.tapAt(tester.getRect(target).intersect(screen).center);
  await tester.pumpAndSettle();
  if (label == 'فتح الآية' && find.byType(AlertDialog).evaluate().isEmpty) {
    await tester.tap(find.text('Start Reading Quran'));
    await tester.pumpAndSettle();
  }
}

Widget shell(Widget child, {double scale = 1}) => MaterialApp(
  theme: ThemeData(
    colorScheme: const ColorScheme.light(
      primary: readerPurple,
      surface: readerCard,
      onSurface: readerInk,
    ),
  ),
  builder: (_, child) => MediaQuery(
    data: MediaQueryData(textScaler: TextScaler.linear(scale)),
    child: Directionality(textDirection: TextDirection.rtl, child: child!),
  ),
  home: child,
);

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  setUpAll(() async {
    readerMetadata = await ReaderMetadata.load(rootBundle);
    await (FontLoader(
      'MaterialIcons',
    )..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'))).load();
    await (FontLoader('inter')
          ..addFont(rootBundle.load('.local/reader/Inter-Regular.ttf'))
          ..addFont(rootBundle.load('.local/reader/Inter-SemiBold.ttf')))
        .load();
    final result = Process.runSync('python3', [
      '-c',
      '''
import sqlite3,json
c=sqlite3.connect('file:.local/handoff/app/arabic-three-tafsirs.sqlite?mode=ro&immutable=1',uri=True)
keys=[(1,1),(20,125),(114,6),(2,282),(27,59)]
print(json.dumps({f'{s}:{a}':c.execute("select text from tafseer_entries where tafseer_id='ibn_kathir' and surah=? and ayah=?",(s,a)).fetchone()[0] for s,a in keys}))
''',
    ]);
    expect(result.exitCode, 0, reason: '${result.stderr}');
    samples = jsonDecode(result.stdout as String) as Map<String, dynamic>;
    await (FontLoader('madina2')..addFont(
          rootBundle.load('.local/handoff/app/UthmanicHafs1_Ver16.ttf'),
        ))
        .load();
  });
  setUp(
    () => messenger.setMockMethodCallHandler(
      PersonalStore.channel,
      (_) async => 'ibn_kathir',
    ),
  );
  tearDown(
    () => messenger.setMockMethodCallHandler(PersonalStore.channel, null),
  );
  tearDown(
    () => messenger.setMockMethodCallHandler(TafsirContent.channel, null),
  );

  test(
    'lookup owns selected identity across async reader changes and preserves exact raw source',
    () async {
      final catalog = await QuranCatalog.load(rootBundle);
      final reader = ReaderController(catalog);
      addTearDown(reader.dispose);
      reader.open(const AyahKey(1, 1));
      final selected = reader.selectCurrent();
      final response = Completer<Map<String, dynamic>>();
      messenger.setMockMethodCallHandler(TafsirContent.channel, (call) async {
        expect(call.method, 'lookup');
        expect(call.arguments, {'book': 'ibn_kathir', 'surah': 1, 'ayah': 1});
        return response.future;
      });
      final pending = const TafsirContent().lookup(
        selected.key,
        book: TafsirBook.ibnKathir,
      );
      reader.open(const AyahKey(114, 6));
      response.complete(payload(selected.key));
      final entry = await pending;
      expect(entry.key, const AyahKey(1, 1));
      expect(entry.rawText.length, 131238);
      expect(entry.rawText, samples['1:1']);
      expect(entry.rawText.contains('\r\n'), true);
      expect(reader.current.key, const AyahKey(114, 6));
    },
  );

  test(
    'typed platform errors, invalid/missing source and retry are public results',
    () async {
      for (final failure in TafsirFailure.values) {
        messenger.setMockMethodCallHandler(
          TafsirContent.channel,
          (_) async => throw PlatformException(code: failure.name),
        );
        await expectLater(
          const TafsirContent().lookup(
            const AyahKey(20, 125),
            book: TafsirBook.ibnKathir,
          ),
          throwsA(
            isA<TafsirException>().having((e) => e.reason, 'reason', failure),
          ),
        );
      }
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (_) async => payload(const AyahKey(20, 125)),
      );
      expect(
        (await const TafsirContent().lookup(
          const AyahKey(20, 125),
          book: TafsirBook.ibnKathir,
        )).rawText,
        'أي: في الدنيا.',
      );
    },
  );

  test(
    'wrong book/key/status and empty responses never become selected commentary',
    () async {
      for (final replacement in [
        {'book': 'al_tabari'},
        {'surah': 1},
        {'ayah': 124},
        {'status': 'empty_markup'},
        {'rawText': ''},
        {'displayText': ''},
      ]) {
        messenger.setMockMethodCallHandler(
          TafsirContent.channel,
          (_) async => {...payload(const AyahKey(20, 125)), ...replacement},
        );
        await expectLater(
          const TafsirContent().lookup(
            const AyahKey(20, 125),
            book: TafsirBook.ibnKathir,
          ),
          throwsA(
            isA<TafsirException>().having(
              (e) => e.reason,
              'reason',
              TafsirFailure.invalidContent,
            ),
          ),
        );
      }
    },
  );

  test(
    'all supplied offline notices match independently pinned source bytes',
    () async {
      final notices = await loadTafsirNotices(rootBundle);
      expect(notices.length, 4);
      for (final (index, file) in [
        'ATTRIBUTION.txt',
        'LICENSE-DATA.txt',
        'SOURCE-DATA-NOTICE.txt',
        'READ-FIRST.txt',
      ].indexed) {
        expect(
          notices[index].text,
          File('.local/handoff/tafsir/$file').readAsStringSync(),
        );
      }
      expect(
        notices[0].text,
        contains('commercial redistribution is not resolved'),
      );
      expect(notices[1].text, contains('Use commercially'));
      expect(
        notices[2].text,
        contains(
          'Commercial redistribution of tafsir texts requires permission',
        ),
      );
    },
  );

  testWidgets(
    'direct bookstand sheet dismissals retain the exact reader key and scroll',
    (tester) async {
      tester.view.physicalSize = const Size(393, 873);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final lookups = <AyahKey>[];
      messenger.setMockMethodCallHandler(TafsirContent.channel, (call) async {
        final key = AyahKey(
          call.arguments['surah'] as int,
          call.arguments['ayah'] as int,
        );
        lookups.add(key);
        return payload(key);
      });
      const boundary = Key('reader-capture');
      await tester.pumpWidget(
        RepaintBoundary(
          key: boundary,
          child: MainApp(
            metadata: readerMetadata,
            bundle: StringBundle(
              File('.local/handoff/app/quran.json').readAsStringSync(),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await jump(tester, '27', '59');
      expect(find.text('27. An-Naml'), findsOneWidget);
      expect(find.text('59/93'), findsOneWidget);
      expect(find.text('Juz 20 : 168 Verses left'), findsOneWidget);
      final scroll = tester
          .widget<SingleChildScrollView>(find.byType(SingleChildScrollView))
          .controller!;
      final offset = scroll.offset;
      Future<void> capture(String name) async {
        if (Platform.environment['QURANLY_CAPTURE'] != '1') return;
        await tester.runAsync(() async {
          final repaint = tester.renderObject<RenderRepaintBoundary>(
            find.byKey(boundary),
          );
          final image = await repaint.toImage();
          final bytes = await image.toByteData(format: ImageByteFormat.png);
          File(
            '.local/parity/$name.png',
          ).writeAsBytesSync(bytes!.buffer.asUint8List());
          image.dispose();
        });
      }

      await tester.runAsync(
        () => precacheImage(
          const AssetImage('.local/reader/background.png'),
          tester.element(find.byType(ReaderView)),
        ),
      );
      await tester.pumpAndSettle();
      await capture('candidate-reader-host');
      for (final dismissal in ['system', 'outside', 'drag']) {
        await tap(tester, 'فتح التفسير');
        expect(find.byType(BottomSheet), findsOneWidget);
        expect(find.byType(TafsirView), findsOneWidget);
        expect(find.text('THE ANT 59/93'), findsOneWidget);
        expect(find.text('إجراءات الآية'), findsNothing);
        if (dismissal == 'system') {
          await capture('candidate-tafsir-host');
          await tester.binding.handlePopRoute();
        } else if (dismissal == 'outside') {
          await tester.tapAt(const Offset(8, 8));
        } else {
          await tester.dragFrom(
            tester.getTopLeft(find.byType(BottomSheet)) + const Offset(80, 12),
            const Offset(0, 700),
          );
        }
        await tester.pumpAndSettle();
        expect(find.byType(TafsirView), findsNothing);
        expect(readerKey('27:59'), findsOneWidget);
        expect(scroll.offset, offset);
      }
      expect(lookups, [
        const AyahKey(27, 59),
        const AyahKey(27, 59),
        const AyahKey(27, 59),
      ]);
      await readerEntry(tester);
      await capture('candidate-entry-host');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'selected reader to tafsir to offline source and app/system Back keeps same context',
    (tester) async {
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (call) async => payload(
          AyahKey(
            call.arguments['surah'] as int,
            call.arguments['ayah'] as int,
          ),
        ),
      );
      await tester.pumpWidget(
        MainApp(
          metadata: readerMetadata,
          bundle: StringBundle(
            File('.local/handoff/app/quran.json').readAsStringSync(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await jump(tester, '20', '125');
      await tap(tester, 'إجراءات الآية');
      await tap(tester, 'فتح التفسير');
      await tester.scrollUntilVisible(
        find.text('أي: في الدنيا.'),
        150,
        scrollable: find
            .descendant(
              of: find.byType(TafsirView),
              matching: find.byType(Scrollable),
            )
            .last,
      );
      expect(find.text('أي: في الدنيا.'), findsOneWidget);
      expect(find.text(TafsirBook.ibnKathir.title), findsOneWidget);
      expect(find.bySemanticsLabel('اختيار تفسير ابن كثير'), findsOneWidget);
      expect(
        find.text('20:125').evaluate().isNotEmpty
            ? find.text('20:125')
            : readerKey('20:125'),
        findsOneWidget,
      );
      await tap(tester, 'المصدر والترخيص');
      expect(find.textContaining('مصدر عربي مستقل'), findsOneWidget);
      await tap(tester, 'العودة إلى التفسير');
      await tester.scrollUntilVisible(
        find.text('أي: في الدنيا.'),
        150,
        scrollable: find
            .descendant(
              of: find.byType(TafsirView),
              matching: find.byType(Scrollable),
            )
            .last,
      );
      expect(find.text('أي: في الدنيا.'), findsOneWidget);
      await tap(tester, 'العودة إلى القراءة');
      expect(
        find.text('20:125').evaluate().isNotEmpty
            ? find.text('20:125')
            : readerKey('20:125'),
        findsOneWidget,
      );
      await tap(tester, 'إجراءات الآية');
      await tap(tester, 'فتح التفسير');
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(
        find.text('20:125').evaluate().isNotEmpty
            ? find.text('20:125')
            : readerKey('20:125'),
        findsOneWidget,
      );
      expect(find.byType(ReaderView), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'system Back during opening or error preserves reader across repeated real routes',
    (tester) async {
      final pending = Completer<Map<String, dynamic>>();
      var failNext = true;
      messenger.setMockMethodCallHandler(TafsirContent.channel, (call) async {
        final key = AyahKey(
          call.arguments['surah'] as int,
          call.arguments['ayah'] as int,
        );
        if (key == const AyahKey(1, 1)) return pending.future;
        if (failNext) {
          failNext = false;
          throw PlatformException(code: 'storage');
        }
        return payload(key);
      });
      await tester.pumpWidget(
        MainApp(
          metadata: readerMetadata,
          bundle: StringBundle(
            File('.local/handoff/app/quran.json').readAsStringSync(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tap(tester, 'إجراءات الآية');
      await tester.tap(find.text('فتح التفسير'));
      await tester.pump();
      await tester.pump(const Duration(seconds: 1));
      await tester.scrollUntilVisible(
        find.byType(CircularProgressIndicator),
        120,
        scrollable: find
            .descendant(
              of: find.byType(TafsirView),
              matching: find.byType(Scrollable),
            )
            .last,
      );
      expect(find.bySemanticsLabel('جارٍ فتح التفسير المحلي'), findsOneWidget);
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(find.byType(ReaderView), findsOneWidget);
      expect(
        find.text('1:1').evaluate().isNotEmpty
            ? find.text('1:1')
            : readerKey('1:1'),
        findsOneWidget,
      );
      await jump(tester, '114', '6');
      await tap(tester, 'إجراءات الآية');
      await tap(tester, 'فتح التفسير');
      expect(find.textContaining('مساحة التخزين المحلية'), findsOneWidget);
      // The disposed first route must not attach a late failure to this one.
      pending.completeError(PlatformException(code: 'corruptPack'));
      await tester.pumpAndSettle();
      expect(find.textContaining('مساحة التخزين المحلية'), findsOneWidget);
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(
        find.text('114:6').evaluate().isNotEmpty
            ? find.text('114:6')
            : readerKey('114:6'),
        findsOneWidget,
      );
      await tap(tester, 'إجراءات الآية');
      await tap(tester, 'فتح التفسير');
      expect(
        find.text('114:6').evaluate().isNotEmpty
            ? find.text('114:6')
            : readerKey('114:6'),
        findsOneWidget,
      );
      expect(find.textContaining('مِنَ الْجِنَّةِ وَالنَّاسِ'), findsWidgets);
      await tap(tester, 'العودة إلى القراءة');
      expect(find.byType(ReaderView), findsOneWidget);
      expect(
        find.text('114:6').evaluate().isNotEmpty
            ? find.text('114:6')
            : readerKey('114:6'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'long reader scroll and selected AyahKey survive commentary return',
    (tester) async {
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (call) async => payload(
          AyahKey(
            call.arguments['surah'] as int,
            call.arguments['ayah'] as int,
          ),
        ),
      );
      await tester.pumpWidget(
        MainApp(
          metadata: readerMetadata,
          bundle: StringBundle(
            File('.local/handoff/app/quran.json').readAsStringSync(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await jump(tester, '2', '282');
      await tap(tester, 'إجراءات الآية');
      final readerScroll = tester
          .widget<SingleChildScrollView>(
            find
                .byWidgetPredicate(
                  (w) => w is SingleChildScrollView && w.controller != null,
                  skipOffstage: false,
                )
                .first,
          )
          .controller!;
      final before = readerScroll.offset;
      expect(before, greaterThan(0));
      await tap(tester, 'فتح التفسير');
      expect(find.text('2:282'), findsOneWidget);
      await tap(tester, 'العودة إلى القراءة');
      expect(readerKey('2:282'), findsOneWidget);
      expect(readerScroll.offset, before);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'long opening complete raw paragraphs and last footnote remain reachable at large type in compact landscape',
    (tester) async {
      tester.view.physicalSize = const Size(640, 320);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (_) async => payload(const AyahKey(1, 1)),
      );
      await tester.pumpWidget(
        shell(
          const TafsirView(ayah: AyahKey(1, 1), surahName: 'الفاتحة'),
          scale: 2.5,
        ),
      );
      await tester.pumpAndSettle();
      final list = tester.widget<ListView>(find.byType(ListView));
      final lines = (samples['1:1'] as String).split('\n');
      expect(
        (list.childrenDelegate as SliverChildBuilderDelegate)
            .estimatedChildCount,
        lines.length + 2,
      );
      expect(lines.join('\n'), samples['1:1']);
      // Public scroll behavior through every lazy source block, without deleting
      // content to make a small synthetic long-entry fixture.
      for (var attempt = 0; attempt < 100; attempt++) {
        list.controller!.jumpTo(list.controller!.position.maxScrollExtent);
        await tester.pump();
        if (find
            .byKey(ValueKey('tafsir-line-${lines.length - 1}'))
            .evaluate()
            .isNotEmpty) {
          break;
        }
      }
      await tester.pumpAndSettle();
      expect(
        find.textContaining('ولم ترد هذه قراءةً عن أحد فيما علمت.'),
        findsOneWidget,
      );
      expect(find.textContaining('¬في "تفسيره" (1/ 93).¥'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'compact large-type Arabic controls expose semantics and keyboard focus',
    (tester) async {
      tester.view.physicalSize = const Size(640, 320);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final semantics = tester.ensureSemantics();
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (_) async => payload(const AyahKey(20, 125)),
      );
      await tester.pumpWidget(
        shell(
          const TafsirView(ayah: AyahKey(20, 125), surahName: 'طه'),
          scale: 2.5,
        ),
      );
      await tester.pumpAndSettle();
      expect(find.bySemanticsLabel('العودة إلى القراءة'), findsWidgets);
      expect(find.bySemanticsLabel('المصدر والترخيص'), findsWidgets);
      await tester.sendKeyEvent(LogicalKeyboardKey.tab);
      await tester.pumpAndSettle();
      final focusContext = FocusManager.instance.primaryFocus?.context;
      expect(focusContext, isNotNull);
      TextButton? focusedButton;
      focusContext!.visitAncestorElements((element) {
        if (element.widget is TextButton) {
          focusedButton = element.widget as TextButton;
          return false;
        }
        return true;
      });
      expect(focusedButton?.enabled, true);
      await tap(tester, 'المصدر والترخيص');
      expect(find.bySemanticsLabel('العودة إلى التفسير'), findsOneWidget);
      expect(tester.takeException(), isNull);
      semantics.dispose();
    },
  );

  testWidgets(
    'changed caller key cannot relabel a pending or completed earlier result',
    (tester) async {
      final first = Completer<Map<String, dynamic>>();
      final last = Completer<Map<String, dynamic>>();
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (call) => call.arguments['surah'] == 1 ? first.future : last.future,
      );
      await tester.pumpWidget(
        shell(const TafsirView(ayah: AyahKey(1, 1), surahName: 'الفاتحة')),
      );
      await tester.pump();
      await tester.pumpWidget(
        shell(const TafsirView(ayah: AyahKey(114, 6), surahName: 'الناس')),
      );
      await tester.pump();
      first.complete(payload(const AyahKey(1, 1)));
      await tester.pump();
      expect(
        find.text('114:6').evaluate().isNotEmpty
            ? find.text('114:6')
            : readerKey('114:6'),
        findsOneWidget,
      );
      expect(find.textContaining('مقدمة مفيدة تذكر'), findsNothing);
      last.complete(payload(const AyahKey(114, 6)));
      await tester.pumpAndSettle();
      expect(find.textContaining('مِنَ الْجِنَّةِ وَالنَّاسِ'), findsWidgets);
      // Also replace an already completed result; no old data while loading.
      final another = Completer<Map<String, dynamic>>();
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (_) => another.future,
      );
      await tester.pumpWidget(
        shell(const TafsirView(ayah: AyahKey(20, 125), surahName: 'طه')),
      );
      await tester.pump();
      expect(
        find.text('20:125').evaluate().isNotEmpty
            ? find.text('20:125')
            : readerKey('20:125'),
        findsOneWidget,
      );
      expect(find.textContaining('مِنَ الْجِنَّةِ وَالنَّاسِ'), findsNothing);
      another.complete(payload(const AyahKey(20, 125)));
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.text('أي: في الدنيا.'),
        150,
        scrollable: find
            .descendant(
              of: find.byType(TafsirView),
              matching: find.byType(Scrollable),
            )
            .last,
      );
      expect(find.text('أي: في الدنيا.'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'failed lookup retries and canceled opening cannot replace later ayah',
    (tester) async {
      var failures = true;
      messenger.setMockMethodCallHandler(TafsirContent.channel, (_) async {
        if (failures) throw PlatformException(code: 'corruptPack');
        return payload(const AyahKey(20, 125));
      });
      await tester.pumpWidget(
        shell(const TafsirView(ayah: AyahKey(20, 125), surahName: 'طه')),
      );
      await tester.pumpAndSettle();
      expect(
        find.text('تعذّر فتح التفسير: المحتوى المحلي غير صالح.'),
        findsOneWidget,
      );
      failures = false;
      await tap(tester, 'إعادة المحاولة');
      await tester.scrollUntilVisible(
        find.text('أي: في الدنيا.'),
        150,
        scrollable: find
            .descendant(
              of: find.byType(TafsirView),
              matching: find.byType(Scrollable),
            )
            .last,
      );
      expect(find.text('أي: في الدنيا.'), findsOneWidget);
      final lateResponse = Completer<Map<String, dynamic>>();
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (_) => lateResponse.future,
      );
      await tester.pumpWidget(
        shell(
          const TafsirView(
            key: ValueKey(1),
            ayah: AyahKey(1, 1),
            surahName: 'الفاتحة',
          ),
        ),
      );
      await tester.pump();
      await tester.pumpWidget(shell(const Text('reader 114:6')));
      lateResponse.completeError(PlatformException(code: 'missingAsset'));
      await tester.pumpAndSettle();
      expect(find.text('reader 114:6'), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
}
