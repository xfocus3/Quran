"""Private retained-XML regression plus explicitly synthetic transport contracts.

Raw captures/prose are read only from the optional private mount, never embedded.
This is source verification; no device, original-route or parity verdict follows.
"""
import importlib.util
import io
import gzip
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile
import time
from types import SimpleNamespace
import xml.etree.ElementTree as ET

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


class RetainedTransportTest(unittest.TestCase):
    def test_actual_failed_headers_and_actions_on_both_apis(self):
        root_dir = Path(os.environ.get('QURANLY_FAILED_EVIDENCE_ROOT', '/home/agent/hosted-evidence'))
        if not root_dir.is_dir():
            self.skipTest('Private failed-run evidence is not mounted')
        for api in (35, 36):
            directory = root_dir / f'api-{api}/reader'
            if not directory.is_dir():
                continue
            # Later failures are deep in contexts; select the first retained
            # loaded Ibn header with its actual selected author action instead
            # of assuming the terminal failure frame still contains a header.
            root = ET.parse(directory / 'failure.xml').getroot()
            trace = directory / 'states.jsonl.gz'
            if trace.exists():
                with gzip.open(trace, 'rt') as stream:
                    for line in stream:
                        candidate = ET.fromstring(json.loads(line)['xml'])
                        labels = [label(n) for n in candidate.iter('node')]
                        if (any(reader.BOOK_TITLES['ibn_kathir'] in raw and 'تفسير الآية 27:59' in raw for raw in labels)
                                and any(label(n) == 'اختيار تفسير ابن كثير' and n.get('selected') == 'true'
                                        for n in candidate.iter('node'))
                                and not any('جارٍ فتح' in raw for raw in labels)):
                            root = candidate
                            break
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
            repo = PATH.parents[2]
            if (repo / '.local/handoff/app/arabic-three-tafsirs.sqlite').exists():
                checks, gestures, _ = checks_for_frames([root] * 2)
                checks.tafsir = reader.TafsirExpectations(repo, repo / '.local/handoff')
                content = checks.ready_tafsir('ibn_kathir', '27:59', full=False)
                self.assertEqual(content['verified_line_indices'], [0, 2])
                self.assertEqual(content['exact_labels'], 2)
                for match in content['matches']:
                    raw = label(list(root.iter('node'))[match['node_index']])
                    self.assertEqual(reader.digest(raw[match['start']:match['end']].encode()), match['value_sha256'])
                self.assertEqual(gestures, [])
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


if __name__ == '__main__':
    unittest.main()
