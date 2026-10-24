part of 'main.dart';

class ReaderView extends StatefulWidget {
  const ReaderView({super.key, required this.catalog, required this.metadata});
  final QuranCatalog catalog;
  final ReaderMetadata metadata;
  @override
  State<ReaderView> createState() => _ReaderViewState();
}

class _ReaderViewState extends State<ReaderView> {
  // Calibrated original 1220px / density3. These are presentation minimums;
  // large text and long verses grow into the reader's existing scroll view.
  static const _margin = 52 / 3;
  late final ReaderController _reader = ReaderController(widget.catalog);
  final _scroll = ScrollController();
  bool _entry = false;
  bool _sharing = false;
  final _shareBoundary = GlobalKey();

  @override
  void dispose() {
    _reader.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _open(AyahKey key) {
    _reader.open(key);
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  Future<void> _pickSurah() async {
    final key = await pickPassage(
      context,
      catalog: widget.catalog,
      metadata: widget.metadata,
      current: _reader.current.key,
    );
    if (key != null && mounted) _open(key);
  }

  Future<void> _jump() async {
    final key = await pickPassage(
      context,
      catalog: widget.catalog,
      metadata: widget.metadata,
      current: _reader.current.key,
      verses: true,
    );
    if (key != null && mounted) _open(key);
  }

  Future<void> _share() async {
    if (_sharing) return;
    _sharing = true;
    final ayah = _reader.current;
    try {
      await WidgetsBinding.instance.endOfFrame;
      if (!mounted || _reader.current.key != ayah.key) return;
      final boundary =
          _shareBoundary.currentContext!.findRenderObject()!
              as RenderRepaintBoundary;
      final image = await boundary.toImage(pixelRatio: 2);
      late final ByteData? bytes;
      try {
        bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      } finally {
        image.dispose();
      }
      if (!mounted || bytes == null) return;
      setState(() {});
      await AyahImageShare.share(
        ayah,
        bytes.buffer.asUint8List(bytes.offsetInBytes, bytes.lengthInBytes),
      );
    } on Exception {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(
            content: Text('تعذّرت مشاركة صورة الآية. أعد المحاولة.'),
          ),
        );
      }
    } finally {
      _sharing = false;
      if (mounted) setState(() {});
    }
  }

