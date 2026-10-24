"""Supplemental raster coverage, not OCR, original-template or device acceptance.

Optional private API36 fixture is a LATER failure capture, not the lost failing
screencap. No private images, XML or Quran strings are embedded here.
"""
import json
import math
import os
from pathlib import Path
import random
import struct
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zlib

from test_reader_transport import reader, bounds, label, checks_for_frames


def model(scale, phase=0., identities=(0, 1, 2), short=False, boundary_strokes=False):
    """Analytic rectangle-area antialiasing of fixed vector-like ink strokes.

    Scale 2/3 models export/device density; phase is a physical subpixel offset.
    No platform shaping, Quran, or device pixels are simulated by this model.
    """
    w, h = round(329 * scale), round((80 * len(identities) + 10) * scale)
    rows = [bytearray([255]) * (w * 3) for _ in range(h)]
    for line, identity in enumerate(identities):
        rng = random.Random(identity)
        # Shared full vertical extent with connected body rows / detached marks.
        rectangles = [(318, 10, 321, 15), (318, 19, 321, 49)]
        for _ in range(30):
            x = (rng.randrange(47 if short else 2, 60) * 329 / 64 - .5 if boundary_strokes
                 else rng.uniform(235 if short else 10, 310))
            y = rng.uniform(18, 35)
            rectangles.append((x, y, x + (1. if boundary_strokes else rng.uniform(2, 5)),
                               y + rng.uniform(5, 14)))
        for l, t, r, b in rectangles:
            l, r = l * scale + phase, r * scale + phase
            t, b = (t + line * 80) * scale + phase, (b + line * 80) * scale + phase
            for y in range(math.floor(t), math.ceil(b)):
                for x in range(math.floor(l), math.ceil(r)):
                    coverage = (min(x + 1, r) - max(x, l)) * (min(y + 1, b) - max(y, t))
                    value = round(255 * (1 - coverage))
                    at = x * 3
                    value = min(rows[y][at], value)
                    rows[y][at:at + 3] = bytes([value]) * 3
    return w, h, 3, rows


def lines(png, scale):
    return reader.ink_lines(png, (0, 0, *png[:2]), round(8 * scale))


def floor_lines(png, scale):
    """Legacy hard-floor oracle, retaining the exact dark predicate/segmentation."""
    return floor_signatures(png, lines(png, scale))


def floor_signatures(png, segmented):
    result = [dict(line) for line in segmented]
    channels = png[2]
    for line in result:
        l, t, r, b = line['bounds']
        signature = [0] * 1536
        for y in range(t, b):
            for x in range(l, r):
                if (max(png[3][y][x*channels:x*channels+3]) < 110 and
                        (channels == 3 or png[3][y][x*channels+3] > 200)):
                    signature[(y-t)*24//(b-t)*64 + (x-l)*64//(r-l)] += 1
        norm = math.sqrt(sum(v*v for v in signature))
        line['signature'] = [v/norm for v in signature]
    return result


def encode_png(png):
    w, h, c, rows = png
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2 if c == 3 else 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(b''.join(b'\0' + row for row in rows))) + chunk(b'IEND', b''))


