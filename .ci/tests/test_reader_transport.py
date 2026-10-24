"""Private retained-XML regression plus explicitly synthetic transport contracts.

Raw captures/prose are read only from the optional private mount, never embedded.
This is source verification; no device, original-route or parity verdict follows.
"""
import importlib.util
from contextlib import ExitStack, closing
import io
import gzip
import json
import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import tempfile
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

# Tests have the same depth in .sandcastle/tests and .ci/tests. The harness
# has a different depth; its PATH must never own content/source resolution.
REPO = Path(__file__).resolve().parents[2]
DEFAULT_EVIDENCE_ROOT = Path('/home/agent/hosted-evidence')
PATH = Path(__file__).parents[1] / 'reader.py'
SPEC = importlib.util.spec_from_file_location('reader_transport', PATH)
reader = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reader)


def label(node):
    return node.get('content-desc') or node.get('text', '')


def bounds(node):
    return tuple(map(int, reader.re.findall(r'\d+', node.get('bounds', '[0,0][0,0]'))))


def checks_for_frames(frames):
    """Replace only the OS XML/input boundary; run actual reader public methods."""
    checks = reader.ReaderChecks.__new__(reader.ReaderChecks)
    frames = iter(frames)
    gestures, taps = [], []
    checks.raw_dump = lambda name=None: next(frames)
    checks.d = SimpleNamespace(label=label, bounds=bounds, sh=lambda *args: gestures.append(args),
                               tap=lambda node: taps.append(node))
    checks.trace = io.StringIO()
    checks.state_count = 0
    checks.deadline = time.monotonic() + 60
    checks.references = {'27:59': 'THE ANT 59/93'}
    checks.adb = ['unexecuted-test-boundary']
    return checks, gestures, taps


def failed_api_directories():
    """An explicit fixture selection requires complete API35 *and* API36 input."""
    selected = os.environ.get('QURANLY_FAILED_EVIDENCE_ROOT')
    if selected is not None and not selected.strip():
        raise AssertionError('Incomplete retained evidence fixture: QURANLY_FAILED_EVIDENCE_ROOT is empty')
    root = Path(selected) if selected is not None else DEFAULT_EVIDENCE_ROOT
    directories = [(api, root / f'api-{api}/reader') for api in (35, 36)]
    missing = [str(directory / name) for _, directory in directories
               for name in ('failure.xml', 'states.jsonl.gz') if not (directory / name).is_file()]
    if missing:
        reason = 'Incomplete retained evidence fixture; missing files: ' + ', '.join(missing)
        if selected is not None:
            raise AssertionError(reason)
        raise unittest.SkipTest(reason)
    return directories


def retained_header(directory):
    # Later failures are deep in contexts; use the first retained loaded Ibn
    # header with its selected author action, rather than inventing a frame.
    try:
        root = ET.parse(directory / 'failure.xml').getroot()
        with gzip.open(directory / 'states.jsonl.gz', 'rt') as stream:
            seen = False
            for line in stream:
                candidate = ET.fromstring(json.loads(line)['xml'])
                seen = True
                labels = [label(n) for n in candidate.iter('node')]
                if (any(reader.BOOK_TITLES['ibn_kathir'] in raw and 'تفسير الآية 27:59' in raw for raw in labels)
                        and any(label(n) == 'اختيار تفسير ابن كثير' and n.get('selected') == 'true'
                                for n in candidate.iter('node'))
                        and not any('جارٍ فتح' in raw for raw in labels)):
                    return candidate
            if not seen:
                raise ValueError('states.jsonl.gz contains no frames')
        return root
    except (OSError, EOFError, ValueError, KeyError, TypeError, ET.ParseError) as exc:
        raise AssertionError(f'Invalid retained evidence fixture at {directory}: {exc}') from exc


