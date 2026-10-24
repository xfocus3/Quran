"""Observation ownership: same-state reads are not new device observations.

Substitute only XML, shell and clock boundaries. Retained full-source semantics
are also replayed on both APIs, through actual readers and the real source pack.
"""
import gzip
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from test_reader_transport import reader, checks_for_frames, real_pack_expectations, retained_header
from test_reader_raster_current import fixture_root


def state(*labels):
    root = ET.Element('hierarchy')
    owner = ET.SubElement(root, 'node', bounds='[0,0][1000,2000]', scrollable='true')
    for i, text in enumerate(labels):
        ET.SubElement(owner, 'node', {'text': text, 'bounds': f'[0,{i*100}][1000,{(i+1)*100}]',
                                     'enabled': 'true', 'clickable': 'true'})
    return root


class ObservationOwnerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(reader, 'OUT', Path(self.tmp.name)); p.start(); self.addCleanup(p.stop)
        self.now = 1.
        p = patch.object(reader.time, 'monotonic', lambda: self.now); p.start(); self.addCleanup(p.stop)

    def checks(self, frames):
        checks, _, _ = checks_for_frames(frames)
        checks.observation_log = io.StringIO()
        self.addCleanup(checks.observation_log.close)
        checks.raw_shell = lambda *args, **kwargs: ''
        checks.d.sh = checks.shell
        checks.d.tap = lambda node: checks.d.sh('input', 'tap', 'current target')
        return checks

    def test_synchronous_assertions_share_original_provenance_then_input_reads_fresh(self):
        before, after = state('target', 'before'), state('target', 'after')
        checks = self.checks([before, after])
        checks.seek('target', exact=True)
        checks.verify_content(['before'], allowed=['target', 'before'])
        checks.capture('same-state', png=False)
        self.assertEqual(checks.state_count, 1)
        uses = [json.loads(line) for line in checks.observation_log.getvalue().splitlines()]
        self.assertEqual([u['state'] for u in uses], [1, 1])
        self.assertTrue(all(u['fresh_dump'] is False for u in uses))
        self.assertEqual(uses[0]['xml_sha256'], reader.digest(ET.tostring(before)))
        checks.click('target')
        result = checks.verify_content(['after'], allowed=['target', 'after'])
        self.assertEqual(checks.state_count, 2)
        self.assertEqual(result['matches'][0]['state'], 2)
        self.assertEqual(len(checks.trace.getvalue().splitlines()), 2)

    def test_shared_helper_consumers_use_one_owner_and_wait_reads_expire(self):
        path = Path(self.tmp.name, 'external-helper.py')
        path.write_text('# synthetic OS helper boundary')
        frames = iter([state('before'), state('after'), state('post-input')])
        helper = SimpleNamespace(__file__=str(path), dump=lambda name=None: next(frames), sh=lambda *a, **k: '')
        navigation = SimpleNamespace(__file__=str(path), dump=helper.dump, sh=helper.sh)
        with patch.dict(os.environ, {'QURAN_CI_SERIAL':'emulator-1234', 'GITHUB_SHA':'test-candidate'}), patch.object(
                reader.importlib, 'import_module', side_effect=lambda name: {'device_ui':helper, 'device_navigation':navigation}[name]):
            checks = reader.ReaderChecks()
        self.addCleanup(checks.trace.close)
        self.addCleanup(checks.observation_log.close)
        helper.bounds = lambda n: tuple(map(int, reader.re.findall(r'\d+', n.get('bounds'))))
        helper.label = lambda n: n.get('text', '')
        self.assertIsNotNone(helper.find('before'))
        self.assertIsNotNone(navigation.find('before'))
        self.assertEqual(checks.state_count, 1)
        self.now += .25  # actual public helper's wait polling interval
        self.assertIsNotNone(helper.find('after'))
        self.assertEqual(checks.state_count, 2)
        navigation.sh('input', 'tap')  # imported shared consumer cannot bypass invalidation
        self.assertIsNotNone(navigation.find('post-input'))
        self.assertEqual(checks.state_count, 3)

    def test_expired_loading_and_failed_shell_never_supply_cached_state(self):
        for boundary in ('expired', 'loading', 'failed shell', 'settings', 'lifecycle', 'read command'):
            with self.subTest(boundary=boundary):
                first = state('جارٍ فتح المصدر' if boundary == 'loading' else 'before')
                checks = self.checks([first, state('after')])
                checks.dump()
                if boundary == 'expired':
                    self.now += .101
                elif boundary == 'failed shell':
                    def failed(*args):
                        raise RuntimeError('OS failure')
                    checks.raw_shell = failed
                    with self.assertRaises(RuntimeError):
                        checks.shell('input', 'swipe')
                elif boundary != 'loading':
                    checks.shell({'settings':'settings', 'lifecycle':'am', 'read command':'getprop'}[boundary])
                checks.verify_content(['after'])
                self.assertEqual(checks.state_count, 2)

    def test_traversal_and_captures_never_relabel_cached_offscreen_or_old_png_state(self):
        first, second = state('line0'), state('line1', 'end')
        # Positive child bounds outside its ancestor cannot satisfy an identity.
        ET.SubElement(next(first.iter('node')), 'node', text='end', bounds='[0,3000][1000,3100]')
        checks = self.checks([first, second])
        with patch.object(reader.time, 'sleep'):
            result = checks.verify_content(['line0', 'line1', 'end'])
        self.assertEqual((checks.state_count, result['frames']), (2, 2))
        self.assertEqual([m['state'] for m in result['matches']], [1, 2, 2])
        checks.raw_dump = lambda name=None: state('new PNG state')
        with patch.object(reader.subprocess, 'check_output', return_value=b'OS PNG boundary'):
            checks.capture('new-png')
        self.assertEqual(checks.state_count, 3)
        self.assertEqual(Path(self.tmp.name, 'new-png.png').read_bytes(), b'OS PNG boundary')


