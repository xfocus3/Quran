"""Hosted reader construction checks. Run as python3 .ci/reader.py before TalkBack.

Only the controller runs this against an installed candidate and installed QA
probe. Sibling device_ui/device_navigation are the public CI helpers. No Android
SDK, Pillow, host paths or original captures are needed. Outputs are private.
"""
import ast
import gzip
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import sys
import time
import traceback
import zlib

OUT = Path('.ci/out/device/reader')
PACKAGE = 'com.xfocus.quranly.local'
AUTHORS = [('ibn_kathir', 'ابن كثير'), ('al_tabari', 'الطبري'), ('al_saadi', 'السعدي')]
BOOK_TITLES = {'ibn_kathir': 'تفسير القرآن العظيم', 'al_tabari': 'جامع البيان عن تأويل آي القرآن',
               'al_saadi': 'تيسير الكريم الرحمن في تفسير كلام المنان'}
SETTINGS = [('system', k) for k in ('font_scale', 'user_rotation', 'accelerometer_rotation')]
SCROLL_STRIDE_CAP_PX = 900
REQUIRED = (
    'offline-startup', 'three-author-27:59-source-return', 'seven-tabari-contexts',
    'boundaries', 'clipboard-2:281', 'clipboard-2:282', 'share-27:59',
    'share-27:59-repeat', 'share-2:282', 'long-export-raster-complete',
    'background-location', 'force-stop-relaunch-location',
    'portrait-2x-controls', 'landscape-2x-controls', 'settings-restored',
)


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def metadata_value(raw):
    """Interpret one balanced Android directional envelope, only for metadata.

    No stripping, case folding, substring or general Unicode normalization.
    In particular embedded controls and malformed/nested envelopes stay unequal.
    """
    pairs = {'\u202a': '\u202c', '\u202b': '\u202c', '\u2066': '\u2069',
             '\u2067': '\u2069', '\u2068': '\u2069'}
    if len(raw) >= 2 and pairs.get(raw[0]) == raw[-1]:
        return raw[1:-1]
    return raw


def provenance(index, label, start, end):
    return {'node_index': index, 'node_label_sha256': digest(label.encode()),
            'start': start, 'end': end, 'offset_unit': 'unicode-code-points',
            'raw_value': label[start:end]}


def tafsir_header(rows, book, key, reference, suffix=()):
    """Exact ordered book/reference/key in standalone or composite header nodes.

    Accept only nodes wholly composed of contiguous expected metadata lines.
    A matching fragment in prose, another book, a stale key or extra suffix
    cannot authenticate a header. Caller separately verifies actual author CLICK.
    """
    expected = [BOOK_TITLES[book], reference, 'تفسير الآية ' + key]
    found = []
    for index, raw in rows:
        lines = raw.split('\n')  # Metadata only; never split notice bodies here.
        # The empty-source live-region is an explicitly owned UI state, not
        # source prose. It may join the header only on the seven context routes.
        if suffix and lines[-len(suffix):] == list(suffix):
            lines = lines[:-len(suffix)]
        values = [metadata_value(line) for line in lines]
        starts = [i for i in range(3) if values == expected[i:i + len(values)]]
        if len(starts) != 1:
            continue
        offset = 0
        for i, line in enumerate(lines):
            found.append((starts[0] + i, provenance(index, raw, offset, offset + len(line))))
            offset += len(line) + 1
    if [i for i, _ in found] != [0, 1, 2]:
        return None
    return [match for _, match in found]


class ScrollProgress:
    """Stop after two unchanged transitions; a bound is failure, never success.

    Merged scroll labels can retain bounds while their pixels move. On repeated
    semantics, lazily establish and compare an actual raster fingerprint before
    declaring a bound. No screenshots are needed for changing semantic frames.
    """
    def __init__(self):
        self.previous = None
        self.unchanged = 0
        self.raster = None

    def observe(self, state, raster=None):
        if state == self.previous:
            if raster is None:
                self.unchanged += 1
            else:
                current = raster()
                self.unchanged = self.unchanged + 1 if current == self.raster else 0
                self.raster = current
        else:
            self.unchanged = 0
            self.raster = None
        self.previous = state
        require(self.unchanged < 2, 'Required UI target unreachable: unchanged scroll state/bounds')


def raw_atoms(raw, allowed, ltr=False):
    """Parse a whole semantic label using exact producer-owned text atoms.

    LF is a *between-widget* separator, not a source splitter. A whole notice
    (including its internal CR/LF, BOM and marks) is one indivisible atom. For
    TextDirection.ltr notices the literal Android LRE/PDF envelope is an alternate
    transport encoding; the source range/hash excludes that external framing.
    Never strip or normalize any character inside a source value. Unknown
    prefixes/suffixes invalidate the whole node, including prefix-only bodies.
    """
    variants = [(text, text, 0) for text in allowed]
    if ltr:
        variants += [('\u202a' + text + '\u202c', text, 1) for text in allowed]
    variants.sort(key=lambda row: len(row[0]), reverse=True)
    matches, offset = [], 0
    while offset < len(raw):
        match = next(((encoded, text, envelope) for encoded, text, envelope in variants
                      if raw.startswith(encoded, offset) and
                      (offset + len(encoded) == len(raw) or raw[offset + len(encoded)] == '\n')), None)
        if match is None:
            return []
        encoded, text, envelope = match
        matches.append((text, offset + envelope, offset + envelope + len(text)))
        offset += len(encoded)
        if offset < len(raw):
            offset += 1
            if offset == len(raw):  # Unowned trailing separator is not source.
                return []
    return matches


def expected_tafsir_display(raw):
    """Independent literal oracle shared with the all-row JVM formatter test.

    These are the retained source's literal tokens, not an HTML parser. Preserve
    BOMs, marks, footnotes, spaces and unknown syntax. TafsirView splits only LF.
    """
    expected = raw.replace('\r\n', '\n').replace('\r', '\n')
    for token in ('<br>', '<p>', '</p>', '</div>'):
        expected = expected.replace(token, '\n')
    return expected.replace('&nbsp;', '\u00a0')