class DensityRasterTest(unittest.TestCase):
    def test_real_density_ratio_and_subpixel_phase_preserve_ordered_ink(self):
        legacy_failed = False
        for short in (False, True):
            exported = lines(model(2, short=short), 2)
            for phase in (0., .25, .5, .75):
                with self.subTest(short=short, phase=phase):
                    screen = model(3, phase, short=short)
                    observed = lines(screen, 3)
                    self.assertEqual([m['line'] for m in reader.match_lines(observed, exported)], [0, 1, 2])
                    legacy_failed |= any(row['cosine'] < .94 for row in reader.line_diagnostics(
                        floor_lines(screen, 3), floor_lines(model(2, short=short), 2)))
        # Thin strokes straddling grid-cell boundaries expose the quantization
        # mechanism directly. Quarter-physical-pixel phase is not an alignment
        # search: render a fixed vector model at the two known densities.
        for phase in (0., .25):
            export = model(2, boundary_strokes=True)
            screen = model(3, phase, boundary_strokes=True)
            self.assertEqual([m['line'] for m in reader.match_lines(lines(screen, 3), lines(export, 2))], [0, 1, 2])
            legacy_failed |= any(row['cosine'] < .94 for row in reader.line_diagnostics(
                floor_lines(screen, 3), floor_lines(export, 2)))
        self.assertTrue(legacy_failed, 'Model must expose the actual hard-bin density defect')

    def test_wrong_missing_reordered_and_cropped_long_and_short_ink_fail(self):
        for short in (False, True):
            observed = lines(model(3, .25, short=short), 3)
            exported = lines(model(2, short=short), 2)
            self.assertEqual(len(reader.match_lines(observed, exported)), 3)
            for changed in (lines(model(2, identities=(9, 8, 7), short=short), 2),
                            exported[:2], exported[::-1]):
                with self.subTest(short=short, mutation='wrong/missing/reordered'):
                    with self.assertRaises(AssertionError):
                        reader.match_lines(observed, changed)
            # Erase an actual horizontal region of ink but preserve crop bounds,
            # including right-aligned short lines. Pure pixel counts cannot
            # distinguish translation/cropping of otherwise similar ink.
            crop = model(2, short=short)
            start = (270 if short else 150) * 2
            for row in crop[3]:
                row[start*3:318*2*3] = bytes([255]) * ((318*2-start)*3)
            with self.assertRaises(AssertionError):
                reader.match_lines(observed, lines(crop, 2))

    def test_full_synthetic_extent_requires_all_lines_and_actual_end(self):
        exported = lines(model(2, identities=tuple(range(24))), 2)
        observed = lines(model(3, .25, identities=tuple(range(24))), 3)
        self.assertEqual((len(exported), len(observed)), (24, 24))
        walk = reader.RasterTraversal(24)
        for offset in range(0, 24, 6):
            matched = reader.match_lines(observed[offset:offset+6], exported)
            self.assertEqual([m['line'] for m in matched], list(range(offset, offset+6)))
            walk.observe(matched, ('synthetic frame', offset), False)
        with self.assertRaisesRegex(AssertionError, 'end.*never observed'):
            walk.finish()
        walk.observe(reader.match_lines(observed[-1:], exported), 'actual synthetic end', True)
        walk.finish()
        # Extra exported lines can never be waived by reaching screen end.
        extra = reader.RasterTraversal(25)
        extra.observe(reader.match_lines(observed, exported), 'synthetic end', True)
        with self.assertRaisesRegex(AssertionError, 'coverage incomplete'):
            extra.finish()

    def test_exact_checked_frame_and_numeric_diagnostics_exist_before_failure(self):
        checks = reader.ReaderChecks.__new__(reader.ReaderChecks)
        png = model(2)
        data = encode_png(png)
        root = ET.fromstring('<hierarchy><node bounds="[0,0][658,500]"/></hierarchy>')
        exported = lines(model(2, identities=(9, 8, 7)), 2)
        with tempfile.TemporaryDirectory() as tmp, patch.object(reader, 'OUT', Path(tmp)):
            with self.assertRaisesRegex(AssertionError, 'absent/different'):
                checks.compare_raster_frame(3, root, data, exported, (0, 0, *png[:2]), 16, False,
                                            {'xml_returned_monotonic': 1., 'screen_returned_monotonic': 2.})
            self.assertEqual((Path(tmp)/'long-raster-checked.png').read_bytes(), data)
            self.assertEqual(ET.tostring(ET.parse(Path(tmp)/'long-raster-checked.xml').getroot()), ET.tostring(root))
            details = json.loads((Path(tmp)/'long-raster-checked.json').read_text())
            self.assertEqual(details['frame'], 3)
            self.assertEqual(details['screen_sha256'], reader.digest(data))
            self.assertEqual(details['state'], 'computed-before-validation')
            self.assertEqual(len(details['lines']), 3)
            self.assertTrue(all(len(row['scores']) == 3 for row in details['lines']))
            self.assertTrue(any(row['cosine'] < .94 for row in details['lines']))
            self.assertIn('sequential', details['atomicity'])
            # A malformed screenshot also survives byte-exactly, with captured
            # metadata rather than fabricated numeric comparisons.
            with self.assertRaises(AssertionError):
                checks.compare_raster_frame(4, root, data[:-1], exported, (0, 0, *png[:2]), 16, False, {})
            self.assertEqual((Path(tmp)/'long-raster-checked.png').read_bytes(), data[:-1])
            self.assertEqual(json.loads((Path(tmp)/'long-raster-checked.json').read_text())['state'], 'captured')

    def test_excess_lines_fail_in_producer_and_comparison(self):
        # Small real raster, 257 distinct complete line bands; no large fixture
        # or mocked signatures can conceal an unbounded producer loop.
        rows = [bytearray([255]*12) for _ in range(257*8)]
        for i in range(257):
            for y in range(i*8+1, i*8+5):
                rows[y][:6] = bytes(6)
        with self.assertRaisesRegex(AssertionError, 'line budget'):
            reader.ink_lines((4, len(rows), 3, rows), (0, 0, 4, len(rows)), 1)
        line = lines(model(2, identities=(0,)), 2)
        with self.assertRaisesRegex(AssertionError, 'line budget'):
            reader.match_lines(line, line*257)