def real_pack_expectations():
    """Optional pack coverage; mounted bytes/source declarations still fail closed."""
    selected = os.environ.get('QURANLY_TRANSPORT_HANDOFF')
    if selected is not None and not selected.strip():
        raise AssertionError('QURANLY_TRANSPORT_HANDOFF is empty')
    handoff = Path(selected) if selected is not None else REPO / '.local/handoff'
    pack = handoff / 'app/arabic-three-tafsirs.sqlite'
    if not pack.exists():
        raise unittest.SkipTest(f'Real-pack transport coverage unavailable; missing pack: {pack}')
    try:
        # This owner authenticates the pack and every notice against the
        # repository content contract and producing Dart source declarations.
        return reader.TafsirExpectations(REPO, handoff)
    except (OSError, ValueError, IndexError) as exc:
        raise AssertionError(f'Invalid real-pack fixture at {handoff}: {exc}') from exc


class RetainedTransportTest(unittest.TestCase):
    def test_actual_failed_headers_and_actions_on_both_apis(self):
        for api, directory in failed_api_directories():
            with self.subTest(api=api):
                self.check_header_and_actions(retained_header(directory))

    def check_header_and_actions(self, root):
        query = 'تفسير الآية 27:59'
        # Reproduce the old exact-node predicate on actual retained bytes.
        self.assertFalse(any(label(n).strip('\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069') == query
                             for n in root.iter('node')))
        rows = [(i, label(n)) for i, n in enumerate(root.iter('node')) if label(n)]
        result = reader.tafsir_header(rows, 'ibn_kathir', '27:59', 'THE ANT 59/93')
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 3)
        for match in result:
            raw = dict(rows)[match['node_index']]
            self.assertEqual(reader.digest(raw.encode()), match['node_label_sha256'])
            self.assertEqual(raw[match['start']:match['end']], match['raw_value'])
        actions = [n for n in root.iter('node') if label(n) == 'اختيار تفسير ابن كثير']
        self.assertEqual(len(actions), 1)
        self.assertEqual([actions[0].get(k) for k in ('selected', 'enabled', 'clickable')], ['true'] * 3)
        checks, gestures, taps = checks_for_frames([root] * 3)
        checks.selected('ابن كثير')
        self.assertEqual(len(checks.header('ibn_kathir', '27:59')), 3)
        checks.click('اختيار تفسير ابن كثير', up=False)
        self.assertEqual(gestures, [])
        self.assertEqual(taps, actions)
        # Whole merged header can never confer a CLICK on a text fragment.
        checks, gestures, taps = checks_for_frames([root] * 8)
        with tempfile.TemporaryDirectory() as tmp, patch.object(reader, 'OUT', Path(tmp)), \
                patch.object(reader.time, 'sleep'), patch.object(reader.subprocess, 'check_output', return_value=b'static test raster'):
            with self.assertRaisesRegex(AssertionError, 'unchanged scroll'):
                checks.click(query, up=False)
        self.assertLessEqual(len(gestures), 3)
        self.assertEqual(taps, [])
        # Mutations are local synthetic negatives of the retained transport.
        actual = dict(rows)[result[0]['node_index']]
        for before, after in [('27:59', '27:58'), ('27:59', '27:590'),
                              ('THE ANT 59/93', 'THE ANT 58/93'),
                              (reader.BOOK_TITLES['ibn_kathir'], reader.BOOK_TITLES['al_tabari'])]:
            mutated = [(i, text.replace(before, after) if text == actual else text) for i, text in rows]
            self.assertIsNone(reader.tafsir_header(mutated, 'ibn_kathir', '27:59', 'THE ANT 59/93'))


