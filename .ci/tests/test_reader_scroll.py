"""Format-aware synthetic scroll model; this does not establish device behavior.

Only the Android XML/input boundary is substituted. Geometry comes from the
retained API36 failure; layout/drag response below is explicitly synthetic.
Private trace/corpus fixtures are optional and are never copied into Git.
"""
import gzip
import itertools
import json
import math
import os
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from test_reader_transport import reader, checks_for_frames, label


class ScrollModel:
    def __init__(self, items, viewport=(0, 686, 1220, 2640), offset=0):
        self.items, self.viewport, self.offset = items, viewport, offset
        self.height = sum(height for _, height, _ in items)
        self.gestures, self.taps = [], []
        self.settings = {}

    def dump(self, name=None):
        l, t, r, b = self.viewport
        root = ET.Element('hierarchy')
        owner = ET.SubElement(root, 'node', {'bounds': f'[{l},{t}][{r},{b}]', 'scrollable': 'true'})
        y = t - self.offset
        for text, height, action in self.items:
            if y < b and y + height > t:
                ET.SubElement(owner, 'node', {'content-desc': text,
                    'bounds': f'[{l},{max(t, y)}][{r},{min(b, y + height)}]',
                    'enabled': 'true', 'clickable': str(action).lower()})
            y += height
        return root

    def sh(self, *args):
        if args[:2] == ('settings', 'put'):
            self.settings[args[2:4]] = args[4]
            return ''
        if args[:2] == ('settings', 'get'):
            return self.settings[args[2:4]]
        assert args[:2] == ('input', 'swipe'), args
        _, _, x1, y1, x2, y2, duration = args
        l, t, r, b = self.viewport
        assert l < x1 == x2 < r and t < min(y1, y2) < max(y1, y2) < b
        self.gestures.append(args)
        # Synthetic 28px drag slop, consistent with the observed 250 -> 222
        # bound displacement. No claim about Android velocity/physics follows.
        distance = max(0, abs(y1 - y2) - 28)
        self.offset = max(0, min(self.height - (b - t), self.offset + (distance if y1 > y2 else -distance)))

    def checks(self):
        checks, _, _ = checks_for_frames([])
        checks.raw_dump = self.dump
        checks.d.sh = self.sh
        checks.d.tap = self.taps.append
        checks.scroll_raster = lambda: str(self.offset)  # Synthetic raster boundary.
        return checks


class ScrollTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        for target, value in [('OUT', Path(self.temp.name))]:
            p = patch.object(reader, target, value)
            p.start()
            self.addCleanup(p.stop)
        for p in [patch.object(reader.time, 'sleep'),
                  patch.object(reader.subprocess, 'check_output', return_value=b'static synthetic raster')]:
            p.start()
            self.addCleanup(p.stop)


