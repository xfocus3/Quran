"""Authenticated selected run fixtures: offline coverage, never device acceptance.

No private PNG/XML/source prose is embedded. Both actual checked pairs and BOTH
full selected first-frame PNGs are required when an explicit root is supplied.
The retained intermediate numeric frames are not substitute screenshot evidence.
"""
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from test_reader_transport import reader, bounds, label

SELECTION_SHA256 = '0ae3eaf19b5f736a6b0c75abbbf3ee3510a3d9c9d8356516b79c71f51c7fb546'


def fixture_root():
    selected = os.environ.get('QURANLY_CURRENT_RASTER_EVIDENCE_ROOT')
    if selected is not None and not selected.strip():
        raise AssertionError('QURANLY_CURRENT_RASTER_EVIDENCE_ROOT is empty')
    root = Path(selected) if selected is not None else Path('/home/agent/hosted-evidence')
    if not (root / 'selection.json').is_file():
        if selected is not None:
            raise AssertionError('Explicit current raster fixture is incomplete: selection.json')
        raise unittest.SkipTest('Optional current raster fixture absent: selection.json')
    data = (root / 'selection.json').read_bytes()
    assert reader.digest(data) == SELECTION_SHA256, 'Unauthenticated current fixture selection'
    selection = json.loads(data)
    assert (selection['run_id'], selection['run_attempt'], selection['private_commit'], selection['public_commit']) == (
        '40077025422', 1, '6a659754c027b82db3a290338b0573d04650bcf1',
        '2329dcad3b0f7edec8735ac7f19d03ed3713847b'), 'Current fixture labels differ'
    # Authenticate both APIs' complete selected archives, reports, images and
    # traces, not just a convenient earlier seven-line crop. Explicit/partial
    # selections always fail; mounted damaged defaults fail too.
    pins = {name: pin for name, pin in selection['files'].items() if name.startswith('current-run/')}
    assert pins and all(name.startswith('current-run/api-35/') or name.startswith('current-run/api-36/')
                        for name in pins), 'Invalid current fixture paths'
    for name, pin in pins.items():
        assert (root / name).is_file(), 'Explicit current raster fixture is incomplete: ' + name
        assert reader.digest((root / name).read_bytes()) == pin, 'Unauthenticated fixture: ' + name
    return root


def exported(png):
    # Same source-owned card crop as the real caller; no fitted line cells.
    return reader.ink_lines(png, (128/3, (64/3+48+18)*2, png[0]-128/3,
                                 png[1]-(48+43/3+14)*2), 8, background=reader.RASTER_BACKGROUND)


def observed(png, root):
    nodes = [n for n in root.iter('node') if label(n).startswith('الآية 2:282 ')]
    assert len(nodes) == 1, 'Missing/ambiguous canonical Quran semantic node'
    box = bounds(nodes[0])
    scroll = max((n for n in root.iter('node') if n.get('scrollable') == 'true'),
                 key=lambda n: bounds(n)[3] - bounds(n)[1])
    viewport = bounds(scroll)
    assert viewport[0] <= box[0] < box[2] <= viewport[2]
    clipped = (box[1] <= viewport[1]+1, box[3] >= viewport[3]-1)
    return reader.ink_lines(png, box, 12, clipped, background=reader.RASTER_BACKGROUND), clipped


class CurrentRasterFixtureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = fixture_root()
        cls.png = reader.read_png((cls.root/'current-run/api-35/reader/share-2-282-export.png').read_bytes())
        cls.export = exported(cls.png)

    def test_actual_checked_pairs_and_full_selected_first_frames(self):
        self.assertEqual(len(self.export), 24)
        for api in (35, 36):
            directory = self.root / f'current-run/api-{api}/reader'
            report = json.loads((directory/'reader-result.json').read_text())
            self.assertEqual(report['status'], 'failed')
            checked = json.loads((directory/'long-raster-checked.json').read_text())
            self.assertEqual(checked['frame'], 1 if api == 35 else 3)
            self.assertEqual(checked['screen_sha256'], reader.digest((directory/'long-raster-checked.png').read_bytes()))
            self.assertEqual(checked['xml_sha256'], reader.digest((directory/'long-raster-checked.xml').read_bytes()))
            seen = set()
            for name, indices in [('long-raster-00', list(range(7))),
                                  ('long-raster-checked', list(range(13)) if api == 35 else list(range(12, 24)))]:
                with self.subTest(api=api, frame=name):
                    screen = reader.read_png((directory/(name+'.png')).read_bytes())
                    root = ET.parse(directory/(name+'.xml')).getroot()
                    lines, clipped = observed(screen, root)
                    matches = reader.match_lines(lines, self.export)
                    self.assertEqual([m['line'] for m in matches], indices)
                    self.assertGreaterEqual(min(m['cosine'] for m in matches), .94)
                    seen.update(indices)
                    if name == 'long-raster-checked':
                        self.assertEqual(len(lines), len(checked['lines']))
                        self.assertEqual(clipped, tuple(checked['clipped']))
                        # Every alternative is still computed; no key/API/index
                        # override or permissive fallback picks the expected one.
                        diagnostics = reader.line_diagnostics(lines, self.export)
                        self.assertTrue(all(len(row['scores']) == 24 for row in diagnostics))
                        self.assertLess(max(score for row in diagnostics for i, score in enumerate(row['scores'])
                                            if i != row['line']), .65)
            self.assertEqual(seen, set(range(13)) if api == 35 else set(range(7)) | set(range(12,24)))
            # Pixel replay covers 13/24 and 19/24. API36's retained device
            # metrics separately record ALL24/end over4frames for the OLD head.
            progress = json.loads((directory/'long-raster-progress.json').read_text())
            self.assertEqual(progress['ayah_end_observed'], api == 36)
            if api == 36:
                self.assertEqual(progress['matched_lines'], list(range(24)))
                self.assertEqual(len(progress['frames']), 4)
            else:
                self.assertEqual(progress['matched_lines'], list(range(7)))

    def test_actual_long_short_crop_removed_reordered_and_changed_ink_negatives(self):
        png = self.png
        for changed in (self.export[:2] + self.export[3:], self.export[::-1]):
            with self.assertRaises(AssertionError):
                reader.match_lines(self.export, changed)
        for index in (2, 23):
            l, t, r, b = self.export[index]['bounds']
            # Reproduce the diagnostic's actual bottom-quarter-CELL erasures,
            # including faint tails: source31.5/1.75, runSpacing17/3, export2x.
            # These coordinates define a NEGATIVE fixture, never match geometry.
            cell_top = (64/3+48+18)*2 + index*(31.5*1.75+17/3)*2
            cell_bottom = cell_top + 31.5*1.75*2
            for mutation in ('bottom_quarter_cell', 'bottom_quarter_ink', 'right_quarter', 'all'):
                with self.subTest(index=index, mutation=mutation):
                    rows = list(png[3])
                    erased = 0
                    for y in range(math.floor(cell_top), math.ceil(cell_bottom)):
                        row = bytearray(rows[y]); rows[y] = row
                        for x in range(l, r):
                            if (mutation == 'all' or mutation == 'bottom_quarter_cell' and y > cell_bottom-(cell_bottom-cell_top)/4
                                    or mutation == 'bottom_quarter_ink' and y > b-(b-t)/4
                                    or mutation == 'right_quarter' and x > r-(r-l)/4):
                                at = x*png[2]
                                erased += sum(row[at:at+3]) < sum(reader.RASTER_BACKGROUND)
                                row[at:at+3] = bytes(reader.RASTER_BACKGROUND)
                    self.assertGreater(erased, 0, 'Negative must actually remove optical ink')
                    changed = exported((*png[:3], rows))
                    with self.assertRaises(AssertionError):
                        reader.match_lines(self.export, changed)


class CurrentFixtureSelectionTest(unittest.TestCase):
    def test_explicit_empty_missing_and_tampered_selection_fail_closed(self):
        for selected in ('', '/definitely-absent-current-raster-fixture'):
            with patch.dict(os.environ, {'QURANLY_CURRENT_RASTER_EVIDENCE_ROOT': selected}):
                with self.assertRaises(AssertionError):
                    fixture_root()
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, {'QURANLY_CURRENT_RASTER_EVIDENCE_ROOT': tmp}):
            Path(tmp, 'selection.json').write_text('{}')
            with self.assertRaisesRegex(AssertionError, 'Unauthenticated'):
                fixture_root()

    def test_absent_optional_default_explicitly_skips(self):
        with patch.dict(os.environ), patch.object(Path, 'is_file', return_value=False):
            os.environ.pop('QURANLY_CURRENT_RASTER_EVIDENCE_ROOT', None)
            with self.assertRaisesRegex(unittest.SkipTest, 'Optional current raster fixture absent'):
                fixture_root()


if __name__ == '__main__':
    unittest.main()