class RealPackTransportTest(unittest.TestCase):
    def test_actual_failed_headers_match_authenticated_pack_on_both_apis(self):
        owner = real_pack_expectations()
        # TafsirExpectations.entry uses a SQLite transaction context. Own and
        # explicitly close these test connections as well, without changing the
        # exported harness or its interpretation of entries.
        connect = reader.sqlite3.connect
        with ExitStack() as connections:
            def owned_connect(*args, **kwargs):
                return connections.enter_context(closing(connect(*args, **kwargs)))

            with patch.object(reader.sqlite3, 'connect', owned_connect):
                for api, directory in failed_api_directories():
                    with self.subTest(api=api):
                        root = retained_header(directory)
                        checks, gestures, _ = checks_for_frames([root] * 2)
                        checks.tafsir = owner
                        content = checks.ready_tafsir('ibn_kathir', '27:59', full=False)
                        self.assertEqual(content['verified_line_indices'], [0, 2])
                        self.assertEqual(content['exact_labels'], 2)
                        for match in content['matches']:
                            raw = label(list(root.iter('node'))[match['node_index']])
                            self.assertEqual(reader.digest(raw[match['start']:match['end']].encode()),
                                             match['value_sha256'])
                        self.assertEqual(gestures, [])


class SyntheticTransportTest(unittest.TestCase):
    """Small synthetic envelopes/identities; these are not observed device states."""
    def test_selected_author_and_click_require_the_real_enabled_action(self):
        for attributes in ({'selected': 'false'}, {'enabled': 'false'}, {'clickable': 'false'}):
            root = ET.Element('hierarchy')
            defaults = {'content-desc': 'اختيار تفسير السعدي', 'bounds': '[20,30][160,180]',
                        'selected': 'true', 'enabled': 'true', 'clickable': 'true'}
            ET.SubElement(root, 'node', {**defaults, **attributes})
            checks, gestures, taps = checks_for_frames([root])
            with self.assertRaises(AssertionError):
                checks.selected('السعدي')
            self.assertEqual((gestures, taps), ([], []))
            if attributes.get('selected') != 'false':
                checks, gestures, taps = checks_for_frames([root])
                with self.assertRaisesRegex(AssertionError, 'enabled CLICK'):
                    checks.click('اختيار تفسير السعدي')
                self.assertEqual((gestures, taps), ([], []))

    def test_metadata_partitions_and_rejection(self):
        values = [reader.BOOK_TITLES['ibn_kathir'], 'THE ANT 59/93', 'تفسير الآية 27:59']
        for labels in [values, ['\n'.join(values)], [values[0], '\n'.join(values[1:])],
                       ['\n'.join(values[:2]), values[2]],
                       ['\n'.join('\u202a' + v + '\u202c' for v in values)]]:
            self.assertEqual(len(reader.tafsir_header(list(enumerate(labels)), 'ibn_kathir', '27:59', values[1])), 3)
        for labels in [values[:2], values[::-1], values + [values[2]],
                       [values[0], values[1], values[2] + '0'],
                       ['prefix\n' + '\n'.join(values)], ['\n'.join(values) + '\nsuffix'],
                       ['\n'.join(values).replace('27:59', '27:58')],
                       ['\n'.join(values).replace(values[2], '\u202a' + values[2])]]:
            self.assertIsNone(reader.tafsir_header(list(enumerate(labels)), 'ibn_kathir', '27:59', values[1]))

    def test_whole_notice_bodies_and_precise_raw_ranges(self):
        notices = [text for i in range(4) for text in (f'title {i}', f'\ufeffنَصّ {i}\r\nsecond\n¬حاشية¥\u00a0')]
        summary = 'synthetic summary\nwith a newline'
        merged = summary + '\n' + '\n'.join(title + '\n\u202a' + body + '\u202c'
                                            for title, body in zip(notices[::2], notices[1::2]))
        traversal = reader.TextTraversal(notices, allowed=[summary] + notices, ltr=True)
        self.assertTrue(traversal.observe([merged], [17], state=43))
        result = traversal.finish()
        self.assertEqual(result['exact_labels'], 8)
        for text, match in zip(notices, result['matches']):
            self.assertEqual(merged[match['start']:match['end']], text)
            self.assertEqual((match['node_index'], match['state']), (17, 43))
            self.assertEqual(match['value_sha256'], reader.digest(text.encode()))
        for wrong in [merged.replace('\r\n', '\n'), merged.replace('\ufeff', ''),
                      merged.replace('َ', ''), merged.replace('\u00a0', ' '),
                      merged.replace(notices[-1], notices[-1] + '\nstale suffix'),
                      merged.replace(notices[-1], notices[-1][:-1]),
                      merged.replace(notices[-1], 'loading'),
                      merged + '\nunowned prose', 'prefix\n' + merged]:
            traversal = reader.TextTraversal(notices, allowed=[summary] + notices, ltr=True)
            self.assertFalse(traversal.observe([wrong]))
            with self.assertRaisesRegex(AssertionError, 'incomplete'):
                traversal.finish()
        traversal = reader.TextTraversal(notices, allowed=[summary] + notices, ltr=True)
        with self.assertRaisesRegex(AssertionError, 'order differs'):
            traversal.observe(['\n'.join(notices[::-1])])
        for status in ['جارٍ فتح إشعارات المصدر', 'تعذّر فتح التفسير المحلي. أعد المحاولة.']:
            traversal = reader.TextTraversal(notices, allowed=[summary] + notices, ltr=True)
            with self.assertRaises(AssertionError):
                traversal.observe([merged, status])
                traversal.finish()

    def test_metadata_envelopes_never_normalize_prose_or_clipboard(self):
        raw = '\ufeffنَصّ\u202c\u00a0'
        for wrong in [raw.lstrip('\ufeff'), raw.replace('\u202c', ''), raw.replace('\u00a0', ' '),
                      '\u202a' + raw + '\u202c']:
            traversal = reader.TextTraversal([raw])
            self.assertFalse(traversal.observe([wrong]))
            with self.assertRaises(AssertionError):
                traversal.finish()
            with self.assertRaises(AssertionError):
                reader.verify_clipboard(wrong + '\n27:59', raw, '27:59')
        self.assertEqual(reader.raw_atoms(raw, [raw]), [(raw, 0, len(raw))])

    def test_unchanged_semantics_need_actual_unchanged_raster(self):
        progress = reader.ScrollProgress()
        for raster in ('first', 'second', 'third', 'fourth'):
            progress.observe('same merged bounds and label', lambda: raster)
        progress.observe('same merged bounds and label', lambda: 'fourth')
        with self.assertRaisesRegex(AssertionError, 'unchanged scroll'):
            progress.observe('same merged bounds and label', lambda: 'fourth')


