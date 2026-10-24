"""Chooser readiness boundary: synthetic models and optional private real XML.

Only OS hierarchy, time and screenshot boundaries are substituted. Synthetic
frames establish no Android execution, speedup, original observation or parity.
No private XML, screenshots or corpus are embedded in this source.
"""
import itertools
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from test_reader_transport import reader, checks_for_frames

PACKAGE = 'com.android.intentresolver'
CAPTION = 'Verse 59, Surah 27 shared via https://quranly.app !'


def synthetic_frame(package=PACKAGE, caption=CAPTION, bounds='[20,100][900,200]'):
    root = ET.Element('hierarchy', {'rotation': '0'})
    owner = ET.SubElement(root, 'node', {'package': package, 'bounds': '[0,0][1000,2000]'})
    ET.SubElement(owner, 'node', {'package': package, 'text': caption, 'bounds': bounds,
        'resource-id': package + ':id/content_preview_text'})
    return root


def retained_chooser_directory():
    selected = os.environ.get('QURANLY_CHOOSER_EVIDENCE_ROOT')
    if selected is not None and not selected.strip():
        raise AssertionError('QURANLY_CHOOSER_EVIDENCE_ROOT is empty')
    root = Path(selected) if selected is not None else Path('/home/agent/hosted-evidence')
    directory = root / 'api-35/reader'
    names = ('share-27-59-chooser.xml', 'share-27-59-repeat-chooser.xml', 'failure.xml',
             'share-27-59-repeat-activity.txt')
    missing = [str(directory / name) for name in names if not (directory / name).is_file()]
    if missing:
        reason = 'Incomplete retained chooser fixture; missing files: ' + ', '.join(missing)
        if selected is not None:
            raise AssertionError(reason)
        raise unittest.SkipTest(reason)
    return directory


class ChooserBoundaryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)
        p = patch.object(reader, 'OUT', self.out)
        p.start()
        self.addCleanup(p.stop)

    def ready(self, frames, png=False):
        checks, commands, taps = checks_for_frames(frames)
        # Historical activity text deliberately lies; it cannot establish
        # readiness while the current XML still belongs to the app.
        checks.d.sh = lambda *args: 'historical ChooserActivity; top MainActivity'
        with patch.object(reader.subprocess, 'check_output', return_value=b'synthetic screenshot'):
            root = checks.wait_for_chooser(27, 59, 'checked', png=png)
        self.assertEqual(commands, [])
        self.assertEqual(taps, [])  # Never select a recipient.
        self.assertEqual(ET.tostring(ET.parse(self.out / 'checked.xml').getroot()), ET.tostring(root))
        return checks, root

    def test_synthetic_delayed_app_tree_ignores_historical_activity_and_saves_exact_checked_frame(self):
        stale = synthetic_frame(reader.PACKAGE, 'app reader 27:59')
        settled = synthetic_frame()
        # No third dump is available: capture must save the checked hierarchy.
        checks, root = self.ready([stale, stale, settled], png=True)
        self.assertIs(root, settled)
        self.assertEqual(checks.state_count, 3)
        self.assertEqual((self.out / 'checked.png').read_bytes(), b'synthetic screenshot')

    def test_synthetic_live_native_caption_passes_without_activity_name_match(self):
        checks, _, taps = checks_for_frames([synthetic_frame()])
        checks.d.sh = lambda *args: 'no activity history available'
        checks.wait_for_chooser(27, 59, 'native', png=False)
        self.assertEqual(taps, [])
        self.assertTrue((self.out / 'native.xml').is_file())
        self.assertFalse((self.out / 'native.png').exists())

    def test_synthetic_long_share_requires_its_own_key_after_old_chooser(self):
        caption = 'Verse 282, Surah 2 shared via https://quranly.app !'
        settled = synthetic_frame(caption=caption)
        checks, _, _ = checks_for_frames([synthetic_frame(), settled])
        root = checks.wait_for_chooser(2, 282, 'long', png=False)
        self.assertIs(root, settled)
        self.assertEqual(checks.state_count, 2)
        self.assertEqual(ET.tostring(ET.parse(self.out / 'long.xml').getroot()), ET.tostring(settled))

    def test_synthetic_wrong_key_caption_package_or_hidden_caption_times_out(self):
        wrong = [synthetic_frame(caption=CAPTION.replace('59', '58')),
                 synthetic_frame(caption=CAPTION.replace('27', '2')),
                 synthetic_frame(caption=CAPTION + ' stale'),
                 synthetic_frame(caption='prefix ' + CAPTION),
                 synthetic_frame(package=reader.PACKAGE),
                 synthetic_frame(package='android'),
                 synthetic_frame(bounds='[20,2100][900,2200]'),
                 synthetic_frame(bounds='[0,0][0,0]')]
        wrong_id = synthetic_frame()
        list(wrong_id.iter('node'))[-1].set('resource-id', PACKAGE + ':id/unrelated_text')
        wrong.append(wrong_id)
        for frame in wrong:
            with self.subTest(xml=ET.tostring(frame)):
                checks, _, _ = checks_for_frames(itertools.repeat(frame))
                ticks = itertools.count(0, 1)
                checks.deadline = 2400
                with patch.object(reader.time, 'monotonic', side_effect=lambda: next(ticks)):
                    with self.assertRaisesRegex(AssertionError, 'exact caption/key.*25 seconds'):
                        checks.wait_for_chooser(27, 59, 'rejected', png=False)
                self.assertFalse((self.out / 'rejected.xml').exists())

    def test_synthetic_correct_caption_arriving_after_deadline_is_not_accepted(self):
        checks, _, _ = checks_for_frames([synthetic_frame()])
        clock = [0]
        def late_dump(name=None):
            clock[0] = 25
            return synthetic_frame()
        checks.raw_dump = late_dump
        checks.deadline = 2400
        with patch.object(reader.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(AssertionError, '25 seconds'):
                checks.wait_for_chooser(27, 59, 'late', png=False)
        self.assertFalse((self.out / 'late.xml').exists())

    def test_synthetic_global_ceiling_still_blocks_readiness(self):
        checks, _, _ = checks_for_frames(itertools.repeat(synthetic_frame(reader.PACKAGE)))
        checks.deadline = 5
        ticks = itertools.count(0, 1)
        with patch.object(reader.time, 'monotonic', side_effect=lambda: next(ticks)):
            with self.assertRaisesRegex(AssertionError, '40 minute budget'):
                checks.wait_for_chooser(27, 59, 'global', png=False)

    def test_retained_real_first_repeat_and_later_failure_hierarchies(self):
        directory = retained_chooser_directory()
        first, stale, settled = [ET.parse(directory / name).getroot() for name in
            ('share-27-59-chooser.xml', 'share-27-59-repeat-chooser.xml', 'failure.xml')]
        self.assertIn('ChooserActivity', (directory / 'share-27-59-repeat-activity.txt').read_text())
        self.assertEqual({n.get('package') for n in stale.iter('node')}, {reader.PACKAGE})
        self.assertEqual({n.get('package') for n in first.iter('node')}, {PACKAGE})
        self.ready([first])
        checks, root = self.ready([stale, settled])
        self.assertIs(root, settled)
        self.assertEqual(checks.state_count, 2)
        # Historical replay checks this boundary only; it cannot predict a
        # future candidate/device outcome or relabel the old report as passed.

    def test_optional_missing_fixture_skips_and_explicit_incomplete_selection_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            for selected in ('', tmp):
                with patch.dict(os.environ, {'QURANLY_CHOOSER_EVIDENCE_ROOT': selected}):
                    with self.assertRaisesRegex(AssertionError, 'empty|missing files'):
                        retained_chooser_directory()
            with patch.dict(os.environ, {}, clear=True), patch.object(Path, 'is_file', return_value=False):
                with self.assertRaisesRegex(unittest.SkipTest, 'missing files'):
                    retained_chooser_directory()


if __name__ == '__main__':
    unittest.main()
