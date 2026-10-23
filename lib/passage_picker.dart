import 'dart:math' as math;
import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';
import 'content.dart';
import 'reader_metadata.dart';

// Observed chapter and verse sheets. Juz/audio bodies are not recovered; they
// have no fabricated data or action. See docs/issue-30/reference-spec.md.
const pickerSurface = Color(0xFFFAF7FF);
const pickerRow = Color(0xFFEDEBF2);
const pickerSelected = Color(0xFFF0EAFF);
const pickerOutline = Color(0xFF9E6AFF);
const pickerPurple = Color(0xFF6945B6);

Future<AyahKey?> pickPassage(
  BuildContext context, {
  required QuranCatalog catalog,
  required ReaderMetadata metadata,
  required AyahKey current,
  bool verses = false,
}) => showModalBottomSheet<AyahKey>(
  context: context,
  isScrollControlled: true,
  useSafeArea: true,
  backgroundColor: pickerSurface,
  barrierColor: Colors.black54,
  showDragHandle: false,
  shape: const RoundedRectangleBorder(
    borderRadius: BorderRadius.vertical(top: Radius.circular(18)),
  ),
  clipBehavior: Clip.antiAlias,
  builder: (_) => PassagePicker(
    catalog: catalog,
    metadata: metadata,
    current: current,
    verses: verses,
  ),
);

class PassagePicker extends StatefulWidget {
  const PassagePicker({
    super.key,
    required this.catalog,
    required this.metadata,
    required this.current,
    this.verses = false,
  });
  final QuranCatalog catalog;
  final ReaderMetadata metadata;
  final AyahKey current;
  final bool verses;
  @override
  State<PassagePicker> createState() => _PassagePickerState();
}

class _PassagePickerState extends State<PassagePicker> {
  final _search = TextEditingController();
  final _focus = FocusNode();
  late final ScrollController _scroll;
  bool _editing = false;
  static const _margin = 52 / 3;

