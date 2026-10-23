import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:ui' show Tristate, SemanticsAction;
import 'package:compatibility/tafsir_view.dart';
import 'package:compatibility/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter/semantics.dart';
import 'tafsir_test.dart' show shell, tap;
import 'reader_test.dart' show readerKey, jump;
import 'package:compatibility/reader_metadata.dart';
import 'content_test.dart' show StringBundle;
import 'package:compatibility/personal.dart';
import 'package:compatibility/tafsir_session.dart';
import 'package:compatibility/content.dart';
import 'package:compatibility/tafsir.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

late ReaderMetadata readerMetadata;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
  tearDown(
    () => messenger.setMockMethodCallHandler(TafsirContent.channel, null),
  );
  test(
    'malformed top-level tafsir transport is invalidContent and retryable',
    () async {
      Object? response = 42;
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (_) async => response,
      );
      final invalidContent = throwsA(
        isA<TafsirException>().having(
          (error) => error.reason,
          'reason',
          TafsirFailure.invalidContent,
        ),
      );
      final valid = <Object?, Object?>{
        'book': 'al_saadi',
        'surah': 20,
        'ayah': 125,
        'status': 'source_text',
        'rawText': 'نص المصدر',
        'displayText': 'نص المصدر',
      };
      for (final malformed in [
        42,
        null,
        'text',
        <Object?>[],
        {1: 'value'},
        {...valid, 1: 'extra'},
      ]) {
        response = malformed;
        await expectLater(
          const TafsirContent().lookup(
            const AyahKey(20, 125),
            book: TafsirBook.alSaadi,
          ),
          invalidContent,
        );
      }
      response = valid;
      final entry = await const TafsirContent().lookup(
        const AyahKey(20, 125),
        book: TafsirBook.alSaadi,
      );
      expect(entry.rawText, 'نص المصدر');
    },
  );
  test('malformed saved author responses remain typed and retryable', () async {
    addTearDown(
      () => messenger.setMockMethodCallHandler(PersonalStore.channel, null),
    );
    for (final invalid in [
      null,
      42,
      ['al_tabari'],
      'unknown',
    ]) {
      messenger.setMockMethodCallHandler(
        PersonalStore.channel,
        (_) async => invalid,
      );
      await expectLater(
        const PersonalStore().readTafsirBook(),
        throwsA(
          isA<PersonalException>().having(
            (error) => error.reason,
            'reason',
            PersonalFailure.invalidData,
          ),
        ),
      );
    }
    messenger.setMockMethodCallHandler(
      PersonalStore.channel,
      (_) async => 'al_saadi',
    );
    expect(await const PersonalStore().readTafsirBook(), TafsirBook.alSaadi);
  });
  test(
    'explicit book lookup preserves empty selected source and ordered context identities',
    () async {
      messenger.setMockMethodCallHandler(TafsirContent.channel, (call) async {
        expect(call.method, 'lookup');
        expect(call.arguments, {'book': 'al_tabari', 'surah': 4, 'ayah': 168});
        Map<String, dynamic> row(
          int ayah,
          String status,
          String raw,
          String display,
        ) => {
          'book': 'al_tabari',
          'surah': 4,
          'ayah': ayah,
          'status': status,
          'rawText': raw,
          'displayText': display,
        };
        return {
          ...row(168, 'empty_markup', '<br>', '\n'),
          'context': {
            'fromAyah': 168,
            'toAyah': 169,
            'headingAyah': 169,
            'headingText': 'عنوان المصدر',
            'basis': 'source-derived',
            'rows': [
              row(168, 'empty_markup', '<br>', '\n'),
              row(169, 'source_text', 'نص المصدر', 'نص المصدر'),
            ],
          },
        };
      });
      final entry = await const TafsirContent().lookup(
        const AyahKey(4, 168),
        book: TafsirBook.alTabari,
      );
      expect(entry.book, TafsirBook.alTabari);
      expect(entry.status, TafsirStatus.emptyMarkup);
      expect(entry.rawText, '<br>');
      expect(entry.context!.rows.map((e) => e.key), [
        const AyahKey(4, 168),
        const AyahKey(4, 169),
      ]);
      expect(entry.context!.rows.last.rawText, 'نص المصدر');
      expect(entry.key, const AyahKey(4, 168));
    },
  );
  test(
    'latest author wins late content and failed old save; next session reads explicit persisted author',
    () async {
      var saved = 'ibn_kathir';
      final firstSave = Completer<void>();
      final oldLookup = Completer<Map<String, dynamic>>();
      final key = const AyahKey(20, 125);
      messenger.setMockMethodCallHandler(PersonalStore.channel, (call) async {
        if (call.method == 'readTafsirBook') return saved;
        final book = call.arguments['book'] as String;
        if (book == 'al_tabari') await firstSave.future;
        saved = book;
        return null;
      });
      addTearDown(
        () => messenger.setMockMethodCallHandler(PersonalStore.channel, null),
      );
      messenger.setMockMethodCallHandler(TafsirContent.channel, (call) async {
        final book = call.arguments['book'];
        if (book == 'al_tabari') return oldLookup.future;
        return {
          'book': book,
          'surah': 20,
          'ayah': 125,
          'status': 'source_text',
          'rawText': 'نص $book',
          'displayText': 'نص $book',
        };
      });
      final session = TafsirSession(key);
      addTearDown(session.dispose);
      await session.initialize();
      expect(session.book, TafsirBook.ibnKathir);
      session.choose(TafsirBook.alTabari);
      await Future<void>.delayed(Duration.zero);
      session.choose(TafsirBook.alSaadi);
      await Future<void>.delayed(Duration.zero);
      expect(session.entry?.book, TafsirBook.alSaadi);
      firstSave.completeError(PlatformException(code: 'storage'));
      oldLookup.completeError(PlatformException(code: 'corruptPack'));
      await Future<void>.delayed(Duration.zero);
      await Future<void>.delayed(Duration.zero);
      expect(session.book, TafsirBook.alSaadi);
      expect(session.contentError, isNull);
      expect(session.preferenceError, isNull);
      expect(session.saving, false);
      expect(saved, 'al_saadi');
      final reopened = TafsirSession(key);
      addTearDown(reopened.dispose);
      await reopened.initialize();
      expect(reopened.book, TafsirBook.alSaadi);
      expect(reopened.entry?.book, TafsirBook.alSaadi);
    },
  );
  test(
    'preference read failure never silently defaults; failed save stays visible until retry',
    () async {
      var failRead = true, failWrite = true;
      messenger.setMockMethodCallHandler(PersonalStore.channel, (call) async {
        if (call.method == 'readTafsirBook') {
          if (failRead) throw PlatformException(code: 'unsupportedVersion');
          return 'al_tabari';
        }
        if (failWrite) throw PlatformException(code: 'storage');
        return null;
      });
      addTearDown(
        () => messenger.setMockMethodCallHandler(PersonalStore.channel, null),
      );
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (call) async => {
          'book': call.arguments['book'],
          'surah': 20,
          'ayah': 125,
          'status': 'source_text',
          'rawText': 'نص',
          'displayText': 'نص',
        },
      );
      final session = TafsirSession(const AyahKey(20, 125));
      addTearDown(session.dispose);
      await session.initialize();
      expect(session.book, isNull);
      expect(
        session.preferenceError?.reason,
        PersonalFailure.unsupportedVersion,
      );
      failRead = false;
      await session.initialize();
      expect(session.book, TafsirBook.alTabari);
      session.choose(TafsirBook.alSaadi);
      await Future<void>.delayed(Duration.zero);
      expect(session.preferenceError?.reason, PersonalFailure.storage);
      expect(session.entry?.book, TafsirBook.alSaadi);
      failWrite = false;
      await session.retryPreference();
      expect(session.preferenceError, isNull);
      expect(session.saving, false);
    },
  );
  test(
    'successful old result cannot replace newer author; reopening waits for queued durable writes',
    () async {
      final old = Completer<Map<String, dynamic>>();
      final saving = Completer<void>();
      var saved = 'ibn_kathir';
      messenger.setMockMethodCallHandler(PersonalStore.channel, (call) async {
        if (call.method == 'readTafsirBook') return saved;
        if (call.arguments['book'] == 'al_tabari') await saving.future;
        saved = call.arguments['book'] as String;
        return null;
      });
      addTearDown(
        () => messenger.setMockMethodCallHandler(PersonalStore.channel, null),
      );
      messenger.setMockMethodCallHandler(TafsirContent.channel, (call) async {
        if (call.arguments['book'] == 'al_tabari') return old.future;
        return {
          'book': call.arguments['book'],
          'surah': 20,
          'ayah': 125,
          'status': 'source_text',
          'rawText': 'السعدي',
          'displayText': 'السعدي',
        };
      });
      final session = TafsirSession(const AyahKey(20, 125));
      await session.initialize();
      session.choose(TafsirBook.alTabari);
      session.choose(TafsirBook.alSaadi);
      await Future<void>.delayed(Duration.zero);
      old.complete({
        'book': 'al_tabari',
        'surah': 20,
        'ayah': 125,
        'status': 'source_text',
        'rawText': 'الطبري',
        'displayText': 'الطبري',
      });
      await Future<void>.delayed(Duration.zero);
      expect(session.entry?.book, TafsirBook.alSaadi);
      session.dispose();
      final reopened = TafsirSession(const AyahKey(20, 125));
      addTearDown(reopened.dispose);
      final ready = reopened.initialize();
      expect(reopened.book, isNull);
      saving.complete();
      await ready;
      expect(saved, 'al_saadi');
      expect(reopened.book, TafsirBook.alSaadi);
    },
  );

  // Only the OS channel is replaced: exact prepared raw rows are the fixture.
  // This view test does NOT execute the production native SQLite/Html adapter.
  late Map<String, dynamic> fixtures;
  setUpAll(() async {
    readerMetadata = await ReaderMetadata.load(rootBundle);
    final result = Process.runSync('python3', [
      '-c',
      r'''
import sqlite3,json
c=sqlite3.connect('file:.local/handoff/app/arabic-three-tafsirs.sqlite?mode=ro&immutable=1',uri=True)
def row(book,s,a):
 raw,status=c.execute('select text,content_status from tafseer_entries where tafseer_id=? and surah=? and ayah=?',(book,s,a)).fetchone()
 return dict(book=book,surah=s,ayah=a,status=status,rawText=raw,displayText=raw.replace('<br>','\n'))
output={}
for book in ['ibn_kathir','al_tabari','al_saadi']:
 for s,a in [(4,168),(26,16),(26,205),(37,25),(37,62),(37,103),(50,13),(2,196),(12,111)]:
  entry=row(book,s,a)
  group=c.execute('select from_ayah,to_ayah,heading_ayah,heading_text,basis from tafseer_context_ranges where tafseer_id=? and surah=? and ayah=?',(book,s,a)).fetchone()
  if group:
   f,t,h,title,basis=group
   entry['context']=dict(fromAyah=f,toAyah=t,headingAyah=h,headingText=title,basis=basis,rows=[row(book,s,i) for i in range(f,t+1)])
  output[f'{book}/{s}:{a}']=entry
print(json.dumps(output))
''',
    ]);
    expect(result.exitCode, 0, reason: result.stderr as String);
    fixtures = jsonDecode(result.stdout as String) as Map<String, dynamic>;
  });

  Future<void> channels({
    String initial = 'ibn_kathir',
    bool failSave = false,
  }) async {
    var saved = initial;
    messenger.setMockMethodCallHandler(PersonalStore.channel, (call) async {
      if (call.method == 'readTafsirBook') return saved;
      if (failSave) throw PlatformException(code: 'storage');
      saved = call.arguments['book'] as String;
      return null;
    });
    messenger.setMockMethodCallHandler(
      TafsirContent.channel,
      (call) async =>
          fixtures['${call.arguments['book']}/${call.arguments['surah']}:${call.arguments['ayah']}'],
    );
  }

  tearDown(
    () => messenger.setMockMethodCallHandler(PersonalStore.channel, null),
  );

  testWidgets(
    'author, context, source and both Back controls retain reader ayah',
    (tester) async {
      await channels();
      await tester.pumpWidget(
        MainApp(
          metadata: readerMetadata,
          bundle: StringBundle(
            File('.local/handoff/app/quran.json').readAsStringSync(),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await jump(tester, '4', '168');
      await tap(tester, 'إجراءات الآية');
      await tap(tester, 'فتح التفسير');
      await tap(tester, 'الطبري');
      await tap(tester, 'فتح السياق المحيط 4:168–169');
      expect(
        find.byType(TafsirView).evaluate().isNotEmpty
            ? find.text('4:168')
            : readerKey('4:168'),
        findsOneWidget,
      );
      expect(find.text('إخفاء السياق المحيط'), findsOneWidget);
      await tap(tester, 'المصدر والترخيص');
      expect(find.textContaining('مصدر عربي مستقل'), findsOneWidget);
      await tap(tester, 'العودة إلى التفسير');
      expect(find.text('إخفاء السياق المحيط'), findsOneWidget);
      await tap(tester, 'السعدي');
      expect(
        find.byType(TafsirView).evaluate().isNotEmpty
            ? find.text('4:168')
            : readerKey('4:168'),
        findsOneWidget,
      );
      expect(find.text('إخفاء السياق المحيط'), findsNothing);
      await tap(tester, 'العودة إلى القراءة');
      expect(find.byType(ReaderView), findsOneWidget);
      expect(
        find.byType(TafsirView).evaluate().isNotEmpty
            ? find.text('4:168')
            : readerKey('4:168'),
        findsOneWidget,
      );
      await tap(tester, 'إجراءات الآية');
      await tap(tester, 'فتح التفسير');
      expect(find.bySemanticsLabel('اختيار تفسير السعدي'), findsOneWidget);
      expect(
        find.byType(TafsirView).evaluate().isNotEmpty
            ? find.text('4:168')
            : readerKey('4:168'),
        findsOneWidget,
      );
      await tester.binding.handlePopRoute();
      await tester.pumpAndSettle();
      expect(find.byType(ReaderView), findsOneWidget);
      expect(
        find.byType(TafsirView).evaluate().isNotEmpty
            ? find.text('4:168')
            : readerKey('4:168'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'malformed tafsir responses leave loading and allow public retry',
    (tester) async {
      await channels(initial: 'al_saadi');
      Object? response;
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (_) async => response,
      );
      final valid = fixtures['al_saadi/4:168'];
      for (final malformed in [
        null,
        42,
        'text',
        <Object?>[],
        {1: 'value'},
        {...valid as Map, 1: 'extra'},
      ]) {
        response = malformed;
        await tester.pumpWidget(
          shell(
            TafsirView(
              key: UniqueKey(),
              ayah: const AyahKey(4, 168),
              surahName: 'النساء',
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('إعادة المحاولة'), findsOneWidget);
        expect(find.byType(CircularProgressIndicator), findsNothing);
        expect(tester.takeException(), isNull);
        response = valid;
        await tap(tester, 'إعادة المحاولة');
        expect(find.text('إعادة المحاولة'), findsNothing);
        await tester.scrollUntilVisible(
          find.text('نهاية تفسير الآية 4:168'),
          250,
          scrollable: find.byType(Scrollable).first,
        );
        expect(find.text('نهاية تفسير الآية 4:168'), findsOneWidget);
        expect(tester.takeException(), isNull);
      }
    },
  );

  testWidgets('content failures show Arabic reasons and an accessible retry', (
    tester,
  ) async {
    for (final failure in TafsirFailure.values) {
      await channels();
      messenger.setMockMethodCallHandler(
        TafsirContent.channel,
        (_) async => throw PlatformException(code: failure.name),
      );
      await tester.pumpWidget(
        shell(
          TafsirView(
            key: ValueKey(failure),
            ayah: const AyahKey(4, 168),
            surahName: 'النساء',
          ),
        ),
      );
      await tester.pumpAndSettle();
      final text = tester
          .widgetList<Text>(find.byType(Text))
          .map((block) => block.data ?? '')
          .join('\n');
      expect(text, contains('إعادة المحاولة'));
      expect(text, isNot(contains(failure.name)));
      expect(
        text,
        contains(
          failure == TafsirFailure.invalidBook
              ? 'اختيار المفسر غير صالح'
              : failure == TafsirFailure.invalidReference
              ? 'مرجع الآية غير صالح'
              : failure == TafsirFailure.missingEntry
              ? 'لم يُعثر على تفسير'
              : failure == TafsirFailure.missingAsset
              ? 'ملف التفسير المحلي غير متاح'
              : 'تعذّر',
        ),
      );
    }
  });

  for (final size in [const Size(375, 740), const Size(640, 320)]) {
    for (final sheet in [false, true]) {
      testWidgets(
        '2x chooser has selected author semantics and 48dp controls at $size sheet=$sheet',
        (tester) async {
          tester.view.physicalSize = size;
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          final semantics = tester.ensureSemantics();

          await channels(failSave: true);
          await tester.pumpWidget(
            shell(
              TafsirView(
                ayah: const AyahKey(4, 168),
                surahName: 'النساء',
                sheet: sheet,
              ),
              scale: 2,
            ),
          );
          await tester.pumpAndSettle();
          for (final book in TafsirBook.values) {
            await tap(tester, book.author);
            final selected = find.byWidgetPredicate(
              (w) =>
                  w is Semantics &&
                  w.properties.label == 'اختيار تفسير ${book.author}',
            );
            expect(
              tester.getSemantics(selected).flagsCollection.isSelected,
              Tristate.isTrue,
            );
            final node = tester.getSemantics(selected);
            expect(
              node.getSemanticsData().hasAction(SemanticsAction.tap),
              true,
            );
            expect(
              node.getSemanticsData().label,
              'اختيار تفسير ${book.author}',
            );
            expect(node.getSemanticsData().flagsCollection.isButton, true);
            var childActions = 0;
            void countActions(SemanticsNode child) {
              if (child.isMergedIntoParent) return;
              if (child.getSemanticsData().hasAction(SemanticsAction.tap)) {
                childActions++;
              }
              child.visitChildren((descendant) {
                countActions(descendant);
                return true;
              });
            }

            node.visitChildren((child) {
              countActions(child);
              return true;
            });
            expect(childActions, 0);
            final button = find.widgetWithText(OutlinedButton, book.author);
            expect(tester.getSize(button).height, greaterThanOrEqualTo(48));
            expect(
              find.byType(TafsirView).evaluate().isNotEmpty
                  ? find.text('4:168')
                  : readerKey('4:168'),
              findsOneWidget,
            );
            expect(tester.takeException(), isNull);
          }
          await tester.ensureVisible(
            find.textContaining('تعذّر حفظ اختيار المفسر'),
          );
          await tester.pumpAndSettle();
          expect(find.text('إعادة حفظ الاختيار'), findsOneWidget);
          expect(find.textContaining('لهذه الجلسة فقط'), findsOneWidget);
          await tester.sendKeyEvent(LogicalKeyboardKey.tab);
          await tester.pumpAndSettle();
          expect(FocusManager.instance.primaryFocus?.context, isNotNull);
          semantics.dispose();
        },
      );
    }
  }

  testWidgets(
    'all seven empty selected entries offer actual complete source context without changing identity',
    (tester) async {
      final contract =
          jsonDecode(
                File('docs/phase-4/content-contract.json').readAsStringSync(),
              )
              as Map<String, dynamic>;
      await channels(initial: 'al_tabari');
      for (final c in contract['contexts'] as List) {
        final s = c['surah'] as int, a = c['selected'] as int;
        await tester.pumpWidget(
          shell(
            TafsirView(
              key: ValueKey('$s:$a'),
              ayah: AyahKey(s, a),
              surahName: 'السورة',
            ),
          ),
        );
        await tester.pumpAndSettle();
        expect(
          find.textContaining('لا يوجد نص تفسير مستقل لهذه الآية'),
          findsOneWidget,
        );
        expect(
          find.text('سجل المصدر $s:${c['heading']} — الطبري'),
          findsNothing,
        );
        await tap(tester, 'فتح السياق المحيط $s:${c['from']}–${c['to']}');
        expect(find.text('$s:$a'), findsOneWidget);
        final list = tester.widget<ListView>(find.byType(ListView));
        // Read every laid-out block through the actual scroll boundary; keep
        // source references/status and all terminal rows discoverable in order.
        list.controller!.jumpTo(0);
        await tester.pump();
        final seen = <String>{};
        var last = -1.0;
        for (var i = 0; i < 500; i++) {
          seen.addAll(
            tester.widgetList<Text>(find.byType(Text)).map((w) => w.data ?? ''),
          );
          final position = list.controller!.position;
          if (position.pixels == position.maxScrollExtent &&
              position.pixels == last) {
            break;
          }
          last = position.pixels;
          list.controller!.jumpTo(
            (position.pixels + 250).clamp(0, position.maxScrollExtent),
          );
          await tester.pump();
        }
        for (final row in c['source_rows'] as List) {
          expect(seen, contains('سجل المصدر $s:${row['ayah']} — الطبري'));
        }
        expect(seen, contains('حالة المصدر: لا يوجد نص مستقل.'));
        expect(seen, contains('حالة المصدر: نص المصدر.'));
        expect(seen.join('\n'), isNot(contains('empty_markup')));
        expect(seen.join('\n'), isNot(contains('source_text')));
        expect(seen, contains('نهاية السياق $s:${c['from']}–${c['to']}'));
        expect(seen, contains('نهاية تفسير الآية $s:$a'));
        expect(tester.takeException(), isNull);
      }
    },
  );

  for (final sample in [
    ('al_tabari', const AyahKey(2, 196)),
    ('al_saadi', const AyahKey(12, 111)),
  ]) {
    testWidgets('complete longest ${sample.$1} reaches exact final text at 2x', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(640, 320);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      await channels(initial: sample.$1);
      await tester.pumpWidget(
        shell(TafsirView(ayah: sample.$2, surahName: 'السورة'), scale: 2),
      );
      await tester.pumpAndSettle();
      final list = tester.widget<ListView>(find.byType(ListView));
      final text =
          (fixtures['${sample.$1}/${sample.$2.reference}']
                  as Map)['displayText']
              as String;
      final lines = text.split('\n');
      final seen = <String>{};
      var reachedEnd = false;
      // Traverse the public scrolling/rendering boundary, rather than assert
      // a delegate's child count or jump past potentially omitted middle text.
      for (var i = 0; i < 10000; i++) {
        for (final block in tester.widgetList<Text>(find.byType(Text))) {
          seen.add(block.data ?? '');
          expect(block.maxLines, isNull);
        }
        final position = list.controller!.position;
        if (position.pixels == position.maxScrollExtent) {
          reachedEnd = true;
          break;
        }
        list.controller!.jumpTo(
          (position.pixels + position.viewportDimension * .75).clamp(
            0,
            position.maxScrollExtent,
          ),
        );
        await tester.pump();
      }
      expect(reachedEnd, true);
      expect(seen, containsAll(lines.toSet()));
      final end = lines.lastWhere((line) => line.trim().isNotEmpty);
      expect(
        find.text('نهاية تفسير الآية ${sample.$2.reference}'),
        findsOneWidget,
      );
      for (var i = 0; i < 20 && find.text(end).evaluate().isEmpty; i++) {
        list.controller!.jumpTo(
          (list.controller!.offset - 250).clamp(
            0,
            list.controller!.position.maxScrollExtent,
          ),
        );
        await tester.pump();
      }
      expect(find.text(end), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  }
}