  Future<void> _tafsir(QuranAyah ayah) => showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    showDragHandle: true,
    backgroundColor: Colors.white,
    barrierColor: Colors.black54,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(12)),
    ),
    clipBehavior: Clip.antiAlias,
    constraints: BoxConstraints(
      maxHeight: MediaQuery.sizeOf(context).height * .8,
    ),
    builder: (_) => TafsirView(
      ayah: ayah.key,
      surahName: widget.catalog.surah(ayah.key).name,
      sheet: true,
      referenceHeading:
          '${widget.metadata.englishName(ayah.key).toUpperCase()} '
          '${ayah.key.ayah}/${widget.catalog.surah(ayah.key).ayahCount}',
    ),
  );

  // Required canonical-copy action remains separate from the observed native
  // image sharing. The original text-tap/long-press copy policy is unknown.
  Future<void> _actions() async {
    final ayah = _reader.selectCurrent();
    final openTafsir = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (_) => _AyahActions(reader: _reader, ayah: ayah),
    );
    _reader.clearSelection();
    if (openTafsir == true && mounted) await _tafsir(ayah);
  }

  Widget _svg(String name, {double size = 24, Color? color}) =>
      SvgPicture.asset(
        '.local/reader/$name.svg',
        width: size,
        height: size,
        excludeFromSemantics: true,
        colorFilter: color == null
            ? null
            : ColorFilter.mode(color, BlendMode.srcIn),
      );

  Widget _icon(String label, Widget icon, {VoidCallback? onPressed}) =>
      IconButton(
        tooltip: label,
        padding: const EdgeInsets.all(7),
        onPressed: onPressed,
        disabledColor: readerInk,
        constraints: const BoxConstraints(minWidth: 48, minHeight: 48),
        icon: icon,
      );

  // Rounded stems from the original subset, not the SDK's Material font.
  // The 25dp paint size follows the retained full glyph; device comparison is
  // pending. Keep the slot/targets independent of paint and button semantics.
  static const _backArrow = IconData(0xf572, fontFamily: 'quranlyReaderIcons');
  static const _forwardArrow = IconData(0xf57a, fontFamily: 'quranlyReaderIcons');

  Widget _arrow(IconData glyph, {required Color color}) => ExcludeSemantics(
    child: SizedBox.square(
      dimension: 28,
      child: Icon(glyph, size: 25, color: color),
    ),
  );

  Widget _previous() => OutlinedButton(
    style: OutlinedButton.styleFrom(
      padding: const EdgeInsets.symmetric(vertical: 10),
      minimumSize: const Size(48, 52),
      foregroundColor: Colors.white,
      disabledForegroundColor: Colors.white54,
      side: const BorderSide(color: Colors.white, width: 1),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
    ),
    onPressed: _reader.previous == null ? null : () => _open(_reader.previous!),
    child: Tooltip(
      message: 'الآية السابقة',
      excludeFromSemantics: true,
      // Merge the name into the button's role, enabled state and tap action.
      child: Semantics(
        label: 'الآية السابقة',
        child: _arrow(
          _backArrow,
          color: _reader.previous == null ? Colors.white54 : Colors.white,
        ),
      ),
    ),
  );

  Widget _next() => FilledButton(
    style: FilledButton.styleFrom(
      padding: const EdgeInsets.symmetric(vertical: 10),
      minimumSize: const Size(48, 52),
      backgroundColor: readerCard,
      foregroundColor: readerInk,
      disabledBackgroundColor: Colors.white24,
      disabledForegroundColor: Colors.white54,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
    ),
    onPressed: _reader.next == null ? null : () => _open(_reader.next!),
    child: Tooltip(
      message: 'الآية التالية',
      excludeFromSemantics: true,
      child: Semantics(
        label: 'الآية التالية',
        child: _arrow(
          _forwardArrow,
          color: _reader.next == null ? Colors.white54 : readerInk,
        ),
      ),
    ),
  );

  Widget _card(QuranAyah ayah) {
    final surah = widget.catalog.surah(ayah.key);
    return Container(
      decoration: BoxDecoration(
        color: readerCard,
        borderRadius: BorderRadius.circular(18),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(32 / 3, 64 / 3, 32 / 3, 0),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 260 / 3,
                  height: 48,
                  child: Align(
                    alignment: Alignment.topCenter,
                    child: Container(
                      height: 116 / 3,
                      decoration: BoxDecoration(
                        borderRadius: BorderRadius.circular(30),
                        border: Border.all(color: const Color(0xFFE3DFE9)),
                      ),
                      child: Row(
                        children: [
                          Expanded(
                            child: _inactiveIcon(
                              'تشغيل التلاوة',
                              const Icon(
                                Icons.play_arrow,
                                color: Color(0xFF9E6AFF),
                                size: 26,
                              ),
                            ),
                          ),
                          Expanded(
                            child: Padding(
                              padding: const EdgeInsets.only(right: 4),
                              child: _inactiveIcon(
                                'تكرار التلاوة',
                                Stack(
                                  alignment: Alignment.center,
                                  children: [
                                    _svg('repeat', size: 28),
                                    const Text(
                                      '1',
                                      style: TextStyle(fontSize: 10, height: 1),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
                Expanded(
                  child: Semantics(
                    button: true,
                    child: InkWell(
                      onTap: _pickSurah,
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(minHeight: 48),
                        child: Column(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Text(
                              '${surah.number}. ${widget.metadata.latinName(ayah.key)}',
                              textAlign: TextAlign.center,
                              style: const TextStyle(
                                fontSize: 18,
                                height: 1.2,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              '${ayah.key.ayah}/${surah.ayahCount}',
                              style: const TextStyle(fontSize: 15, height: 1.2),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
                SizedBox(
                  width: 130 / 3,
                  height: 48,
                  child: Align(
                    alignment: Alignment.topCenter,
                    child: _inactiveIcon(
                      'المفضلة',
                      _svg('heart', size: 20),
                      height: 80 / 3,
                    ),
                  ),
                ),
                SizedBox(
                  width: 32,
                  height: 48,
                  child: Align(
                    alignment: Alignment.topLeft,
                    child: Padding(
                      padding: const EdgeInsets.only(left: 4 / 3),
                      child: SizedBox(
                        width: 20,
                        child: _inactiveIcon(
                          'العلامات المرجعية',
                          _svg('bookmark', size: 20),
                          height: 80 / 3,
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
          ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 346 / 3),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(64 / 3, 18, 64 / 3, 14),
              child: Center(
                child: Tooltip(
                  message: 'إجراءات الآية',
                  child: Semantics(
                    label: 'الآية ${ayah.key.reference} ${ayah.text}',
                    button: true,
                    onTap: _actions,
                    excludeSemantics: true,
                    child: GestureDetector(
                      behavior: HitTestBehavior.opaque,
                      onTap: _actions,
                      onLongPress: _actions,
                      // The retained PNG and word bounds show right-aligned
                      // word runs. Keep source order/combining marks untouched;
                      // the outer semantics/clipboard still own the whole ayah.
                      child: SizedBox(
                        width: double.infinity,
                        child: Wrap(
                          textDirection: TextDirection.rtl,
                          spacing: 16 / 3,
                          runSpacing: 17 / 3,
                          alignment: WrapAlignment.start,
                          children: [
                            for (final word in ayah.text.split(' '))
                              Text(
                                word,
                                textAlign: TextAlign.right,
                                textDirection: TextDirection.rtl,
                                style: const TextStyle(
                                  fontFamily: 'madina2',
                                  fontSize: 31.5,
                                  height: 1.75,
                                  letterSpacing: 0,
                                  color: readerInk,
                                ),
                              ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(29 / 3, 0, 58 / 3, 43 / 3),
            child: Row(
              children: [
                _icon(
                  'مشاركة الآية كصورة',
                  _sharing
                      ? const SizedBox(
                          width: 24,
                          height: 24,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      : Container(
                          width: 100 / 3,
                          height: 100 / 3,
                          decoration: const BoxDecoration(
                            color: Color(0xFFE7DCFF),
                            shape: BoxShape.circle,
                          ),
                          child: Center(
                            child: Image.asset(
                              '.local/reader/share-arrow.png',
                              width: 49 / 3,
                              height: 49 / 3,
                              excludeFromSemantics: true,
                            ),
                          ),
                        ),
                  onPressed: _sharing ? null : _share,
                ),
                const Spacer(),
                _icon(
                  'فتح التفسير',
                  _svg('tafsir', size: 22),
                  onPressed: () => _tafsir(ayah),
                ),
                const SizedBox(width: 14 / 3),
                _icon('الملاحظات الشخصية', _svg('notes', size: 26)),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: _reader,
    builder: (context, _) {
      if (_entry) return _readingEntry();
      final ayah = _reader.current;
      final passage = widget.metadata.context(widget.catalog, ayah.key);
      return _systemBars(
        Directionality(
          textDirection: TextDirection.ltr,
          child: Scaffold(
            bottomNavigationBar: ColoredBox(
              color: readerCard,
              child: SizedBox(height: MediaQuery.viewPaddingOf(context).bottom),
            ),
            body: DecoratedBox(
              decoration: const BoxDecoration(
                image: DecorationImage(
                  image: AssetImage('.local/reader/background.png'),
                  fit: BoxFit.cover,
                ),
              ),
              child: SafeArea(
                bottom: false,
                child: LayoutBuilder(
                  builder: (context, bounds) => SingleChildScrollView(
                    controller: _scroll,
                    padding: const EdgeInsets.fromLTRB(
                      _margin,
                      4,
                      _margin,
                      _margin,
                    ),
                    child: ConstrainedBox(
                      constraints: BoxConstraints(
                        minHeight: (bounds.maxHeight - 4 - _margin).clamp(
                          0,
                          double.infinity,
                        ),
                      ),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              // The short painted pill and the full touch target
                              // have different owners. Do not compress safe insets.
                              _readerHeader(),
                              // Challenge/goal values and rules remain #13+.
                              const SizedBox(height: 136),
                              Container(
                                constraints: const BoxConstraints(
                                  minHeight: 52,
                                ),
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 64 / 3,
                                  vertical: 8,
                                ),
                                decoration: BoxDecoration(
                                  borderRadius: BorderRadius.circular(16),
                                  gradient: const LinearGradient(
                                    colors: [
                                      Color(0xFF60DEB8),
                                      Color(0xFFA4EAD7),
                                    ],
                                  ),
                                ),
                                alignment: Alignment.centerLeft,
                                child: const Text(
                                  'Goal',
                                  style: TextStyle(
                                    fontSize: 20,
                                    height: 1.2,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                              Padding(
                                padding: const EdgeInsets.symmetric(
                                  vertical: 34 / 3,
                                ),
                                child: Text(
                                  'Juz ${passage.juz} : ${passage.remaining} Verses left',
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(
                                    color: Colors.white,
                                    fontWeight: FontWeight.w600,
                                    fontSize: 15,
                                    height: 1.2,
                                  ),
                                ),
                              ),
                              RepaintBoundary(
                                key: _shareBoundary,
                                child: _card(ayah),
                              ),
                            ],
                          ),
                          Padding(
                            padding: const EdgeInsets.only(top: 24),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Expanded(flex: 153, child: _previous()),
                                const SizedBox(width: 52 / 3),
                                Expanded(
                                  flex: 199,
                                  child: FilledButton(
                                    style: FilledButton.styleFrom(
                                      minimumSize: const Size(48, 52),
                                      disabledBackgroundColor: const Color(
                                        0xFF60DEB8,
                                      ),
                                      disabledForegroundColor: readerInk,
                                      padding: const EdgeInsets.symmetric(
                                        vertical: 12,
                                      ),
                                      shape: RoundedRectangleBorder(
                                        borderRadius: BorderRadius.circular(18),
                                      ),
                                    ),
                                    onPressed: null,
                                    child: const Text(
                                      "I'm Done",
                                      textAlign: TextAlign.center,
                                      style: TextStyle(
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ),
                                ),
                                const SizedBox(width: 52 / 3),
                                Expanded(flex: 154, child: _next()),
                              ],
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    },
  );

  Widget _readingEntry() {
    final key = _reader.current.key;
    return _systemBars(
      Directionality(
        textDirection: TextDirection.ltr,
        child: Scaffold(
          backgroundColor: readerCard,
          body: SafeArea(
            child: ListView(
              padding: const EdgeInsets.symmetric(horizontal: _margin),
              children: [
                const Padding(
                  padding: EdgeInsets.only(top: 36, bottom: 112 / 3),
                  child: Text(
                    'Reading',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 20,
                      height: 1.2,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
                const Text(
                  'This is a separate Qur’an — your main daily Quran stays untouched',
                  textAlign: TextAlign.center,
                  style: TextStyle(
                    fontSize: 16,
                    height: 1.25,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 49 / 3),
                _entryRow(
                  widget.metadata.latinName(key),
                  '${widget.metadata.englishName(key).toUpperCase()} | '
                      '${widget.catalog.surah(key).ayahCount} Verses',
                  'السور',
                  _pickSurah,
                ),
                const SizedBox(height: 52 / 3),
                _entryRow(
                  'Start from Verse',
                  '${key.ayah} Verse',
                  'الانتقال إلى آية',
                  _jump,
                ),
                const SizedBox(height: 52 / 3),
                Semantics(
                  button: true,
                  child: Material(
                    color: Colors.transparent,
                    child: InkWell(
                      borderRadius: BorderRadius.circular(18),
                      onTap: () => setState(() => _entry = false),
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(minHeight: 48),
                        child: Align(
                          heightFactor: 1,
                          alignment: Alignment.topCenter,
                          child: Ink(
                            decoration: BoxDecoration(
                              color: readerInk,
                              borderRadius: BorderRadius.circular(18),
                            ),
                            child: ConstrainedBox(
                              constraints: const BoxConstraints(
                                minHeight: 136 / 3,
                              ),
                              child: const Padding(
                                padding: EdgeInsets.symmetric(
                                  horizontal: 16,
                                  vertical: 10,
                                ),
                                child: Center(
                                  child: Text(
                                    'Start Reading Quran',
                                    style: TextStyle(
                                      color: readerCard,
                                      fontSize: 15,
                                      height: 1.2,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _systemBars(Widget child) => AnnotatedRegion<SystemUiOverlayStyle>(
    value: SystemUiOverlayStyle.dark.copyWith(
      statusBarColor: Colors.transparent,
      systemNavigationBarColor: Colors.transparent,
      systemNavigationBarContrastEnforced: false,
    ),
    child: child,
  );

  Widget _inactiveIcon(String label, Widget icon, {double height = 116 / 3}) =>
      Semantics(
        label: label,
        button: true,
        enabled: false,
        excludeSemantics: true,
        child: Tooltip(
          message: label,
          child: SizedBox(
            height: height,
            child: Center(child: icon),
          ),
        ),
      );

  Widget _readerHeader() => Row(
    children: [
      SizedBox(
        width: 54,
        height: 48,
        child: TextButton(
          style: TextButton.styleFrom(
            padding: EdgeInsets.zero,
            foregroundColor: Colors.white,
          ),
          onPressed: () => setState(() => _entry = true),
          // Original pill extends20px beyond the card's left edge. Keep a
          //54×48dp target; size only its painted outline to60×30dp.
          child: Semantics(
            label: 'العودة إلى اختيار القراءة',
            child: Transform.translate(
              offset: const Offset(-11 / 3, 0),
              child: OverflowBox(
                minWidth: 60,
                maxWidth: 60,
                minHeight: 30,
                maxHeight: 30,
                child: Container(
                  decoration: BoxDecoration(
                    border: Border.all(color: readerCard),
                    borderRadius: BorderRadius.circular(30),
                  ),
                  child: Center(
                    child: _arrow(_backArrow, color: Colors.white),
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
      const SizedBox(width: 10),
      Expanded(
        child: Container(
          height: 34,
          decoration: BoxDecoration(
            border: Border.all(color: Colors.white70),
            borderRadius: BorderRadius.circular(30),
          ),
        ),
      ),
      _icon('الإعدادات', _svg('settings', color: Colors.white)),
    ],
  );

  Widget _entryRow(
    String title,
    String subtitle,
    String label,
    VoidCallback action,
  ) => Semantics(
    label: label,
    button: true,
    onTap: action,
    child: Material(
      color: const Color(0xFFEDEBF2),
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        onTap: action,
        borderRadius: BorderRadius.circular(18),
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: 52 / 3,
            vertical: 47 / 3,
          ),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: const TextStyle(
                        fontSize: 20,
                        height: 1.2,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        fontSize: 15,
                        height: 1.2,
                        color: Color(0xFF858585),
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right, size: 28),
            ],
          ),
        ),
      ),
    ),
  );
}
