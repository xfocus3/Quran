import 'dart:io';
import 'package:compatibility/main.dart';
import 'package:compatibility/passage_picker.dart';
import 'package:compatibility/reader_share.dart';
import 'package:compatibility/reader_metadata.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'reader_test.dart' show jump, readerEntry, tapVisible, readerKey;
import 'content_test.dart' show StringBundle;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late ReaderMetadata metadata;
  late String data;
  setUpAll(() async {
    data = File('.local/handoff/app/quran.json').readAsStringSync();
    metadata = await ReaderMetadata.load(rootBundle);
  });

  Future<void> open(WidgetTester tester) async {
    await tester.pumpWidget(
      MainApp(bundle: StringBundle(data), metadata: metadata),
    );
    await tester.pumpAndSettle();
  }

  testWidgets(
    'chapter search uses retained labels; verse search/clear/cancel preserve chapter',
    (tester) async {
      await open(tester);
      await jump(tester, '27', '59');
      await readerEntry(tester);
      await tapVisible(tester, find.text('An-Naml'));
      expect(find.byType(BottomSheet), findsOneWidget);
      expect(find.text('Chapter'), findsOneWidget);
      expect(find.byType(AlertDialog), findsNothing);
      await tester.enterText(find.byType(TextField), 'naml');
      await tester.pumpAndSettle();
      expect(find.text('27. An-Naml'), findsOneWidget);
      expect(find.text('The Ant'), findsOneWidget);
      expect(find.text('93 Verses'), findsOneWidget);
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      await tapVisible(tester, find.text('Start from Verse'));
      await tester.enterText(find.byType(TextField), '59');
      await tester.pumpAndSettle();
      expect(
        find.descendant(of: find.byType(GridView), matching: find.text('59')),
        findsOneWidget,
      );
      expect(find.text('60'), findsNothing);
      await tapVisible(tester, find.byTooltip('Clear search'));
      expect(find.text('1'), findsOneWidget);
      await tester.enterText(find.byType(TextField), '94');
      await tester.pumpAndSettle();
      expect(
        find.descendant(of: find.byType(GridView), matching: find.text('94')),
        findsNothing,
      );
      await tapVisible(tester, find.text('Cancel'));
      expect(find.text('1'), findsOneWidget);
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      await tapVisible(tester, find.text('Start Reading Quran'));
      expect(readerKey('27:59'), findsOneWidget);
    },
  );

  testWidgets('reader chapter sheet dismissals preserve exact key and scroll', (
    tester,
  ) async {
    await open(tester);
    await jump(tester, '27', '59');
    final scroll = tester
        .widget<SingleChildScrollView>(find.byType(SingleChildScrollView))
        .controller!;
    for (final action in ['system', 'outside', 'drag']) {
      await tester.ensureVisible(find.text('27. An-Naml'));
      await tester.pumpAndSettle();
      final offset = scroll.offset;
      await tester.tap(find.text('27. An-Naml'));
      await tester.pumpAndSettle();
      if (action == 'system') {
        await tester.binding.handlePopRoute();
      } else if (action == 'outside') {
        await tester.tapAt(const Offset(4, 4));
      } else {
        await tester.dragFrom(
          tester.getTopLeft(find.byType(PassagePicker)) + const Offset(80, 12),
          const Offset(0, 800),
        );
      }
      await tester.pumpAndSettle();
      expect(find.byType(PassagePicker), findsNothing, reason: action);
      expect(readerKey('27:59'), findsOneWidget);
      expect(scroll.offset, offset);
    }
  });

  for (final size in [const Size(320, 568), const Size(568, 320)]) {
    testWidgets('verse picker remains readable at2x with keyboard at $size', (
      tester,
    ) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(() {
        tester.view.reset();
        tester.platformDispatcher.clearTextScaleFactorTestValue();
      });
      await open(tester);
      await readerEntry(tester);
      await tapVisible(tester, find.text('Start from Verse'));
      tester.view.viewInsets = FakeViewPadding(bottom: size.height * .4);
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextField), '7');
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    });
  }

  testWidgets(
    'share arrow exports a PNG and selected identity directly; failure is retryable',
    (tester) async {
      final calls = <MethodCall>[];
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        AyahImageShare.channel,
        (call) async {
          calls.add(call);
          if (calls.length == 1) throw PlatformException(code: 'unavailable');
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          AyahImageShare.channel,
          null,
        ),
      );
      await open(tester);
      await jump(tester, '27', '59');
      for (var i = 0; i < 2; i++) {
        await tapVisible(tester, find.byTooltip('مشاركة الآية كصورة'));
        await tester.runAsync(() async {
          // Raster encoding uses the engine's real asynchronous boundary.
          for (
            var attempt = 0;
            attempt < 100 && calls.length < i + 1;
            attempt++
          ) {
            await Future<void>.delayed(const Duration(milliseconds: 10));
          }
          await Future<void>.delayed(const Duration(milliseconds: 100));
        });
        await tester.pumpAndSettle();
        expect(calls.length, i + 1);
        expect(calls.last.method, 'shareImage');
        final args = calls.last.arguments as Map;
        expect((args['surah'], args['ayah']), (27, 59));
        expect((args['png'] as Uint8List).take(8), [
          137,
          80,
          78,
          71,
          13,
          10,
          26,
          10,
        ]);
        expect(readerKey('27:59'), findsOneWidget);
        expect(find.text('إجراءات الآية'), findsNothing);
      }
      expect(
        find.text('تعذّرت مشاركة صورة الآية. أعد المحاولة.'),
        findsOneWidget,
      );
    },
  );
}
