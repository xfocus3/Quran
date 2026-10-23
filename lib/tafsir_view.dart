import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'content.dart';
import 'tafsir.dart';
import 'tafsir_session.dart';
import 'personal.dart';

/// Commentary and source documents use the platform prose font and its Arabic
/// fallback. The recovered madina2 font belongs to Quran text, including its
/// specialized punctuation glyphs. Scope both destinations independently since
/// a pushed source route does not inherit the tafsir route's local theme.
class _TafsirProse extends StatelessWidget {
  const _TafsirProse({required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Theme(
      data: theme.copyWith(
        textTheme: theme.textTheme.apply(fontFamily: 'Roboto'),
        primaryTextTheme: theme.primaryTextTheme.apply(fontFamily: 'Roboto'),
      ),
      child: child,
    );
  }
}

/// Route owns a snapshot of the caller key. Lookup completion, retry and Back
/// cannot move the reader underneath. Disposed routes ignore outstanding work;
/// native installation may finish atomically for the next opening.
class TafsirView extends StatefulWidget {
  const TafsirView({
    super.key,
    required this.ayah,
    required this.surahName,
    this.sheet = false,
    this.referenceHeading,
  });
  final AyahKey ayah;
  final String surahName;
  final bool sheet;
  final String? referenceHeading;
  @override
  State<TafsirView> createState() => _TafsirViewState();
}

class _TafsirViewState extends State<TafsirView> {
  late final TafsirSession _session;
  final _scroll = ScrollController();
  bool _contextOpen = false;

  @override
  void initState() {
    super.initState();
    _session = TafsirSession(widget.ayah)..addListener(_update);
    _session.initialize();
  }

  void _update() {
    if (mounted) setState(() {});
  }

  void _top() {
    _contextOpen = false;
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  @override
  void didUpdateWidget(covariant TafsirView oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.ayah != widget.ayah) {
      _top();
      _session.changeKey(widget.ayah);
    }
  }