class RetainedRasterTest(unittest.TestCase):
    def test_later_api36_capture_has_seven_ordered_matches_not_full_coverage(self):
        selected = os.environ.get('QURANLY_RASTER_EVIDENCE_ROOT')
        if selected is not None and not selected.strip():
            self.fail('QURANLY_RASTER_EVIDENCE_ROOT is empty')
        root = Path(selected) if selected is not None else Path('/home/agent/hosted-evidence')
        directory = root / 'api-36/reader'
        names = {'failure.png': 'a6c67b997b8356d88e9955cc96de90208ee7ccf5e82f97c1c9bc269a68e019fe',
                 'long-raster-00.xml': '20dbd0b81aed16bcadc18adf8ff983130cabcb78b154cbb5758c4081586ebc97',
                 'share-2-282-export.png': '00f331bab9ed5eb86c49cc594034012ca8161e7f515dbce2c242f0976f058461'}
        missing = [name for name in names if not (directory / name).is_file()]
        if missing and selected is None:
            self.skipTest('Optional API36 later-capture raster fixture missing: ' + ', '.join(missing))
        self.assertEqual(missing, [], 'Explicit raster fixture is incomplete')
        data = {name: (directory / name).read_bytes() for name in names}
        for name, pin in names.items():
            self.assertEqual(reader.digest(data[name]), pin, name)
        xml = ET.fromstring(data['long-raster-00.xml'])
        nodes = [n for n in xml.iter('node') if label(n).startswith('الآية 2:282 ')]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(bounds(nodes[0]), (116, 1246, 1104, 2640))
        scroll = max((n for n in xml.iter('node') if n.get('scrollable') == 'true'),
                     key=lambda n: bounds(n)[3] - bounds(n)[1])
        self.assertEqual(bounds(scroll), (0, 144, 1220, 2640))
        export = reader.read_png(data['share-2-282-export.png'])
        screen = reader.read_png(data['failure.png'])
        self.assertEqual(export[:2], (744, 3228))
        self.assertEqual(screen[:2], (1220, 2712))
        exported = reader.ink_lines(export, (128/3, (64/3+48+18)*2, 744-128/3,
                                            3228-(48+43/3+14)*2), 8)
        visible = reader.ink_lines(screen, bounds(nodes[0]), 12, (False, True))
        self.assertEqual((len(exported), len(visible)), (24, 7))
        legacy = reader.line_diagnostics(floor_signatures(screen, visible), floor_signatures(export, exported))
        self.assertAlmostEqual(legacy[1]['cosine'], .9319651303816633, places=12)
        with self.assertRaisesRegex(AssertionError, 'best=0.9320'):
            reader.checked_line_matches(legacy)
        matches = reader.match_lines(visible, exported)
        self.assertEqual([m['line'] for m in matches], list(range(7)))
        self.assertGreater(min(m['cosine'] for m in matches), .98)
        for i, line in enumerate(visible):
            wrong = [sum(a*b for a, b in zip(line['signature'], target['signature']))
                     for j, target in enumerate(exported) if j != i]
            self.assertLess(max(wrong), .5)
        for changed in (exported[:1] + exported[2:], exported[::-1]):
            with self.assertRaises(AssertionError):
                reader.match_lines(visible, changed)
        # Actual retained exported ink, changed over a substantial region of
        # line 1. This verifies detectable raster change, not individual marks.
        changed = (*export[:3], [bytearray(row) for row in export[3]])
        l, t, r, b = exported[1]['bounds']
        for y in range(t, b):
            changed[3][y][150*export[2]:600*export[2]] = bytes([255]) * (450*export[2])
        changed_lines = reader.ink_lines(changed, (128/3, (64/3+48+18)*2, 744-128/3,
                                                  3228-(48+43/3+14)*2), 8)
        with self.assertRaisesRegex(AssertionError, 'absent/different'):
            reader.match_lines(visible, changed_lines)
        partial = reader.RasterTraversal(24)
        partial.observe(matches, 'later capture only', False)
        with self.assertRaisesRegex(AssertionError, 'end.*never observed'):
            partial.finish()
        # Run the actual long-export caller with the later retained XML/PNG
        # and a deliberately damaged export. Only OS observations are replaced.
        # There are exactly two dumps: seek + checked frame, no failure redump.
        checks, gestures, _ = checks_for_frames([xml, xml])
        checks.canonical = {'2:282': label(nodes[0]).removeprefix('الآية 2:282 ')}
        checks.d.find = lambda query, root: next((n for n in root.iter('node') if query in label(n)), None)
        with tempfile.TemporaryDirectory() as tmp, patch.object(reader, 'OUT', Path(tmp)), \
                patch.object(reader.subprocess, 'check_output', return_value=data['failure.png']):
            with self.assertRaisesRegex(AssertionError, 'absent/different'):
                checks.long_export(encode_png(changed))
            self.assertEqual(checks.state_count, 2)
            self.assertEqual(gestures, [])
            self.assertEqual((Path(tmp)/'long-raster-checked.png').read_bytes(), data['failure.png'])
            self.assertEqual(ET.tostring(ET.parse(Path(tmp)/'long-raster-checked.xml').getroot()), ET.tostring(xml))
            diagnostic = json.loads((Path(tmp)/'long-raster-checked.json').read_text())
            self.assertEqual(len(diagnostic['lines']), 7)
            self.assertLess(diagnostic['lines'][1]['cosine'], .94)


if __name__ == '__main__':
    unittest.main()