class FixtureBoundaryTest(unittest.TestCase):
    """Fixture rejection tests; generated files never stand in for real evidence."""

    def test_explicit_missing_empty_and_one_api_fixtures_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for fixture in (root / 'absent', root, root / 'one-api'):
                if fixture.name == 'one-api':
                    directory = fixture / 'api-35/reader'
                    directory.mkdir(parents=True)
                    # Preflight must reject missing API36 before reading these
                    # deliberately invalid bytes; they are not evidence.
                    for name in ('failure.xml', 'states.jsonl.gz'):
                        (directory / name).write_bytes(b'invalid fixture')
                with self.subTest(fixture=fixture.name), patch.dict(
                        os.environ, {'QURANLY_FAILED_EVIDENCE_ROOT': str(fixture)}):
                    result = unittest.TestResult()
                    RetainedTransportTest('test_actual_failed_headers_and_actions_on_both_apis').run(result)
                    self.assertEqual(result.testsRun, 1)
                    self.assertEqual(len(result.failures), 1)
                    self.assertEqual((result.errors, result.skipped), ([], []))
                    self.assertIn('Incomplete retained evidence fixture', result.failures[0][1])
                    self.assertIn('api-36/reader/failure.xml', result.failures[0][1])

    def test_optional_absent_empty_and_partial_fixtures_are_explicit_skips(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            os.environ.pop('QURANLY_FAILED_EVIDENCE_ROOT', None)
            root = Path(tmp)
            (root / 'one-api/api-35/reader').mkdir(parents=True)
            for fixture in (root / 'absent', root, root / 'one-api'):
                with self.subTest(fixture=fixture.name), patch.dict(
                        failed_api_directories.__globals__, DEFAULT_EVIDENCE_ROOT=fixture):
                    result = unittest.TestResult()
                    RetainedTransportTest('test_actual_failed_headers_and_actions_on_both_apis').run(result)
                    self.assertEqual((result.failures, result.errors), ([], []))
                    self.assertEqual(len(result.skipped), 1)
                    self.assertIn('Incomplete retained evidence fixture', result.skipped[0][1])
                    self.assertIn(str(fixture / 'api-36/reader/failure.xml'), result.skipped[0][1])

    def test_malformed_mounted_xml_and_empty_trace_fail(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, {'QURANLY_FAILED_EVIDENCE_ROOT': tmp}):
            root = Path(tmp)
            for api in (35, 36):
                directory = root / f'api-{api}/reader'
                directory.mkdir(parents=True)
                (directory / 'failure.xml').write_text('<broken')
                with gzip.open(directory / 'states.jsonl.gz', 'wt'):
                    pass
            for malformed in ('xml', 'empty trace'):
                with self.subTest(malformed=malformed):
                    result = unittest.TestResult()
                    RetainedTransportTest('test_actual_failed_headers_and_actions_on_both_apis').run(result)
                    self.assertEqual(len(result.failures), 2)  # both API subtests ran
                    self.assertEqual((result.errors, result.skipped), ([], []))
                    for _, failure in result.failures:
                        self.assertIn('Invalid retained evidence fixture', failure)
                        if malformed == 'empty trace':
                            self.assertIn('contains no frames', failure)
                for api in (35, 36):
                    (root / f'api-{api}/reader/failure.xml').write_text('<hierarchy/>')

    def test_public_layout_owns_sources_and_reports_absent_or_invalid_pack(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ):
            os.environ.pop('QURANLY_TRANSPORT_HANDOFF', None)
            repo = Path(tmp)
            (repo / '.ci/tests').mkdir(parents=True)
            source = Path(__file__).read_text()
            harness_path = next(line for line in source.splitlines() if line.startswith('PATH = '))
            self.assertEqual(source.splitlines().count(harness_path), 1)
            exported_test = repo / '.ci/tests/test_reader_transport.py'
            exported_test.write_text(source.replace(harness_path + '\n',
                                                   "PATH = Path(__file__).parents[1] / 'reader.py'\n"))
            shutil.copy2(PATH, repo / '.ci/reader.py')
            for name in ('docs/phase-4/content-contract.json', 'lib/tafsir.dart', 'lib/tafsir_view.dart'):
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPO / name, target)
            spec = importlib.util.spec_from_file_location('public_transport_fixture', exported_test)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.assertEqual(module.REPO, repo)
            result = unittest.TestResult()
            module.RealPackTransportTest('test_actual_failed_headers_match_authenticated_pack_on_both_apis').run(result)
            self.assertEqual((result.failures, result.errors), ([], []))
            self.assertEqual(len(result.skipped), 1)
            pack = repo / '.local/handoff/app/arabic-three-tafsirs.sqlite'
            self.assertIn(str(pack), result.skipped[0][1])
            self.assertIn('Real-pack transport coverage unavailable', result.skipped[0][1])
            # Invalid mounted data must reach the real expectation owner's pin
            # check. This is a negative fixture, never a substitute corpus.
            pack.parent.mkdir(parents=True)
            pack.write_bytes(b'invalid pack')
            with self.assertRaisesRegex(AssertionError, 'Unauthenticated tafsir expectation pack'):
                module.real_pack_expectations()


if __name__ == '__main__':
    unittest.main()