  @override
  void dispose() {
    _session.removeListener(_update);
    _session.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _source() => Navigator.of(
    context,
  ).push<void>(MaterialPageRoute(builder: (_) => const TafsirSourceView()));

  Widget _controls() => Wrap(
    spacing: 12,
    runSpacing: 8,
    children: [
      TextButton.icon(
        onPressed: () => Navigator.pop(context),
        icon: const Icon(Icons.arrow_back),
        label: const Text('العودة إلى القراءة'),
      ),
      TextButton.icon(
        onPressed: _source,
        icon: const Icon(Icons.info_outline),
        label: const Text('المصدر والترخيص'),
      ),
    ],
  );

  Widget _heading(String text) => Semantics(
    header: true,
    child: Text(
      text,
      style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
    ),
  );

  Widget _header() {
    final book = _session.book;
    final entry = _session.entry;
    final group = entry?.context;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (widget.sheet) ...[
          Center(child: _heading(book?.title ?? 'التفسير')),
          const SizedBox(height: 16),
          Text(
            widget.referenceHeading ?? widget.surahName,
            textDirection: TextDirection.ltr,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 16),
        ],
        _controls(),
        const SizedBox(height: 16),
        if (!widget.sheet) Text(widget.surahName),
        Text(
          widget.ayah.reference,
          textDirection: TextDirection.ltr,
          textAlign: TextAlign.right,
          semanticsLabel: 'تفسير الآية ${widget.ayah.reference}',
        ),
        const SizedBox(height: 16),
        if (widget.sheet)
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              for (final candidate in TafsirBook.values)
                MergeSemantics(
                  child: Semantics(
                    selected: book == candidate,
                    label: 'اختيار تفسير ${candidate.author}',
                    child: OutlinedButton(
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(48, 48),
                      ),
                      onPressed: book == null
                          ? null
                          : () {
                              _top();
                              _session.choose(candidate);
                            },
                      child: ExcludeSemantics(
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Icon(
                              book == candidate
                                  ? Icons.radio_button_checked
                                  : Icons.radio_button_unchecked,
                              size: 18,
                            ),
                            const SizedBox(width: 6),
                            Flexible(child: Text(candidate.author)),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
            ],
          )
        else
          _heading('اختيار المفسر'),
        if (!widget.sheet)
          for (final candidate in TafsirBook.values)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: MergeSemantics(
                child: Semantics(
                  selected: book == candidate,
                  label: 'اختيار تفسير ${candidate.author}',
                  child: OutlinedButton(
                    style: OutlinedButton.styleFrom(
                      minimumSize: const Size(48, 48),
                    ),
                    onPressed: book == null
                        ? null
                        : () {
                            _top();
                            _session.choose(candidate);
                          },
                    child: ExcludeSemantics(
                      child: Row(
                        children: [
                          Icon(
                            book == candidate
                                ? Icons.radio_button_checked
                                : Icons.radio_button_unchecked,
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              candidate.author,
                              style: const TextStyle(fontSize: 20),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
        if (_session.saving)
          Semantics(liveRegion: true, child: Text('جارٍ حفظ اختيار المفسر…')),
        if (_session.preferenceError != null) ...[
          Semantics(
            liveRegion: true,
            child: Text(
              book == null
                  ? 'تعذّرت قراءة اختيار المفسر المحفوظ. لم يُستخدم اختيار افتراضي. ${_personalError(_session.preferenceError!)}'
                  : 'تعذّر حفظ اختيار المفسر. الاختيار الحالي لهذه الجلسة فقط. ${_personalError(_session.preferenceError!)}',
            ),
          ),
          TextButton(
            onPressed: _session.retryPreference,
            child: Text(
              book == null ? 'إعادة قراءة الاختيار' : 'إعادة حفظ الاختيار',
            ),
          ),
        ],
        if (book != null && !widget.sheet) ...[
          const SizedBox(height: 24),
          if (!widget.sheet) _heading(book.title),
          Text('المفسر: ${book.author}', style: const TextStyle(fontSize: 22)),
        ],
        if (entry?.status == TafsirStatus.emptyMarkup) ...[
          const SizedBox(height: 16),
          Semantics(
            liveRegion: true,
            child: Text(
              'لا يوجد نص تفسير مستقل لهذه الآية في سجل المصدر المحدد.',
            ),
          ),
          if (group != null)
            TextButton(
              onPressed: () => setState(() => _contextOpen = !_contextOpen),
              child: Text(
                _contextOpen
                    ? 'إخفاء السياق المحيط'
                    : 'فتح السياق المحيط ${widget.ayah.surah}:${group.fromAyah}–${group.toAyah}',
              ),
            ),
        ],
        const SizedBox(height: 24),
      ],
    );
  }

  @override
  Widget build(BuildContext context) => _TafsirProse(child: _content(context));

  Widget _content(BuildContext context) {
    final entry = _session.entry;
    final group = entry?.context;
    // Presentation consumes the native grouping, never guesses a heading row
    // or parses raw markup. All derived display characters/blank lines survive.
    final lines = <String>[];
    if (entry != null) {
      lines.addAll(entry.displayText.split('\n'));
      if (_contextOpen && group != null) {
        lines.addAll([
          'السياق المحيط ${entry.key.surah}:${group.fromAyah}–${group.toAyah}',
          'الآية المختارة ${entry.key.reference} — ${entry.book.author}',
          'عنوان المقطع في سجل المصدر ${entry.key.surah}:${group.headingAyah}',
          group.headingText,
          'سجلات المصدر بالترتيب؛ هذا سياق محيط وليس تفسيراً مستقلاً بديلاً للآية المختارة.',
        ]);
        for (final row in group.rows) {
          lines.add('سجل المصدر ${row.key.reference} — ${row.book.author}');
          lines.add(
            row.status == TafsirStatus.emptyMarkup
                ? 'حالة المصدر: لا يوجد نص مستقل.'
                : 'حالة المصدر: نص المصدر.',
          );
          lines.addAll(row.displayText.split('\n'));
        }
        lines.add(
          'نهاية السياق ${entry.key.surah}:${group.fromAyah}–${group.toAyah}',
        );
      }
    }
    return Scaffold(
      backgroundColor: widget.sheet
          ? Colors.white
          : Theme.of(context).colorScheme.surface,
      body: SafeArea(
        child: Scrollbar(
          controller: _scroll,
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.all(20),
            itemCount: lines.isEmpty ? 2 : lines.length + 2,
            itemBuilder: (context, index) {
              if (index == 0) return _header();
              if (lines.isEmpty) {
                if (_session.contentError != null) {
                  return Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Semantics(
                        liveRegion: true,
                        child: Text(_errorMessage(_session.contentError)),
                      ),
                      TextButton(
                        onPressed: _session.reload,
                        child: const Text('إعادة المحاولة'),
                      ),
                    ],
                  );
                }
                if (_session.preferenceError != null && _session.book == null) {
                  return const SizedBox.shrink();
                }
                return const Center(
                  child: CircularProgressIndicator(
                    semanticsLabel: 'جارٍ فتح التفسير المحلي',
                  ),
                );
              }
              if (index == lines.length + 1) {
                return Padding(
                  padding: const EdgeInsets.only(top: 24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Text('نهاية تفسير الآية ${widget.ayah.reference}'),
                      _controls(),
                    ],
                  ),
                );
              }
              return Text(
                lines[index - 1],
                key: ValueKey('tafsir-line-${index - 1}'),
                textDirection: TextDirection.rtl,
                style: const TextStyle(fontSize: 22, height: 1.8),
              );
            },
          ),
        ),
      ),
    );
  }
}

String _personalError(PersonalException error) => switch (error.reason) {
  PersonalFailure.storage => 'تعذّر الوصول إلى التخزين المحلي.',
  PersonalFailure.unsupportedVersion => 'البيانات الشخصية من إصدار أحدث.',
  PersonalFailure.invalidData => 'الاختيار المحفوظ غير صالح.',
  PersonalFailure.unavailable => 'خدمة التخزين المحلي غير متاحة.',
};

String _errorMessage(Object? error) {
  final reason = error is TafsirException
      ? error.reason
      : TafsirFailure.unavailable;
  return switch (reason) {
    TafsirFailure.invalidBook => 'اختيار المفسر غير صالح. أعد فتح التفسير.',
    TafsirFailure.invalidReference =>
      'مرجع الآية غير صالح. عد إلى القراءة واختر الآية.',
    TafsirFailure.missingAsset => 'ملف التفسير المحلي غير متاح.',
    TafsirFailure.storage =>
      'تعذّر تجهيز التفسير في مساحة التخزين المحلية. أعد المحاولة.',
    TafsirFailure.missingEntry =>
      'لم يُعثر على تفسير لهذه الآية في الحزمة المحلية.',
    TafsirFailure.corruptPack ||
    TafsirFailure.invalidContent ||
    TafsirFailure.invalidSchema =>
      'تعذّر فتح التفسير: المحتوى المحلي غير صالح.',
    TafsirFailure.unavailable => 'تعذّر فتح التفسير المحلي. أعد المحاولة.',
  };
}

class TafsirSourceView extends StatefulWidget {
  const TafsirSourceView({super.key, this.bundle});
  final AssetBundle? bundle;
  @override
  State<TafsirSourceView> createState() => _TafsirSourceViewState();
}

class _TafsirSourceViewState extends State<TafsirSourceView> {
  late Future<List<TafsirNotice>> _notices;
  @override
  void initState() {
    super.initState();
    _reload();
  }

  void _reload() {
    _notices = loadTafsirNotices(widget.bundle ?? rootBundle);
    _notices.ignore();
  }

  @override
  Widget build(BuildContext context) => _TafsirProse(child: _content(context));

  Widget _content(BuildContext context) => Scaffold(
    backgroundColor: Theme.of(context).colorScheme.surface,
    body: SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: TextButton.icon(
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.arrow_back),
                label: const Text('العودة إلى التفسير'),
              ),
            ),
            Semantics(
              header: true,
              child: Text('المصدر والترخيص', style: TextStyle(fontSize: 24)),
            ),
            const SizedBox(height: 16),
            const Text(
              'مركز تفسير للدراسات القرآنية — tafsir.net\n'
              'تفسير القرآن العظيم — ابن كثير\n'
              'جامع البيان عن تأويل آي القرآن — الطبري\n'
              'تيسير الكريم الرحمن في تفسير كلام المنان — السعدي\n'
              'مصدر عربي مستقل عن محتوى Quranly، متاح دون اتصال.\n'
              'حُفظ نص التفسير كما ورد، مع المقدمات والحواشي والإحالات. '
              'تنسيق العرض فقط منفصل عن النص الأصلي.\n'
              'لم يحدد الموزع الطبعة أو المحقق أو الناشر أو سنة النشر. '
              'تغطية الآيات لا تثبت استقلالاً اكتمال طبعة مطبوعة أو دقتها.\n'
              'يعلن الموزع CC BY 4.0، بينما يشترط إشعار المصدر إذناً لإعادة '
              'التوزيع التجاري. أُبقي الإشعاران، والتعارض غير محسوم.\n'
              'فيما يلي الإشعارات الأصلية كما وردت عند إعداد الحزمة:',
              style: TextStyle(fontSize: 18, height: 1.6),
            ),
            FutureBuilder<List<TafsirNotice>>(
              future: _notices,
              builder: (context, snapshot) {
                if (snapshot.hasError) {
                  return Column(
                    children: [
                      Text(_errorMessage(snapshot.error)),
                      TextButton(
                        onPressed: () => setState(_reload),
                        child: const Text('إعادة المحاولة'),
                      ),
                    ],
                  );
                }
                if (!snapshot.hasData) {
                  return const CircularProgressIndicator(
                    semanticsLabel: 'جارٍ فتح إشعارات المصدر',
                  );
                }
                return Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    for (final notice in snapshot.data!) ...[
                      const SizedBox(height: 24),
                      Semantics(
                        header: true,
                        child: Text(
                          notice.title,
                          style: const TextStyle(fontSize: 22),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        notice.text,
                        // Supplied English/bilingual documents keep LTR flow;
                        // surrounding Arabic headings and summary remain RTL.
                        textDirection: TextDirection.ltr,
                        style: const TextStyle(fontSize: 18, height: 1.6),
                      ),
                    ],
                  ],
                );
              },
            ),
          ],
        ),
      ),
    ),
  );
}