class TafsirExpectations:
    """Read authenticated prepared inputs; never trust candidate channel prose.

    The pack pin belongs to the three-book content contract. Notice order, titles and pins
    belong to loadTafsirNotices; read its fixed declaration, failing closed if
    that source format changes. No private corpus is embedded in this harness.
    """
    # Source-format line identities from the pinned pack. Each bounded prefix
    # includes commentary beyond the source's Quran quote/heading. In particular
    # Saadi 2:282 lines 0/1 are heading/ayah; Tabari 2:282 line 2 is
    # another heading. Ibn 27:59 line 1 is blank; commentary starts at 2.
    SAMPLES = {
        ('ibn_kathir', '27:59'): (0, 2), ('al_tabari', '27:59'): (1, 2),
        ('al_saadi', '27:59'): (0, 1),
        ('ibn_kathir', '2:282'): (0, 2), ('al_tabari', '2:282'): (0, 2, 3),
        ('al_saadi', '2:282'): (0, 1, 2),
    }

    def __init__(self, root=Path('.'), handoff=Path('.local/handoff')):
        contract = json.loads((root / 'docs/phase-4/content-contract.json').read_text())
        self.pack = (handoff / 'app/arabic-three-tafsirs.sqlite').resolve()
        with self.pack.open('rb') as stream:
            self.pack_sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        require(self.pack_sha256 == contract['pack_sha256'], 'Unauthenticated tafsir expectation pack')
        owner = (root / 'lib/tafsir.dart').read_bytes()
        declaration = owner.decode().split('Future<List<TafsirNotice>> loadTafsirNotices(', 1)[1]
        declaration = declaration.split('const files = {', 1)[1].split('};', 1)[0]
        pattern = r"'([^']+\.txt)':\s*\(\s*'([^']+)',\s*'([a-f0-9]{64})',\s*\),"
        files = re.findall(pattern, declaration)
        require(not re.sub(pattern, '', declaration).strip() and len(files) == 4
                and len({f[0] for f in files}) == 4 and all(Path(f[0]).name == f[0] for f in files),
                'Notice owner declaration changed; update the expectation boundary')
        self.notices = []
        for filename, title, pinned in files:
            data = (handoff / 'tafsir' / filename).read_bytes()
            require(digest(data) == pinned, 'Unauthenticated source notice: ' + filename)
            self.notices.append({'file': filename, 'title': title, 'text': data.decode('utf-8'), 'sha256': pinned})
        self.notice_owner_sha256 = digest(owner)
        # This exact static summary may precede the four notice pairs in one
        # merged label. Derive it from the unchanged producing source, rather
        # than allowing an arbitrary prefix or duplicating its prose here.
        view = (root / 'lib/tafsir_view.dart').read_text()
        self.notice_view_sha256 = digest((root / 'lib/tafsir_view.dart').read_bytes())
        summary = view.split("const Text(\n              'مركز تفسير", 1)
        require(len(summary) == 2, 'Source summary declaration changed')
        literals = "'مركز تفسير" + summary[1].split('style: TextStyle', 1)[0]
        tokens = re.findall(r"'(?:[^'\\]|\\.)*'", literals)
        require(tokens and not re.sub(r"'(?:[^'\\]|\\.)*'", '', literals).replace(',', '').strip(),
                'Source summary format changed')
        self.source_summary = ''.join(ast.literal_eval(token) for token in tokens)

    def entry(self, book, key):
        s, a = map(int, key.split(':'))
        with sqlite3.connect(self.pack.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
            rows = db.execute('SELECT text,content_status FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah=?',
                              (book, s, a)).fetchall()
        require(len(rows) == 1 and rows[0][1] == 'source_text', 'Expected one source-text tafsir entry')
        raw = rows[0][0]
        return {'raw_sha256': digest(raw.encode()), 'display': expected_tafsir_display(raw)}

    def content(self, book, key, full=True):
        """Select exact source identities for both device and real-pack checks.

        Samples are explicit pinned source indices, never filtered/fallback lines.
        A blank, missing or reordered sample is an invalid expectation, not a
        candidate-content failure. Full traversal retains every nonempty line
        and the endpoint; samples never imply full-entry coverage.
        """
        entry = self.entry(book, key)
        lines = entry['display'].split('\n')
        indices = [i for i, line in enumerate(lines) if line]
        require(indices, 'No expected source prose')
        selected = indices if full else list(self.SAMPLES[(book, key)])
        if not full:
            require(selected and all(type(i) is int and 0 <= i < len(lines) and lines[i].strip()
                                     for i in selected) and selected == sorted(set(selected)),
                    'Expected sample line identities changed: ' + book + ' ' + key)
        expected = [lines[i] for i in selected]
        if full:
            expected.append('نهاية تفسير الآية ' + key)
        require(len(set(expected)) == len(expected), 'Repeated text needs an unambiguous line-identity contract')
        return {'book': book, 'key': key, 'pack_sha256': self.pack_sha256,
                'raw_sha256': entry['raw_sha256'], 'display_sha256': digest(entry['display'].encode()),
                'scope': 'all-nonempty-source-lines' if full else 'sampled-source-lines',
                'source_line_count': len(lines), 'nonempty_line_count': len(indices),
                'verified_line_indices': selected, 'blank_lines_without_semantic_labels': len(lines) - len(indices),
                'expected': expected}


class TextTraversal:
    """Ordered exact raw identities across bounded, overlapping XML frames.

    Blank source lines have no Android text label and are reported separately.
    No whitespace, bidi, mark or source Unicode normalization is permitted here.
    """
    def __init__(self, expected, frame_limit=100, allowed=None, ltr=False):
        require(expected and all(expected), 'Expected nonempty text identities')
        require(len(set(expected)) == len(expected), 'Repeated text needs an unambiguous line-identity contract')
        self.expected = expected
        self.position = self.frames = 0
        self.frame_limit = frame_limit
        self.loading = False
        self.allowed = list(dict.fromkeys(expected if allowed is None else allowed))
        require(all(text in self.allowed for text in expected), 'Expected identity outside source grammar')
        self.ltr = ltr
        self.matches = []

    def observe(self, labels, node_indices=None, state=None):
        self.frames += 1
        require(self.frames <= self.frame_limit, 'Text traversal frame budget exhausted')
        require(not any('تعذّر' in text or 'لم يُعثر' in text or text == 'إعادة المحاولة' for text in labels),
                'Content UI reported an error')
        self.loading = any('جارٍ فتح' in text or 'جارٍ حفظ اختيار المفسر' in text for text in labels)
        if self.loading:
            return False
        identities = {text: i for i, text in enumerate(self.expected)}
        atoms = []
        for index, raw in zip(range(len(labels)) if node_indices is None else node_indices, labels):
            atoms.extend((text, provenance(index, raw, start, end))
                         for text, start, end in raw_atoms(raw, self.allowed, self.ltr))
        visible = [identities[text] for text, _ in atoms if text in identities]
        require(all(a <= b for a, b in zip(visible, visible[1:])), 'Source text order differs in displayed frame')
        for text, match in atoms:
            if text in identities and identities[text] >= self.position:
                require(identities[text] == self.position, 'Displayed source text skipped an expected line')
            if self.position < len(self.expected) and text == self.expected[self.position]:
                self.matches.append({'identity': self.position, 'frame': self.frames, 'state': state,
                                     **{k: v for k, v in match.items() if k != 'raw_value'},
                                     'value_sha256': digest(text.encode())})
                self.position += 1
        return self.position == len(self.expected)

    def finish(self):
        require(not self.loading and self.position == len(self.expected),
                f'Exact source text traversal incomplete: {self.position}/{len(self.expected)} labels')
        return {'exact_labels': len(self.expected), 'frames': self.frames,
                'label_sha256': [digest(text.encode()) for text in self.expected],
                'matches': self.matches}


class RasterTraversal:
    """Both directions of line completeness AND an observed ayah-end state."""
    def __init__(self, line_count, frame_limit=45):
        self.line_count, self.frame_limit = line_count, frame_limit
        self.seen = set()
        self.frames = self.stalled = 0
        self.previous = None
        self.end_observed = False

    def observe(self, matches, state, ayah_end):
        self.frames += 1
        require(self.frames <= self.frame_limit, 'Long raster frame budget exhausted without ayah end')
        self.stalled = self.stalled + 1 if state == self.previous else 0
        self.previous = state
        require(self.stalled < 3, 'Long raster traversal stalled before ayah end')
        self.seen.update(row['line'] for row in matches)
        self.end_observed = ayah_end
        return ayah_end

    def finish(self):
        require(self.end_observed, 'Long raster actual ayah end was never observed')
        require(self.seen == set(range(self.line_count)), 'Full long-export raster coverage incomplete')


def clipboard_value(root):
    fields = [n for n in root.iter('node') if n.get('class') == 'android.widget.EditText']
    require(len(fields) == 1, 'Clipboard probe must expose exactly one text field')
    return fields[0].get('text', '')


def verify_clipboard(actual, canonical, key):
    expected = canonical + '\n' + key
    require(actual == expected, f'Android clipboard differs from canonical Unicode at {key}')
    require(not any(0xe000 <= ord(c) <= 0xf8ff or 0xf0000 <= ord(c) <= 0xffffd or
                    0x100000 <= ord(c) <= 0x10fffd for c in actual), 'Clipboard contains private-use glyphs')
    return {'characters': len(actual), 'utf8_sha256': digest(actual.encode()), 'exact_match': True}


def read_png(data):
    """Decode bounded Android/Flutter RGB(A) PNGs; reject unsupported layouts.

    Pixel rows support an independent full-export vs scrolled-screen ink check,
    not OCR or a claim that the provisional template matches the original.
    """
    require(data[:8] == b'\x89PNG\r\n\x1a\n', 'Invalid PNG signature')
    pos, compressed, size, channels = 8, bytearray(), None, None
    ended = False
    while pos + 12 <= len(data):
        length, kind = struct.unpack('>I4s', data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        require(len(body) == length and pos + length + 12 <= len(data), 'Truncated PNG chunk')
        crc = struct.unpack('>I', data[pos + 8 + length:pos + 12 + length])[0]
        require(zlib.crc32(kind + body) & 0xffffffff == crc, 'PNG CRC mismatch')
        pos += length + 12
        if kind == b'IHDR':
            require(size is None and length == 13, 'Invalid PNG header')
            w, h, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', body)
            require(depth == 8 and color in (2, 6) and compression == filtering == interlace == 0,
                    'Expected noninterlaced 8-bit RGB/RGBA PNG')
            require(0 < w * h <= 32_000_000, 'PNG dimensions exceed native share contract')
            size, channels = (w, h), 3 if color == 2 else 4
        elif kind == b'IDAT':
            compressed.extend(body)
        elif kind == b'IEND':
            ended = True
            break
    require(size is not None and ended and pos == len(data), 'Incomplete PNG')
    w, h = size
    stride = w * channels
    decoder = zlib.decompressobj()
    raw = decoder.decompress(compressed, (stride + 1) * h + 1)
    require(decoder.eof and not decoder.unused_data and len(raw) == (stride + 1) * h,
            'PNG decompressed size mismatch')
    rows, previous = [], bytearray(stride)
    for y in range(h):
        start = y * (stride + 1)
        method = raw[start]
        row = bytearray(raw[start + 1:start + 1 + stride])
        require(method <= 4, 'Invalid PNG row filter')
        if method:
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                up = previous[i]
                corner = previous[i - channels] if i >= channels else 0
                if method == 1:
                    predictor = left
                elif method == 2:
                    predictor = up
                elif method == 3:
                    predictor = (left + up) // 2
                else:
                    p = left + up - corner
                    a, b, c = abs(p - left), abs(p - up), abs(p - corner)
                    predictor = left if a <= b and a <= c else up if b <= c else corner
                row[i] = (row[i] + predictor) & 255
        rows.append(row)
        previous = row
    return w, h, channels, rows


RASTER_LINE_LIMIT = 256


def pixel_bin_weights(pixels, bins):
    """Exact overlap of unit pixel areas with equal normalized grid cells.

    A pixel straddling a cell boundary contributes proportionally to both;
    integer arithmetic defines the overlaps before conversion to a fraction.
    Each row sums to one. Unlike point/floor binning, this represents density
    continuously as raster scale/phase changes, without alignment searches or
    extra smoothing. Total table entries <= pixels + bins (shared edges less).
    """
    return [[(cell, (min((pixel + 1) * bins, (cell + 1) * pixels) -
                     max(pixel * bins, cell * pixels)) / bins)
             for cell in range(pixel * bins // pixels,
                               ((pixel + 1) * bins + pixels - 1) // pixels)]
            for pixel in range(pixels)]


def ink_lines(png, box, gap, clipped=False):
    """64x24 ink-density signatures of complete Quran lines, in source order.

    The existing dark-pixel/alpha predicate and segmentation are retained.
    Integrate each dark pixel's area over the grid; L2 normalization cancels
    the common pixel-area/density factor. Keep horizontal whitespace and line
    order. Bounds come from Android semantics / the candidate card contract.
    This coarse coverage check cannot certify individual marks or source text.

    PNG decode caps pixels at 32M. For P crop pixels, K dark pixels, W width,
    H line height: scan O(P); weights O(W+64+H+24), accumulation bounded by
    O(K+24W+64H+1536) per line, even when upsampling. At most 256 signatures;
    comparison O(256^2 * 1536). No shift/scale search or unbounded refinement.
    """
    w, h, channels, rows = png
    left, top, right, bottom = box
    left, top = max(0, int(math.ceil(left))), max(0, int(math.ceil(top)))
    right, bottom = min(w, int(right)), min(h, int(bottom))
    require(right > left and bottom > top, 'Empty Quran raster bounds')
    ink = []
    for y in range(top, bottom):
        row = rows[y]
        points = [x for x in range(left, right) if max(row[x * channels:x * channels + 3]) < 110
                  and (channels == 3 or row[x * channels + 3] > 200)]
        if points:
            ink.append((y, points))
    groups = []
    for y, points in ink:
        if not groups or y - groups[-1][-1][0] > gap:
            groups.append([])
        groups[-1].append((y, points))
    result = []
    for group in groups:
        y1, y2 = group[0][0], group[-1][0] + 1
        clip_top, clip_bottom = clipped if isinstance(clipped, tuple) else (clipped, clipped)
        if (clip_top and y1 <= top + gap) or (clip_bottom and y2 >= bottom - gap):
            continue
        if y2 - y1 < gap:  # isolated punctuation/noise isn't a complete line
            continue
        require(len(result) < RASTER_LINE_LIMIT, 'Quran raster line budget exceeded')
        signature = [0.] * (64 * 24)
        xweights = pixel_bin_weights(right - left, 64)
        yweights = pixel_bin_weights(y2 - y1, 24)
        for y, points in group:
            for x in points:
                for iy, wy in yweights[y - y1]:
                    for ix, wx in xweights[x - left]:
                        signature[iy * 64 + ix] += wx * wy
        norm = math.sqrt(sum(v * v for v in signature))
        require(norm > 0, 'Empty ink signature')
        result.append({'bounds': [left, y1, right, y2],
                       'signature': [v / norm for v in signature]})
    return result


def line_diagnostics(observed, exported):
    """Numeric comparisons before validation, including every candidate score."""
    require(observed and exported, 'No complete Quran ink lines to compare')
    require(max(len(observed), len(exported)) <= RASTER_LINE_LIMIT, 'Quran raster line budget exceeded')
    diagnostics = []
    for line in observed:
        scores = [sum(a * b for a, b in zip(line['signature'], target['signature']))
                  for target in exported]
        index = max(range(len(scores)), key=scores.__getitem__)
        diagnostics.append({'line': index, 'cosine': scores[index],
                            'screen_bounds': line['bounds'], 'scores': scores})
    return diagnostics


def checked_line_matches(diagnostics):
    require(diagnostics, 'No complete Quran ink lines to compare')
    matches = []
    for row in diagnostics:
        require(row['cosine'] >= .94,
                f"Screen Quran line absent/different in export: best={row['cosine']:.4f}")
        matches.append({'line': row['line'], 'cosine': round(row['cosine'], 5),
                        'screen_bounds': row['screen_bounds']})
    require(all(a['line'] < b['line'] for a, b in zip(matches, matches[1:])),
            'Export Quran line order differs from the scrolled screen')
    return matches


def match_lines(observed, exported):
    return checked_line_matches(line_diagnostics(observed, exported))


class ReaderChecks:
    def __init__(self):
        # No default device discovery or fallback serial, including in helpers.
        serial = os.environ['QURAN_CI_SERIAL']
        require(bool(re.fullmatch(r'emulator-\d+', serial)), 'Expected controller-owned hosted emulator serial')
        self.adb = ['adb', '-s', serial]
        self.d = importlib.import_module('device_ui')
        self.n = importlib.import_module('device_navigation')
        self.d.ADB = self.adb
        self.d.OUT = self.n.OUT = OUT
        self.raw_dump = self.d.dump
        self.helper_hashes = {module: digest(Path(importlib.import_module(module).__file__).read_bytes())
                              for module in ('device_ui', 'device_navigation')}
        self.trace = gzip.open(OUT / 'states.jsonl.gz', 'wt', encoding='utf-8')
        self.state_count = 0
        self.deadline = time.monotonic() + 2400
        self.d.dump = self.dump
        self.d.seek = self.seek
        self.report = {'schema': 1, 'status': 'running', 'source_commit': os.environ['GITHUB_SHA'],
                       'harness_sha256': digest(Path(__file__).read_bytes()),
                       'scope': 'construction', 'finalParityAccepted': False,
                       'finalOnlyGaps': [f'F29-00{i}' for i in range(1, 7)],
                       'helper_sha256': self.helper_hashes,
                       'required_checks': list(REQUIRED), 'checks': [], 'errors': [],
                       'phone_access': False, 'no_recipient_selected': True}
        self.initial = {}

    def save(self):
        self.report['states'] = self.state_count
        temporary = OUT / 'reader-result.tmp'
        temporary.write_text(json.dumps(self.report, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(OUT / 'reader-result.json')

    def passed(self, name, **details):
        require(name in REQUIRED and name not in [c['name'] for c in self.report['checks']],
                'Unexpected/duplicate reader check: ' + name)
        self.report['checks'].append({'name': name, 'status': 'passed', **details})
        self.save()
        print('PASS', name, flush=True)

    def dump(self, name=None):
        import xml.etree.ElementTree as ET
        require(time.monotonic() < self.deadline, 'Reader check exceeded 40 minute budget')
        root = self.raw_dump(name)
        self.state_count += 1
        self.trace.write(json.dumps({'state': self.state_count, 'monotonic': time.monotonic(),
                                     'stage': getattr(self, 'stage', 'unassigned'),
                                     'xml': ET.tostring(root, encoding='unicode')}, ensure_ascii=False) + '\n')
        self.trace.flush()
        return root

    def capture(self, name, png=True):
        root = self.dump(name)
        if png:
            (OUT / (name + '.png')).write_bytes(subprocess.check_output(
                self.adb + ['exec-out', 'screencap', '-p'], timeout=35))
        return root

    def visible_nodes(self, root):
        # A positive node rectangle can still be outside its scroll owner.
        # Intersect every Android ancestor; never count cached offscreen text
        # or swipe through a viewport belonging to an offscreen scroll node.
        parents = {child: parent for parent in root.iter() for child in parent}
        rows = []
        for i, node in enumerate(root.iter('node')):
            l, t, r, b = self.d.bounds(node)
            parent = parents.get(node)
            while parent is not None:
                if parent.tag == 'node':
                    pl, pt, pr, pb = self.d.bounds(parent)
                    l, t, r, b = max(l, pl), max(t, pt), min(r, pr), min(b, pb)
                parent = parents.get(parent)
            if r > l and b > t:
                rows.append((i, node, (l, t, r, b)))
        return rows

    def visible_rows(self, root):
        return [(i, n, self.d.label(n)) for i, n, _ in self.visible_nodes(root) if self.d.label(n)]

    def scroll_raster(self):
        return digest(subprocess.check_output(self.adb + ['exec-out', 'screencap', '-p'], timeout=35))

    def scroll(self, root, up=True, remaining_px=math.inf):
        """One target/content traversal stride in the current scroll viewport.

        Use the source-body traversal's 40% stride (at least 60% overlap),
        capped at 900 physical pixels. Recompute for every frame, including
        reverse returns and rotated/large-text windows; no key-specific steps.
        This is commanded distance, not a measurement of Android displacement.
        Only the final budget-limited gesture may be shorter than that stride.
        """
        scrolls = [(n, box) for _, n, box in self.visible_nodes(root) if n.get('scrollable') == 'true'
                   and box[3] - box[1] > 120]
        require(scrolls, 'No active scroll owner during reader traversal')
        _, (l, t, r, b) = max(scrolls, key=lambda row: (row[1][2] - row[1][0]) * (row[1][3] - row[1][1]))
        distance = int(min(SCROLL_STRIDE_CAP_PX, (b - t) * .4, remaining_px))
        require(distance >= 1, 'Scroll distance budget exhausted')
        middle = (b + t) / 2
        low, high = int(middle + distance / 2), int(middle - distance / 2)
        start, end = (low, high) if up else (high, low)
        self.d.sh('input', 'swipe', (l + r) // 2, start, (l + r) // 2, end, 450)
        time.sleep(.15)
        return {'viewport': [l, t, r, b], 'up': up, 'from_y': start, 'to_y': end,
                'commanded_distance_px': abs(start - end), 'duration_ms': 450}

    def seek_frame(self, query, match, up=True, limit=70):
        # Helper-compatible `limit` now bounds commanded travel in full stride
        # equivalents at 1x, not gesture count. Thus a short landscape viewport
        # does not silently shrink route coverage. Scale the coverage allowance
        # by the read-back font scale squared: both wrapping and line pitch can
        # grow. This is a conservative policy allowance, not a rendered-height
        # prediction (Android's font scaling is nonlinear). Default at 1x:
        # 70 * 900 = 63,000px; existing source-return limit160: 144,000px.
        # Loading has its own deadline and the whole run retains 40 minutes.
        require(limit > 0, 'Expected positive target traversal coverage budget')
        text_scale = getattr(self, 'text_scale', 1.0)
        distance_budget = limit * SCROLL_STRIDE_CAP_PX * max(1, text_scale ** 2)
        travelled = 0
        gestures, progress = [], ScrollProgress()
        loading_deadline = None
        reason = 'commanded scroll distance budget exhausted'
        while True:
            root = self.dump()
            rows = self.visible_rows(root)
            labels = [raw for _, _, raw in rows]
            require(not any(text.startswith(('تعذّر', 'لم يُعثر')) or text == 'إعادة المحاولة'
                            for text in labels), 'Content UI reported an error while seeking ' + query)
            if any('جارٍ فتح' in text or 'جارٍ حفظ اختيار المفسر' in text for text in labels):
                if loading_deadline is None:
                    loading_deadline = time.monotonic() + 15
                require(time.monotonic() < loading_deadline, 'Content UI remained loading while seeking ' + query)
                time.sleep(.2)
                continue
            loading_deadline = None
            result = match(rows)
            if result is not None:
                return result
            state = tuple((self.d.label(n), n.get('bounds'), n.get('scrollable'), n.get('enabled'),
                           n.get('selected'), n.get('clickable')) for n in root.iter('node'))
            try:
                progress.observe(state, self.scroll_raster)
            except AssertionError as error:
                reason = str(error)
                break
            if distance_budget - travelled < 1:
                break
            gesture = self.scroll(root, up, distance_budget - travelled)
            gestures.append(gesture)
            travelled += gesture['commanded_distance_px']
        (OUT / 'unreachable.json').write_text(json.dumps({'query': query, 'reason': reason, 'gestures': gestures,
            'commanded_distance_px': travelled, 'distance_budget_px': distance_budget,
            'text_scale': text_scale,
            'budget_unit': 'physical-pixels-commanded-not-observed-displacement'}))
        raise AssertionError('Required UI target unreachable: ' + query + ': ' + reason)

    def seek(self, query, up=True, exact=False, limit=70):
        # Exact controls retain whole-node authority. Never click a fragment
        # extracted from a composite header or an authenticated prose value.
        def match(rows):
            nodes = [node for _, node, raw in rows if (raw == query if exact else query in raw)]
            # Header/footer may expose the same real control twice. Each still
            # owns its complete exact label and actual bounds/action.
            return nodes[0] if nodes else None
        return self.seek_frame(query, match, up, limit)

    def seek_metadata(self, query, up=True):
        # Read-only metadata lines (context references/endpoints), explicitly
        # scoped by callers. Controls, canonical Quran and source bodies never
        # use this interpretation.
        def match(rows):
            nodes = [node for _, node, raw in rows
                     if query in [metadata_value(line) for line in raw.split('\n')]]
            require(len(nodes) <= 1, 'Ambiguous metadata: ' + query)
            return nodes[0] if nodes else None
        return self.seek_frame(query, match, up=up)

    def header(self, book, key, suffix=()):
        def match(rows):
            result = tafsir_header([(i, raw) for i, _, raw in rows], book, key, self.references[key], suffix)
            if result is None:
                return None
            return [{'state': self.state_count, **{k: v for k, v in row.items() if k != 'raw_value'}}
                    for row in result]
        return self.seek_frame('tafsir header ' + book + ' ' + key, match, up=False)

    def click(self, query, up=True, exact=True, limit=70):
        node = self.seek(query, up=up, exact=exact, limit=limit)
        require(node.get('enabled') == 'true' and node.get('clickable') == 'true',
                'Control lacks an enabled CLICK action: ' + query)
        self.d.tap(node)

    def back(self):
        self.d.sh('input', 'keyevent', 'KEYCODE_BACK')
        time.sleep(.4)

    def reader(self, key, up=False):
        node = self.seek('الآية ' + key + ' ', up=up)
        require(self.d.label(node) == 'الآية ' + key + ' ' + self.canonical[key],
                'Reader key/content differs from canonical ' + key)
        return node

    def jump(self, surah, ayah):
        self.n.jump(surah, ayah)
        return self.reader(f'{surah}:{ayah}')

    def selected(self, author):
        node = self.seek('اختيار تفسير ' + author, up=False, exact=True)
        require(node.get('selected') == 'true', 'Wrong selected author: ' + author)
        require(node.get('enabled') == 'true' and node.get('clickable') == 'true',
                'Selected author lacks enabled CLICK: ' + author)

    def verify_content(self, expected, frame_limit=100, allowed=None, ltr=False):
        traversal = TextTraversal(expected, frame_limit, allowed, ltr)
        progress = ScrollProgress()
        loading_deadline = None
        for _ in range(frame_limit):
            root = self.dump()
            rows = self.visible_rows(root)
            labels = [raw for _, _, raw in rows]
            if traversal.observe(labels, [i for i, _, _ in rows], state=self.state_count):
                return traversal.finish()
            if traversal.loading:
                if loading_deadline is None:
                    loading_deadline = time.monotonic() + 15
                require(time.monotonic() < loading_deadline, 'Content UI remained loading')
                time.sleep(.2)
                continue
            loading_deadline = None
            progress.observe((traversal.position, tuple((self.d.label(n), n.get('bounds'))
                                                       for n in root.iter('node'))), self.scroll_raster)
            if traversal.frames < frame_limit:
                self.scroll(root)
        traversal.finish()  # A budget, loading state or missing label never passes.

    def ready_tafsir(self, book, key, full=True):
        content = self.tafsir.content(book, key, full)
        header = self.header(book, key)
        allowed = [line for line in self.tafsir.entry(book, key)['display'].split('\n') if line]
        allowed.append('نهاية تفسير الآية ' + key)
        observed = self.verify_content(content.pop('expected'), allowed=allowed)
        return {**content, **observed, 'header_matches': header}

    def source_notices(self):
        expected = [text for notice in self.tafsir.notices for text in (notice['title'], notice['text'])]
        observed = self.verify_content(expected, frame_limit=160,
                                       allowed=[self.tafsir.source_summary, 'المصدر والترخيص'] + expected, ltr=True)
        self.capture('source-loaded-' + str(self.state_count), png=False)
        return {'scope': 'all-four-exact-notice-semantic-bodies-in-source-order',
                'owner_sha256': self.tafsir.notice_owner_sha256,
                'view_owner_sha256': self.tafsir.notice_view_sha256,
                'notices': [{k: notice[k] for k in ('file', 'sha256')} for notice in self.tafsir.notices],
                **observed}

    def set_settings(self, scale, rotation):
        actual_scale = None
        for key, value in [('accelerometer_rotation', '0'), ('user_rotation', str(rotation)), ('font_scale', str(scale))]:
            self.d.sh('settings', 'put', 'system', key, value)
            actual = float(self.d.sh('settings', 'get', 'system', key).strip())
            require(actual == float(value),
                    'Settings write did not take effect: ' + key)
            if key == 'font_scale':
                actual_scale = actual
        require(actual_scale is not None and math.isfinite(actual_scale) and actual_scale > 0,
                'Invalid read-back text scale')
        self.text_scale = actual_scale
        time.sleep(.8)

    def verify_offline(self):
        airplane = self.d.sh('settings', 'get', 'global', 'airplane_mode_on').strip()
        wifi = self.d.sh('settings', 'get', 'global', 'wifi_on').strip()
        data = self.d.sh('settings', 'get', 'global', 'mobile_data').strip()
        connectivity = self.d.sh('dumpsys', 'connectivity')
        (OUT / 'connectivity.txt').write_text(connectivity)
        require(airplane == '1' and wifi == '0' and data == '0', 'Controller must provision offline Android')
        require(re.search(r'Active default network:\s*(?:none|null)', connectivity, re.I),
                'Android still has an active default network')
        return {'airplane_mode_on': airplane, 'wifi_on': wifi, 'mobile_data': data}

    def prepare(self):
        api = int(self.d.sh('getprop', 'ro.build.version.sdk').strip())
        require(api in (35, 36), 'Expected hosted API 35/36')
        self.report['api'] = api
        self.report['build_fingerprint'] = self.d.sh('getprop', 'ro.build.fingerprint').strip()
        receipt = json.loads(Path('.ci/out/build-receipt.json').read_text())
        require(receipt['source_commit'] == self.report['source_commit'], 'Build receipt source differs')
        self.report['source_export'] = receipt['source_export']
        self.report['installed_sha256'] = {}
        for filename, package in [('app-x86_64-debug.apk', PACKAGE),
                                  ('app-debug-androidTest.apk', PACKAGE + '.test')]:
            expected = digest((Path('.ci/out/apks') / filename).read_bytes())
            require(expected == receipt['apk_sha256'][filename], 'Build APK receipt differs')
            remote = self.d.sh('pm', 'path', package).strip().removeprefix('package:')
            actual = self.d.sh('sha256sum', remote).split()[0]
            require(actual == expected, 'Installed APK differs from exact candidate')
            self.report['installed_sha256'][package] = actual
        probe = self.d.sh('pm', 'path', 'qa.quranly.probe').strip().removeprefix('package:')
        require(probe.startswith('/'), 'Clipboard probe is not installed')
        self.report['probe_installed_sha256'] = self.d.sh('sha256sum', probe).split()[0]
        require(self.report['probe_installed_sha256'] == digest(Path('.ci/out/probe/probe.apk').read_bytes()),
                'Installed clipboard probe differs from the controller-built probe')
        canonical = Path('.local/handoff/app/quran.json').read_bytes()
        self.canonical = {f"{r['surah']}:{r['ayah']}": r['unicode'] for r in json.loads(canonical)['ayahs']}
        require(len(self.canonical) == 6236, 'Missing canonical Quran identities')
        self.report['canonical_sha256'] = digest(canonical)
        metadata = Path('.local/reader/metadata.json').read_bytes()
        metadata_owner = Path('lib/reader_metadata.dart').read_text()
        pins = re.findall(r"static const _sha256 =\s*'([a-f0-9]{64})';", metadata_owner)
        require(len(pins) == 1 and digest(metadata) == pins[0], 'Unauthenticated chapter metadata')
        chapters = json.loads(metadata)['surahs']
        require(len(chapters) == 114, 'Missing chapter metadata')
        counts = {}
        for key in self.canonical:
            surah = key.split(':')[0]
            counts[surah] = counts.get(surah, 0) + 1
        self.references = {key: chapters[int(key.split(':')[0]) - 1]['english'].upper() + ' ' +
                           key.split(':')[1] + '/' + str(counts[key.split(':')[0]])
                           for key in self.canonical}
        self.report['chapter_metadata_sha256'] = digest(metadata)
        self.tafsir = TafsirExpectations()
        self.report['tafsir_expectation_pack_sha256'] = self.tafsir.pack_sha256
        self.report['notice_expectation_owner_sha256'] = self.tafsir.notice_owner_sha256
        for namespace, key in SETTINGS:
            self.initial[namespace + '/' + key] = self.d.sh('settings', 'get', namespace, key).strip()
        self.report['settings_before'] = dict(self.initial)
        self.save()  # Persist before the first mutation.
        require(self.d.sh('settings', 'get', 'secure', 'accessibility_enabled').strip() == '0',
                'Reader touch checks must run before TalkBack')
        self.set_settings(1.0, 0)
        self.report['offline'] = self.verify_offline()
        self.d.start()
        self.reader('1:1')
        self.capture('startup')
        for name, command in [('display-size', ('wm', 'size')), ('display-density', ('wm', 'density')),
                              ('window', ('dumpsys', 'window')), ('activity', ('dumpsys', 'activity', 'top'))]:
            (OUT / (name + '.txt')).write_text(self.d.sh(*command))
        self.passed('offline-startup', key='1:1')

    def authors(self):
        self.jump(27, 59)
        self.capture('reader-27-59')
        self.click('فتح التفسير')
        results = []
        for book, author in AUTHORS:
            self.click('اختيار تفسير ' + author, up=False)
            self.selected(author)
            content = self.ready_tafsir(book, '27:59')
            self.header(book, '27:59')
            self.capture('tafsir-27-59-' + book)
            self.click('المصدر والترخيص', up=False)
            notices = self.source_notices()
            self.capture('source-' + book, png=False)
            self.click('العودة إلى التفسير', up=False, limit=160)
            self.selected(author)
            returned = self.ready_tafsir(book, '27:59', full=False)
            results.append({'book': book, 'key': '27:59', 'content': content, 'notices': notices,
                            'returned_content': returned, 'selected_after_source_return': True})
        self.back()
        self.reader('27:59')
        self.click('فتح التفسير')
        self.selected('السعدي')
        self.back()
        self.reader('27:59')
        self.passed('three-author-27:59-source-return', authors=results, remembered_on_reopen='al_saadi')

    def contexts(self):
        contract = json.loads(Path('docs/phase-4/content-contract.json').read_text())
        require(len(contract['contexts']) == 7, 'Expected exactly seven registered contexts')
        results = []
        for row in contract['contexts']:
            s, a, first, last = (row[k] for k in ('surah', 'selected', 'from', 'to'))
            key, span = f'{s}:{a}', f'{s}:{first}–{last}'
            self.jump(s, a)
            self.click('فتح التفسير')
            self.click('اختيار تفسير الطبري', up=False)
            self.selected('الطبري')
            empty = 'لا يوجد نص تفسير مستقل لهذه الآية في سجل المصدر المحدد.'
            self.header('al_tabari', key, suffix=(empty,))
            self.seek_metadata(empty)
            self.click('فتح السياق المحيط ' + span)
            self.seek_metadata('السياق المحيط ' + span)
            self.seek_metadata('الآية المختارة ' + key + ' — الطبري')
            self.seek_metadata(f'عنوان المقطع في سجل المصدر {s}:{row["heading"]}')
            self.seek_metadata('سجلات المصدر بالترتيب؛ هذا سياق محيط وليس تفسيراً مستقلاً بديلاً للآية المختارة.')
            for source in row['source_rows']:
                self.seek_metadata(f'سجل المصدر {s}:{source["ayah"]} — الطبري')
            self.seek_metadata('نهاية السياق ' + span)
            self.capture('context-' + key.replace(':', '-'), png=False)
            self.seek_metadata('نهاية تفسير الآية ' + key)
            self.back()
            self.reader(key)
            results.append({'selected': key, 'range': span, 'source_rows': [r['ayah'] for r in row['source_rows']]})
        self.passed('seven-tabari-contexts', contexts=results, full_source_bytes='native instrumentation contract')

    def boundaries_and_clipboard(self):
        self.jump(1, 1)
        require(self.seek('الآية السابقة', exact=True).get('enabled') == 'false', 'First previous must be disabled')
        self.jump(1, 7)
        self.click('الآية التالية')
        self.reader('2:1')
        self.click('الآية السابقة')
        self.reader('1:7')
        self.jump(114, 6)
        require(self.seek('الآية التالية', exact=True).get('enabled') == 'false', 'Final next must be disabled')
        self.passed('boundaries', keys=['1:1', '1:7', '2:1', '114:6'])
        for ayah in (281, 282):
            key = f'2:{ayah}'
            self.d.tap(self.jump(2, ayah))
            self.click('نسخ الآية مع المرجع')
            launched = self.d.sh('am', 'start', '-W', '-n', 'qa.quranly.probe/qa.PasteActivity')
            require('Error' not in launched and 'Exception' not in launched, 'Clipboard probe did not launch')
            root = self.dump()
            buttons = [n for n in root.iter('node') if self.d.label(n).casefold() == 'read android clipboard']
            require(len(buttons) == 1, 'Actual Android clipboard button missing or ambiguous')
            self.d.tap(buttons[0])
            root = self.capture('clipboard-' + str(ayah), png=False)
            details = verify_clipboard(clipboard_value(root), self.canonical[key], key)
            self.back()
            self.reader(key)
            self.passed('clipboard-' + key, **details)

    def exports(self):
        # The directory need not exist before the first actual UI export.
        if 'cache' not in self.d.sh('run-as', PACKAGE, 'ls', '-1').splitlines():
            return set()
        directories = self.d.sh('run-as', PACKAGE, 'ls', '-1', 'cache').splitlines()
        if 'reader-share' not in directories:
            return set()
        names = self.d.sh('run-as', PACKAGE, 'ls', '-1', 'cache/reader-share').splitlines()
        require(all(re.fullmatch(r'verse-\d+-\d+-[A-Za-z0-9-]+\.png', n) for n in names), 'Unexpected share cache member')
        return set(names)

    def wait_for_chooser(self, s, a, name, png=True):
        """Poll current native XML, then retain that exact checked hierarchy.

        Activity history can still mention the previous ChooserActivity while
        the reader is visible. Only the visible native preview with the exact
        requested key/caption establishes readiness. XML dumps pace this bounded
        poll; no fixed settling sleep or second capture/dump is needed.
        """
        import xml.etree.ElementTree as ET
        caption = f'Verse {a}, Surah {s} shared via https://quranly.app !'
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            root = self.dump()
            now = time.monotonic()
            require(now < self.deadline, 'Reader check exceeded 40 minute budget')
            if now >= deadline:
                break
            previews = [n for _, n, _ in self.visible_nodes(root)
                        if n.get('package') == 'com.android.intentresolver'
                        and n.get('resource-id') == 'com.android.intentresolver:id/content_preview_text']
            if len(previews) == 1 and self.d.label(previews[0]) == caption:
                ET.ElementTree(root).write(OUT / (name + '.xml'), encoding='utf-8', xml_declaration=True)
                if png:
                    (OUT / (name + '.png')).write_bytes(subprocess.check_output(
                        self.adb + ['exec-out', 'screencap', '-p'], timeout=35))
                return root
        raise AssertionError('Native image chooser with exact caption/key not visible within 25 seconds')

    def share(self, s, a, repeat=False):
        key = f'{s}:{a}'
        self.jump(s, a)
        before = self.exports()
        share_control = self.seek('مشاركة الآية كصورة', exact=True)
        return_bounds = self.d.bounds(self.reader(key))
        require(share_control.get('enabled') == 'true' and share_control.get('clickable') == 'true',
                'Share control lacks enabled CLICK')
        self.d.tap(share_control)
        name = 'share-' + key.replace(':', '-') + ('-repeat' if repeat else '')
        self.wait_for_chooser(s, a, name + '-chooser', png=not repeat)
        # Diagnostic only; activity history is never a readiness predicate.
        activity = self.d.sh('dumpsys', 'activity', 'top')
        (OUT / (name + '-activity.txt')).write_text(activity)
        after = self.exports()
        added = after - before
        require(len(added) == 1 and before <= after, 'Expected exactly one new cache export')
        filename = added.pop()
        require(filename.startswith(f'verse-{s}-{a}-'), 'Export cache key mismatch')
        png = subprocess.check_output(self.adb + ['exec-out', 'run-as', PACKAGE, 'cat',
                                                  'cache/reader-share/' + filename], timeout=35)
        if not repeat:
            (OUT / (name + '-export.png')).write_bytes(png)
        width, height, _, _ = read_png(png)
        permissions = self.d.sh('dumpsys', 'activity', 'permissions')
        (OUT / (name + '-uri-grants.txt')).write_text(permissions)
        uri = f'content://{PACKAGE}.reader.share_provider/reader-images/{filename}'
        require(uri in permissions, 'Chooser has no URI grant for the selected cache PNG')
        require(8 <= len(png) <= 16 * 1024 * 1024, 'PNG byte size violates native contract')
        self.back()
        require(self.d.bounds(self.reader(key)) == return_bounds, 'Chooser cancellation changed reader scroll location')
        self.capture(name + '-returned', png=False)
        self.passed('share-' + key + ('-repeat' if repeat else ''), key=key, cache_name=filename,
                    bytes=len(png), png_sha256=digest(png), dimensions=[width, height],
                    uri=uri, returned_bounds=return_bounds, cancelled=True, delivered=False)
        return png

    def compare_raster_frame(self, frame, root, screen, exported, box, gap, clipped, timing):
        """Keep one rolling EXACT checked pair before decode/match can fail.

        XML then screencap are sequential OS observations, not an atomic live
        snapshot. We never redump/recapture to manufacture a failure pair.
        Successful first/final selective captures are still saved separately.
        """
        import xml.etree.ElementTree as ET
        xml = ET.tostring(root, encoding='utf-8')
        (OUT / 'long-raster-checked.png').write_bytes(screen)
        (OUT / 'long-raster-checked.xml').write_bytes(xml)
        details = {'frame': frame, 'state': 'captured', 'screen_sha256': digest(screen),
                   'xml_sha256': digest(xml), 'quran_bounds': box, 'gap': gap,
                   'clipped': clipped, 'timing': timing,
                   'atomicity': 'sequential XML then screencap; live changes between them are possible',
                   'method': '64x24 dark-pixel area overlap, L2; cosine >=0.94',
                   'export_bounds': [line['bounds'] for line in exported]}
        path = OUT / 'long-raster-checked.json'
        path.write_text(json.dumps(details, indent=2))
        decoded = read_png(screen)
        visible = ink_lines(decoded, box, gap=gap, clipped=clipped)
        details.update(state='computed-before-validation', dimensions=decoded[:2],
                       lines=line_diagnostics(visible, exported) if visible else [])
        path.write_text(json.dumps(details, indent=2))
        return checked_line_matches(details['lines']) if visible else []

    def long_export(self, data):
        png = read_png(data)
        w, h = png[:2]
        # Current source card: 2x raster, Quran horizontal pad 64/3dp,
        # header top 64/3dp +48dp, prose top18dp; footer48dp+43/3dp,
        # prose bottom14dp. These describe the provisional candidate only.
        exported = ink_lines(png, (128 / 3, (64 / 3 + 48 + 18) * 2,
                                   w - 128 / 3, h - (48 + 43 / 3 + 14) * 2), gap=8)
        require(len(exported) >= 20, 'Long export is missing expected Quran lines')
        self.seek('العودة إلى اختيار القراءة', up=False, exact=True)
        matches, traversal = [], RasterTraversal(len(exported))
        for frame in range(traversal.frame_limit):
            timing = {'xml_requested_monotonic': time.monotonic()}
            root = self.dump(f'long-raster-{frame:02d}')
            timing['xml_returned_monotonic'] = time.monotonic()
            node = self.d.find('الآية 2:282 ', root)
            require(node is not None and self.d.label(node) == 'الآية 2:282 ' + self.canonical['2:282'],
                    'Long raster lost canonical ayah identity')
            box = self.d.bounds(node)
            scrolls = [n for n in root.iter('node') if n.get('scrollable') == 'true']
            require(scrolls, 'Long reader has no scroll owner')
            l, t, r, b = self.d.bounds(max(scrolls, key=lambda n: self.d.bounds(n)[3] - self.d.bounds(n)[1]))
            timing['screen_requested_monotonic'] = time.monotonic()
            screen = subprocess.check_output(self.adb + ['exec-out', 'screencap', '-p'], timeout=35)
            timing['screen_returned_monotonic'] = time.monotonic()
            matched = self.compare_raster_frame(
                frame, root, screen, exported, box,
                gap=round(8 * (box[2] - box[0]) / (w - 256 / 3)),
                clipped=(box[1] <= t + 1, box[3] >= b - 1), timing=timing)
            ayah_end = t < box[3] < b - 1
            if matched:
                matches.append({'frame': frame, 'screen_sha256': digest(screen), 'matches': matched})
                # Selective PNG evidence: first, final; raw XML and metrics for
                # every intermediate state. Avoid dozens of repeated huge PNGs.
                if len(matches) == 1 or ayah_end:
                    (OUT / f'long-raster-{frame:02d}.png').write_bytes(screen)
            terminal = traversal.observe(matched, (digest(screen), tuple(box)), ayah_end)
            (OUT / 'long-raster-progress.json').write_text(json.dumps(
                {'frames': matches, 'matched_lines': sorted(traversal.seen), 'ayah_end_observed': terminal}))
            # Continue to the actual on-screen ayah end even after every export
            # line matched: a PNG cropped before the final line must fail too.
            if terminal:
                break
            self.d.sh('input', 'swipe', (l + r) // 2, int(t + (b - t) * .7),
                      (l + r) // 2, int(t + (b - t) * .35), 500)
            time.sleep(.2)
        details = {'export_line_count': len(exported), 'matched_lines': sorted(traversal.seen), 'frames': matches,
                   'ayah_end_observed': traversal.end_observed,
                   'method': 'complete visible Quran line 64x24 dark-pixel area overlap vs full PNG, cosine >=0.94; no OCR/original-template claim'}
        (OUT / 'long-raster-metrics.json').write_text(json.dumps(details, indent=2))
        traversal.finish()
        self.reader('2:282')
        self.passed('long-export-raster-complete', **details)

    def lifecycle(self):
        self.jump(27, 59)
        node = self.reader('27:59')
        bounds_before = self.d.bounds(node)
        self.d.sh('input', 'keyevent', 'KEYCODE_HOME')
        self.d.start()
        require(self.d.bounds(self.reader('27:59')) == bounds_before, 'Background changed reader scroll location')
        self.report['offline_after_background'] = self.verify_offline()
        self.capture('background-return', png=False)
        self.passed('background-location', key='27:59', bounds=bounds_before)
        self.click('فتح التفسير')
        self.click('اختيار تفسير السعدي', up=False)
        self.selected('السعدي')
        content = self.ready_tafsir('al_saadi', '27:59')
        # A visible source route and return allow the serialized preference write
        # to complete through the real native owner before process termination.
        self.click('المصدر والترخيص', up=False)
        notices = self.source_notices()
        self.click('العودة إلى التفسير', up=False, limit=160)
        self.selected('السعدي')
        returned = self.ready_tafsir('al_saadi', '27:59', full=False)
        self.back()
        self.d.sh('am', 'force-stop', PACKAGE)
        processes = self.d.sh('ps', '-A')
        require(not any(line.split()[-1] == PACKAGE for line in processes.splitlines() if line.split()),
                'Force-stop left candidate process running')
        self.d.start()
        self.reader('1:1')
        self.capture('cold-relaunch', png=False)
        self.click('فتح التفسير')
        self.selected('السعدي')
        self.back()
        self.reader('1:1')
        self.report['offline_after_force_stop'] = self.verify_offline()
        self.passed('force-stop-relaunch-location', before='27:59', actual_after='1:1',
                    contract='in-memory reader; durable resume remains issue #8', persisted_author='al_saadi',
                    before_stop_content=content, notices=notices, source_return_content=returned)

    def access(self, rotation, name):
        self.set_settings(2.0, rotation)
        self.reader('2:282')
        # Assert reachability AND enabled CLICK at actual bounds, then use the
        # critical controls. Later inactive personal/audio/settings producers
        # are not claimed functional by this reader check.
        self.seek('العودة إلى اختيار القراءة', up=False, exact=True)
        self.click('العودة إلى اختيار القراءة', up=False)
        self.click('Start Reading Quran')
        self.reader('2:282')
        root = self.capture(name + '-head')
        width, height, _, _ = read_png((OUT / (name + '-head.png')).read_bytes())
        require(root.get('rotation') == str(rotation), 'Actual Android window rotation differs from requested setting')
        require((width > height) if rotation == 1 else (height > width),
                'Actual captured viewport did not change orientation')
        for label in ('الآية السابقة', 'الآية التالية', 'مشاركة الآية كصورة', 'فتح التفسير'):
            node = self.seek(label, exact=True)
            require(node.get('clickable') == 'true' and node.get('enabled') == 'true', 'Critical control unavailable: ' + label)
        self.click('الآية التالية')
        self.reader('2:283')
        self.click('الآية السابقة')
        self.reader('2:282')
        self.click('فتح التفسير')
        contents = []
        for book, author in AUTHORS:
            self.click('اختيار تفسير ' + author, up=False)
            self.selected(author)
            contents.append(self.ready_tafsir(book, '2:282', full=False))
        self.seek_metadata('نهاية تفسير الآية 2:282')  # Saadi endpoint; prose scope above is sampled.
        self.capture(name + '-tafsir-end')
        self.click('المصدر والترخيص')
        notices = self.source_notices()
        self.click('العودة إلى التفسير', up=False, limit=160)
        self.selected('السعدي')
        returned = self.ready_tafsir('al_saadi', '2:282', full=False)
        self.click('العودة إلى القراءة')
        self.reader('2:282')
        self.capture(name + '-reader-end')
        self.passed(name + '-controls', key='2:282', font_scale=2.0, rotation=rotation,
                    actual_window_rotation=root.get('rotation'), captured_dimensions=[width, height],
                    content=contents, notices=notices, source_return_content=returned,
                    used=['entry-return', 'previous-next', 'bookstand', 'three-authors', 'source-return', 'tafsir-end-return'],
                    share='enabled CLICK reachable; actual chooser tested at normal scale')

    def run(self):
        try:
            self.stage = 'prepare'
            self.prepare()
            self.stage = 'authors'
            self.authors()
            self.stage = 'contexts'
            self.contexts()
            self.stage = 'boundaries-and-clipboard'
            self.boundaries_and_clipboard()
            self.stage = 'share'
            self.share(27, 59)
            self.share(27, 59, repeat=True)
            long_png = self.share(2, 282)
            self.stage = 'long-export'
            self.long_export(long_png)
            self.stage = 'lifecycle'
            self.lifecycle()
            self.stage = 'large-text-jump'
            self.jump(2, 282)
            self.stage = 'portrait-2x'
            self.access(0, 'portrait-2x')
            self.stage = 'landscape-2x'
            self.access(1, 'landscape-2x')
        except BaseException:
            self.report['errors'].append({'stage': 'reader', 'traceback': traceback.format_exc()})
            try:
                self.deadline = time.monotonic() + 70
                self.capture('failure')
                (OUT / 'failure-activity.txt').write_text(self.d.sh('dumpsys', 'activity', 'top'))
            except Exception:
                self.report['errors'].append({'stage': 'failure-capture', 'traceback': traceback.format_exc()})
        finally:
            # Every attempted restoration has an independent readback. Continue
            # other keys after one failure; cleanup failures still fail the run.
            restored = {}
            for setting, value in self.initial.items():
                namespace, key = setting.split('/')
                try:
                    if value == 'null':
                        self.d.sh('settings', 'delete', namespace, key, timeout=15)
                    else:
                        self.d.sh('settings', 'put', namespace, key, value, timeout=15)
                    actual = self.d.sh('settings', 'get', namespace, key, timeout=15).strip()
                    restored[setting] = actual
                    require(actual == value, 'Settings restoration readback differs: ' + setting)
                except Exception:
                    self.report['errors'].append({'stage': 'restore-' + setting, 'traceback': traceback.format_exc()})
            self.report['settings_after'] = restored
            if len(restored) == len(SETTINGS) and restored == self.initial:
                self.passed('settings-restored', actual_readback=restored)
            self.trace.close()
            covered = {c['name'] for c in self.report['checks']}
            self.report['missing_checks'] = sorted(set(REQUIRED) - covered)
            self.report['status'] = 'passed' if not self.report['errors'] and not self.report['missing_checks'] else 'failed'
            self.save()
        return self.report['status'] == 'passed'


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    require(not (OUT / 'reader-result.json').exists(), 'Reader output already exists; refuse stale evidence reuse')
    try:
        return 0 if ReaderChecks().run() else 1
    except BaseException:
        # Even missing serial/helper/probe/setup is a failed required run.
        (OUT / 'reader-result.json').write_text(json.dumps({'schema': 1, 'status': 'failed',
            'scope': 'construction', 'finalParityAccepted': False, 'required_checks': list(REQUIRED),
            'missing_checks': list(REQUIRED), 'error': traceback.format_exc()}, indent=2) + '\n')
        return 1


if __name__ == '__main__':
    sys.exit(main())