class RetainedObservationTest(unittest.TestCase):
    def test_both_api_headers_and_complete_exact_notice_bodies_keep_semantics(self):
        root = fixture_root()
        owner = real_pack_expectations()
        with tempfile.TemporaryDirectory() as tmp, patch.object(reader, 'OUT', Path(tmp)), patch.object(reader.time, 'sleep'):
            for api in (35, 36):
                directory = root / f'current-run/api-{api}/reader'
                header = retained_header(directory)
                checks, _, _ = checks_for_frames([header]*3)
                checks.tafsir = owner
                checks.selected('ابن كثير')
                content = checks.ready_tafsir('ibn_kathir', '27:59', full=False)
                self.assertEqual(content['verified_line_indices'], [0, 2])
                self.assertEqual(content['exact_labels'], 2)
                # Same loaded XML may serve these assertions. Its provenance
                # remains that actual observation, rather than a new state.
                self.assertLessEqual(checks.state_count, 3)
                report = json.loads((directory/'reader-result.json').read_text())
                authors = next(c for c in report['checks'] if c['name'].startswith('three-author'))['authors']
                states = [json.loads(line) for line in gzip.open(directory/'states.jsonl.gz', 'rt')]
                for author in authors:
                    notice = author['notices']
                    first, last = notice['matches'][0]['state'], notice['matches'][-1]['state']
                    frames = [ET.fromstring(s['xml']) for s in states if first <= s['state'] <= last+1]
                    checks, _, _ = checks_for_frames(frames)
                    checks.tafsir = owner
                    # Only semantic XML replay is available for these states.
                    # OS raster progress is substituted; stall/raster behavior
                    # is tested separately, never claimed for this replay.
                    checks.scroll_raster = lambda: str(checks.state_count)
                    observed = checks.source_notices()
                    self.assertEqual(observed['exact_labels'], 8)
                    self.assertEqual(observed['label_sha256'], notice['label_sha256'])
                    self.assertEqual([m['identity'] for m in observed['matches']], list(range(8)))
                    self.assertEqual([m['node_label_sha256'] for m in observed['matches']],
                                     [m['node_label_sha256'] for m in notice['matches']])
                    # These are replayed completed normal-scale source tasks;
                    # no conclusion about incomplete2x, TalkBack or device cost.


if __name__ == '__main__':
    unittest.main()