  @override
  void initState() {
    super.initState();
    _scroll = ScrollController();
    _focus.addListener(_focusChanged);
    // Chapters start at the current chapter; verses start at1 in retained states.
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || widget.verses || !_scroll.hasClients) return;
      final scale = MediaQuery.textScalerOf(context).scale(1);
      _scroll.jumpTo(
        math.min(
          (widget.current.surah - 1) * (72 * math.max(1, scale) + 38 / 3),
          _scroll.position.maxScrollExtent,
        ),
      );
    });
  }

  void _focusChanged() {
    if (_focus.hasFocus && !_editing) setState(() => _editing = true);
  }

  @override
  void dispose() {
    _focus.removeListener(_focusChanged);
    _focus.dispose();
    _search.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _filter() {
    setState(() {});
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  void _cancelSearch() {
    _focus.unfocus();
    _search.clear();
    setState(() => _editing = false);
    if (_scroll.hasClients) _scroll.jumpTo(0);
  }

  Widget _searchBox() => Padding(
    padding: EdgeInsets.fromLTRB(
      _margin,
      32 / 3,
      _margin,
      widget.verses ? 17 : 20,
    ),
    child: Row(
      children: [
        Expanded(
          child: TextField(
            controller: _search,
            focusNode: _focus,
            onChanged: (_) => _filter(),
            textDirection: TextDirection.ltr,
            textInputAction: TextInputAction.search,
            onSubmitted: (_) => _focus.unfocus(),
            style: const TextStyle(fontSize: 18, color: Color(0xFF0D0D0D)),
            decoration: InputDecoration(
              hintText: 'Search',
              labelText: 'Search',
              floatingLabelBehavior: FloatingLabelBehavior.never,
              hintStyle: const TextStyle(color: Color(0xFF858585)),
              labelStyle: const TextStyle(color: Color(0xFF858585)),
              filled: _editing,
              fillColor: const Color(0xFFF0EDF5),
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 16,
                vertical: 10,
              ),
              prefixIconConstraints: const BoxConstraints(
                minWidth: 32,
                minHeight: 48,
              ),
              prefixIcon: SizedBox(
                width: 32,
                child: Center(
                  child: Transform.translate(
                    offset: const Offset(7 / 3, 0),
                    child: SvgPicture.asset(
                      '.local/reader/search.svg',
                      width: 20,
                      height: 20,
                      colorFilter: ColorFilter.mode(
                        widget.verses && !_editing
                            ? const Color(0xFF858585)
                            : const Color(0xFF0D0D0D),
                        BlendMode.srcIn,
                      ),
                      excludeFromSemantics: true,
                    ),
                  ),
                ),
              ),
              suffixIcon: _search.text.isEmpty
                  ? null
                  : IconButton(
                      tooltip: 'Clear search',
                      iconSize: 20,
                      color: const Color(0xFF858585),
                      icon: const Icon(Icons.close),
                      onPressed: () {
                        _search.clear();
                        _filter();
                      },
                    ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(18),
                borderSide: const BorderSide(color: Color(0xFFADADAD)),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(18),
                borderSide: const BorderSide(color: Color(0xFFADADAD)),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(18),
                borderSide: const BorderSide(color: Color(0xFF858585)),
              ),
            ),
          ),
        ),
        if (widget.verses && _editing)
          TextButton(
            onPressed: _cancelSearch,
            style: TextButton.styleFrom(
              foregroundColor: const Color(0xFF0D0D0D),
            ),
            child: const Text('Cancel', style: TextStyle(fontSize: 18)),
          ),
      ],
    ),
  );

  Widget _chapters() {
    final query = _digits(_search.text.trim().toLowerCase());
    final chapters = widget.catalog.surahs.where((s) {
      final key = AyahKey(s.number, 1);
      return '${s.number}. ${widget.metadata.latinName(key)} '
              '${widget.metadata.englishName(key)} ${s.name}'
          .toLowerCase()
          .contains(query);
    }).toList();
    final scale = math.max(1.0, MediaQuery.textScalerOf(context).scale(1));
    return ListView.separated(
      controller: _scroll,
      padding: const EdgeInsets.fromLTRB(_margin, 0, _margin, 16),
      itemCount: chapters.length,
      separatorBuilder: (_, _) => const SizedBox(height: 38 / 3),
      itemBuilder: (context, index) {
        final surah = chapters[index];
        final key = AyahKey(surah.number, 1);
        final selected = surah.number == widget.current.surah;
        return Semantics(
          button: true,
          selected: selected,
          excludeSemantics: true,
          label:
              'فتح ${surah.name}، ${surah.ayahCount} آية، السورة ${surah.number}',
          onTap: () => Navigator.pop(context, key),
          child: Material(
            color: selected ? pickerSelected : pickerRow,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(18),
              side: BorderSide(
                color: selected ? pickerOutline : Colors.transparent,
                width: 2,
              ),
            ),
            child: InkWell(
              borderRadius: BorderRadius.circular(18),
              onTap: () => Navigator.pop(context, key),
              child: ConstrainedBox(
                constraints: BoxConstraints(minHeight: 72 * scale),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 16,
                    vertical: 12,
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '${surah.number}. ${widget.metadata.latinName(key)}',
                              style: TextStyle(
                                fontSize: 18,
                                height: 1.2,
                                fontWeight: FontWeight.w600,
                                color: selected
                                    ? pickerOutline
                                    : const Color(0xFF0D0D0D),
                              ),
                            ),
                            Text(
                              _chapterSubtitle(
                                widget.metadata.englishName(key),
                              ),
                              style: TextStyle(
                                fontSize: 15,
                                height: 1.2,
                                color: selected
                                    ? pickerPurple
                                    : const Color(0xFF858585),
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 8),
                      // Counts wrap on compact/large text; never replace labels
                      // with an invented downloaded state.
                      Flexible(
                        fit: FlexFit.tight,
                        child: Text(
                          '${surah.ayahCount} Verses',
                          textAlign: TextAlign.right,
                          style: TextStyle(
                            fontSize: 15,
                            color: selected
                                ? pickerPurple
                                : const Color(0xFF858585),
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      SvgPicture.asset(
                        '.local/reader/download.svg',
                        width: 24,
                        height: 24,
                        excludeFromSemantics: true,
                        colorFilter: const ColorFilter.mode(
                          pickerPurple,
                          BlendMode.srcIn,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  Widget _verses() {
    final query = _digits(_search.text.trim());
    final numbers = List.generate(
      widget.catalog.surah(widget.current).ayahCount,
      (i) => i + 1,
    ).where((n) => '$n'.contains(query)).toList();
    return LayoutBuilder(
      builder: (context, bounds) {
        final scale = MediaQuery.textScalerOf(context).scale(1);
        // Five columns in the observed state; fewer for large text to preserve
        // readable three-digit labels and at least48dp touch targets.
        final columns = math.min(
          5,
          math.max(
            1,
            ((bounds.maxWidth - 2 * _margin + 9) / math.max(57, 57 * scale))
                .floor(),
          ),
        );
        return GridView.builder(
          controller: _scroll,
          padding: const EdgeInsets.fromLTRB(_margin, 0, _margin, 16),
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            crossAxisSpacing: 9,
            mainAxisSpacing: 9,
          ),
          itemCount: numbers.length,
          itemBuilder: (context, index) {
            final number = numbers[index];
            final selected = number == widget.current.ayah;
            return Semantics(
              selected: selected,
              button: true,
              excludeSemantics: true,
              label: 'Verse $number',
              onTap: () =>
                  Navigator.pop(context, AyahKey(widget.current.surah, number)),
              child: Material(
                color: selected ? pickerSelected : pickerRow,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(18),
                  side: BorderSide(
                    color: selected ? pickerOutline : Colors.transparent,
                    width: 2,
                  ),
                ),
                child: InkWell(
                  borderRadius: BorderRadius.circular(18),
                  onTap: () => Navigator.pop(
                    context,
                    AyahKey(widget.current.surah, number),
                  ),
                  child: Center(
                    child: Text(
                      '$number',
                      style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w600,
                        color: selected
                            ? pickerPurple
                            : const Color(0xFF0D0D0D),
                      ),
                    ),
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) => Directionality(
    textDirection: TextDirection.ltr,
    child: Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SizedBox(
        height: math.max(
          0,
          MediaQuery.sizeOf(context).height * (widget.verses ? .818 : .904) -
              MediaQuery.viewInsetsOf(context).bottom,
        ),
        child: LayoutBuilder(
          builder: (context, bounds) {
            final minimumHeight =
                220.0 *
                math.max(1.0, MediaQuery.textScalerOf(context).scale(1));
            final content = ColoredBox(
              color: pickerSurface,
              child: Column(
                children: [
                  Container(
                    margin: const EdgeInsets.only(top: 10, bottom: 10),
                    width: 39,
                    height: 4,
                    decoration: BoxDecoration(
                      color: const Color(0xFFE2DFE9),
                      borderRadius: BorderRadius.circular(4),
                    ),
                  ),
                  if (widget.verses)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: 1.25),
                      child: Text(
                        'Select Verse',
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    )
                  else
                    Padding(
                      padding: const EdgeInsets.symmetric(horizontal: _margin),
                      child: Row(
                        children: [
                          Expanded(
                            child: TextButton(
                              onPressed: null,
                              style: TextButton.styleFrom(
                                minimumSize: const Size(48, 28),
                                padding: EdgeInsets.zero,
                                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                              ),
                              child: const Text(
                                'Juz',
                                style: TextStyle(
                                  fontSize: 20,
                                  color: Color(0xFF0D0D0D),
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                            ),
                          ),
                          Expanded(
                            child: Semantics(
                              selected: true,
                              child: Container(
                                decoration: BoxDecoration(
                                  color: pickerSelected,
                                  borderRadius: BorderRadius.circular(30),
                                ),
                                constraints: const BoxConstraints(
                                  minHeight: 28,
                                ),
                                alignment: Alignment.center,
                                child: const Text(
                                  'Chapter',
                                  style: TextStyle(
                                    fontSize: 20,
                                    color: pickerPurple,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  _searchBox(),
                  Expanded(child: widget.verses ? _verses() : _chapters()),
                  SizedBox(height: MediaQuery.paddingOf(context).bottom),
                ],
              ),
            );
            if (bounds.maxHeight >= minimumHeight) return content;
            // At large text with the IME, scroll the header and results together
            // rather than overflow or conceal the field/selection behind it.
            return SingleChildScrollView(
              child: SizedBox(height: minimumHeight, child: content),
            );
          },
        ),
      ),
    ),
  );
}

// Selector query representation only. Never applied to religious source text.
String _digits(String value) => String.fromCharCodes(
  value.runes.map(
    (r) => r >= 0x660 && r <= 0x669
        ? r - 0x660 + 0x30
        : r >= 0x6f0 && r <= 0x6f9
        ? r - 0x6f0 + 0x30
        : r,
  ),
);

// Presentation case observed in chapter rows; raw metadata is unchanged.
String _chapterSubtitle(String raw) => raw
    .toLowerCase()
    .split(' ')
    .map(
      (word) => word.isEmpty ? word : word[0].toUpperCase() + word.substring(1),
    )
    .join(' ');