class TargetTraversalTest(ScrollTestCase):
    def test_long_changing_content_reaches_exact_endpoint_with_overlapping_strides(self):
        # 20k px of changing, wrapped source-format rows, then a short endpoint.
        # The old 70 x 250px policy exhausts before this endpoint.
        endpoint = 'نهاية السياق 50:12–14'
        model = ScrollModel([(f'synthetic source line {i}', 500, False) for i in range(40)] +
                            [(endpoint, 126, False), ('footer', 600, False)])
        node = model.checks().seek_metadata(endpoint)
        self.assertEqual(label(node), endpoint)
        self.assertLess(len(model.gestures), 70)

    def test_offscreen_target_does_not_satisfy_metadata_or_click(self):
        root = ScrollModel([('visible', 4000, False)]).dump()
        owner = next(root.iter('node'))
        ET.SubElement(owner, 'node', {'content-desc': 'exact target',
            'bounds': '[0,3000][1220,3126]', 'enabled': 'true', 'clickable': 'true'})
        for click in (False, True):
            checks, _, taps = checks_for_frames([root] * 8)
            with self.assertRaisesRegex(AssertionError, 'unchanged scroll'):
                checks.click('exact target') if click else checks.seek_metadata('exact target')
            self.assertEqual(taps, [])

    def test_short_controls_and_endpoints_are_not_skipped_in_either_direction(self):
        # Sweep all initial alignments around a stride, including a very short
        # row. Test a short landscape viewport and the capped source viewport.
        for viewport in [(0, 686, 1220, 2640), (0, 200, 2712, 1100), (0, 144, 1220, 2640)]:
            height = viewport[3] - viewport[1]
            for up in (True, False):
                for alignment in range(0, min(900, int(height * .4)), 37):
                    model = ScrollModel([('before', 3 * height + alignment, False),
                        ('exact target', 20, True), ('after', 3 * height, False)], viewport)
                    if not up:
                        model.offset = model.height - height
                    checks = model.checks()
                    checks.click('exact target', up=up)
                    self.assertEqual([label(n) for n in model.taps], ['exact target'])
                    self.assertTrue(all(abs(g[3] - g[5]) <= min(900, math.ceil(height * .4))
                                        for g in model.gestures))

    def test_reverse_header_return_and_complete_source_notices_share_policy(self):
        values = ['\ufeffنَصّ\u00a0' + str(i) for i in range(40)]
        model = ScrollModel([(v, 500, False) for v in values])
        checks = model.checks()
        result = checks.verify_content(values)
        self.assertEqual(result['exact_labels'], len(values))
        header = '\n'.join([reader.BOOK_TITLES['al_saadi'], 'THE ANT 59/93', 'تفسير الآية 27:59'])
        model.items.insert(0, (header, 400, False))
        model.height += 400
        model.offset += 400
        self.assertEqual(len(checks.header('al_saadi', '27:59')), 3)
        self.assertTrue(any(g[3] < g[5] for g in model.gestures))

    def test_absent_stale_error_loading_and_changing_budget_exhaustion_fail(self):
        for status, reason in [('نهاية السياق 50:12–140', 'unchanged scroll'),
                               ('نهاية السياق 50:11–14', 'unchanged scroll'),
                               ('تعذّر فتح التفسير المحلي', 'reported an error'),
                               ('جارٍ فتح التفسير المحلي', 'remained loading')]:
            # Even an exact target coexisting with loading/error cannot pass.
            items = [(status, 400, False)]
            if status.startswith(('تعذّر', 'جارٍ')):
                items.append(('نهاية السياق 50:12–14', 400, False))
            checks = ScrollModel(items + [('empty', 4000, False)]).checks()
            ticks = itertools.count(reader.time.monotonic(), 1)
            with patch.object(reader.time, 'monotonic', side_effect=lambda: next(ticks)):
                with self.assertRaisesRegex(AssertionError, reason):
                    checks.seek_metadata('نهاية السياق 50:12–14')
        model = ScrollModel([(f'moving row {i}', 1000, False) for i in range(100)])
        with self.assertRaisesRegex(AssertionError, 'distance budget exhausted'):
            model.checks().seek('absent endpoint', exact=True, limit=2)
        self.assertEqual(len(model.gestures), 3)  # ceil(2 * 900 / 781)
        model = ScrollModel([('wrong source body', 500, False)] * 100)
        with self.assertRaisesRegex(AssertionError, 'incomplete'):
            model.checks().verify_content(['exact source body'], frame_limit=2)
        self.assertEqual(len(model.gestures), 1)  # No unobserved final action.

    def test_real_pack_sizes_in_explicit_synthetic_normal_and_2x_layouts(self):
        repo = Path(__file__).parents[2]
        pack = Path(os.environ.get('QURANLY_SCROLL_TAFSIR_PACK', repo / '.local/handoff/app/arabic-three-tafsirs.sqlite')).resolve()
        if not pack.is_file():
            self.skipTest('Retained tafsir pack is not mounted')
        contract = json.loads((repo / 'docs/phase-4/content-contract.json').read_text())
        self.assertEqual(reader.digest(pack.read_bytes()), contract['pack_sha256'])
        routes = []
        with sqlite3.connect(pack.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
            for row in contract['contexts']:
                texts = db.execute('SELECT text FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah BETWEEN ? AND ? ORDER BY ayah',
                    ('al_tabari', row['surah'], row['from'], row['to'])).fetchall()
                self.assertEqual(len(texts), len(row['source_rows']))
                labels = [f'سجل المصدر {row["surah"]}:{source["ayah"]} — الطبري' for source in row['source_rows']]
                routes.append(([reader.expected_tafsir_display(t[0]) for t in texts], labels,
                               f'نهاية السياق {row["surah"]}:{row["from"]}–{row["to"]}'))
            # The later endpoint consumer traverses the full Saadi 2:282
            # extent; the other authors explicitly verify only source samples.
            text, = db.execute('SELECT text FROM tafseer_entries WHERE tafseer_id=? AND surah=2 AND ayah=282', ('al_saadi',)).fetchone()
            routes.append(([reader.expected_tafsir_display(text)], ['تفسير الآية 2:282'], 'نهاية تفسير الآية 2:282'))
        for scale, viewport in [(1, (0, 686, 1220, 2640)), (2, (0, 686, 1220, 2640)),
                                (2, (0, 200, 2712, 1100))]:
            # Explicit conservative synthetic monospace-like layout: 33px per
            # code point and 126px line pitch at 1x, both scale linearly. Real
            # shaping, marks, Android nonlinear scaling and physics differ.
            columns = max(1, int((viewport[2] - viewport[0]) / (33 * scale)))
            for bodies, labels, endpoint in routes:
                items = []
                for metadata, body in zip(labels, bodies):
                    items.append((metadata, 126 * scale, False))
                    items.extend((line, max(1, math.ceil(len(line) / columns)) * 126 * scale, False)
                                 for line in body.split('\n'))
                model = ScrollModel(items + [(endpoint, 126 * scale, False)], viewport)
                checks = model.checks()
                checks.set_settings(scale, 1 if viewport[2] > viewport[3] else 0)
                self.assertEqual(checks.text_scale, scale)
                for metadata in labels:
                    self.assertEqual(label(checks.seek_metadata(metadata)), metadata)
                self.assertEqual(label(checks.seek_metadata(endpoint)), endpoint)
                # Reverse exact-control traversal covers the same long extent.
                model.items.insert(0, ('source return', 144 * scale, True))
                model.height += 144 * scale
                model.offset += 144 * scale
                checks.click('source return', up=False)
                self.assertEqual(len(model.taps), 1)


class RetainedTraversalTest(ScrollTestCase):
    def test_actual_failure_trace_remains_a_failure_and_has_moving_bounds(self):
        directory = Path(os.environ.get('QURANLY_FAILED_EVIDENCE_ROOT', '/home/agent/hosted-evidence')) / 'api-36/reader'
        if not directory.is_dir():
            self.skipTest('Private failed-run trace is not mounted')
        if not (directory / 'unreachable.json').is_file():
            self.skipTest('Retained traversal failure fixture unavailable; missing ' + str(directory / 'unreachable.json'))
        failure = json.loads((directory / 'unreachable.json').read_text())
        if failure['query'] != 'نهاية السياق 50:12–14':
            self.skipTest('Mounted diagnostics belong to a different failure')
        with gzip.open(directory / 'states.jsonl.gz', 'rt') as stream:
            states = [json.loads(line) for line in stream]
        # Last state is the post-failure capture; preceding 71 are the actual
        # failed seek's initial observation plus its 70 gesture results.
        frames = [ET.fromstring(row['xml']) for row in states[-72:-1]]
        self.assertEqual(len(failure['gestures']), 70)
        self.assertEqual({tuple(g[:4]) for g in failure['gestures']}, {(0, 686, 1220, 2640)})
        self.assertNotEqual(ET.tostring(frames[-2]), ET.tostring(frames[-1]))
        self.assertFalse(any(failure['query'] in label(n).split('\n') for f in frames for n in f.iter('node')))
        # Extend only with duplicate *actual* last XML frames, never a fabricated
        # endpoint. This supplies enough observations for the distance budget.
        checks, gestures, _ = checks_for_frames(frames + [frames[-1]] * 20)
        # Intermediate screenshots were not retained. Supply explicitly
        # synthetic changing raster IDs solely to exercise budget failure even
        # where merged/clipped XML repeats. These are not device raster facts.
        checks.scroll_raster = lambda: str(checks.state_count)
        # Replay is immutable: it cannot predict the repaired device outcome.
        with self.assertRaisesRegex(AssertionError, 'distance budget exhausted'):
            checks.seek_metadata(failure['query'])
        self.assertEqual(len(gestures), math.ceil(70 * 900 / 781))
        self.assertEqual(sum(abs(g[3] - g[5]) for g in gestures), 70 * 900)
        self.assertEqual({abs(g[3] - g[5]) for g in gestures[:-1]}, {781})


if __name__ == '__main__':
    unittest.main()
