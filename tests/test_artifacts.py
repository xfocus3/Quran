"""Exercise the CLI with retained bytes, never a fabricated Quran fixture."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = os.environ.get('QURANLY_REFERENCE_DIR')

@unittest.skipUnless(REFERENCE, 'Set QURANLY_REFERENCE_DIR to existing retained evidence')
class ArtifactHandoffTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ROOT / '.local').mkdir(exist_ok=True)

    def test_prepare_preserves_source_unicode_and_separates_tafsir_status(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.local') as temp:
            output = Path(temp) / 'handoff'
            result = subprocess.run(['python3', 'tools/prepare_artifacts.py', 'prepare',
                '--reference-root', REFERENCE, '--output', str(output)],
                cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads((output / 'receipt.json').read_text())
            self.assertEqual(receipt['schema_version'], 3)
            self.assertEqual(receipt['quran']['identities'], 6236)
            self.assertEqual(receipt['tafsir']['lookup_identities'], 18708)
            self.assertEqual(receipt['tafsir']['context_mappings'], 7)
            self.assertTrue(receipt['tafsir']['app_packaged'])
            self.assertEqual(receipt['tafsir']['app_books'], ['ibn_kathir', 'al_tabari', 'al_saadi'])
            for checkpoint in ['device_verified', 'reference_comparison_verified', 'owner_checkpoint_complete']:
                self.assertFalse(receipt[checkpoint])
            passage = json.loads((output / 'app/quran.json').read_text())
            self.assertEqual(passage['schema_version'], 2)
            # The loader's accepted artifact identity is a packaging contract,
            # in addition to the independent source-row comparisons below.
            self.assertEqual(hashlib.sha256((output / 'app/quran.json').read_bytes()).hexdigest(),
                             'b98ccebd59936fe204274abb36538802b9b3abfe55013ac6af1879350efe3a99')
            self.assertEqual(len(passage['ayahs']), 6236)
            self.assertEqual(len(passage['surahs']), 114)
            self.assertEqual(receipt['quran']['app_ayahs'], 6236)
            self.assertEqual(passage['ayahs'][0]['unicode'], 'بِسۡمِ ٱللَّهِ ٱلرَّحۡمَٰنِ ٱلرَّحِيمِ')
            page = json.loads((output / 'source/page-1.json').read_text())
            self.assertNotEqual(passage['ayahs'][0]['unicode'], page['suras'][0]['texts'][0])
            self.assertTrue(all('page_glyphs' not in a for a in passage['ayahs']))
            self.assertTrue((output / 'tafsir/ATTRIBUTION.txt').is_file())
            manifest = json.loads((ROOT / 'docs/phase-1/artifact-manifest.json').read_text())
            for item in manifest['files']:
                if item['role'] == 'tafsir provenance/context':
                    self.assertEqual((output / item['destination']).read_bytes(),
                                     (Path(REFERENCE) / item['path']).read_bytes())
            with sqlite3.connect(f'file:{output}/source/offlinedb.db?mode=ro', uri=True) as db:
                expected = db.execute('SELECT surah,verse,text_madina FROM Quran ORDER BY surah,verse').fetchall()
            self.assertEqual([(a['surah'], a['ayah'], a['unicode']) for a in passage['ayahs']], expected)
            metadata = json.loads((output / 'inventory/content-followup/rea-surah-all.json').read_text())['normalized_result']['rows']
            rows = [{k: cell['value'] for k, cell in zip(metadata['columns'], row)} for row in metadata['values']]
            self.assertEqual(passage['surahs'], [dict(surah=int(r['id']), name=r['arabic'], ayah_count=int(r['ayah'])) for r in rows])
            self.assertEqual(set(p.name for p in (output / 'app').iterdir()), {'quran.json', 'UthmanicHafs1_Ver16.ttf', 'arabic-three-tafsirs.sqlite'})
            # Independent retained manifest framing, using real prepared SQLite.
            import struct
            contract = json.loads((ROOT / 'docs/phase-3/content-contract.json').read_text())
            retained_pack_manifest = json.loads((output / 'tafsir/manifest.json').read_text())
            ibn = next(book for book in retained_pack_manifest['books'] if book['id'] == 'ibn_kathir')
            self.assertEqual(contract['canonical_row_sha256'], ibn['canonical_row_sha256'])
            self.assertEqual(contract['pack_sha256'], retained_pack_manifest['artifact']['sha256'])
            pack = output / 'app/arabic-three-tafsirs.sqlite'
            self.assertEqual(pack.stat().st_size, contract['pack_bytes'])
            with pack.open('rb') as stream:
                self.assertEqual(hashlib.file_digest(stream, 'sha256').hexdigest(), contract['pack_sha256'])
            with sqlite3.connect(pack.as_uri() + '?mode=ro&immutable=1', uri=True) as db:
                keys = [(a['surah'], a['ayah']) for a in passage['ayahs']]
                row_hash = hashlib.sha256()
                for key in keys:
                    rows = db.execute('SELECT text,content_status FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah=? LIMIT 2', ('ibn_kathir', *key)).fetchall()
                    self.assertEqual(len(rows), 1)
                    text, status = rows[0]
                    self.assertEqual(status, 'source_text')
                    raw = text.encode('utf-8')
                    row_hash.update(struct.pack('>IIQ', *key, len(raw)))
                    row_hash.update(raw)
                self.assertEqual(row_hash.hexdigest(), contract['canonical_row_sha256'])
                for sample in contract['samples']:
                    text, = db.execute("SELECT text FROM tafseer_entries WHERE tafseer_id='ibn_kathir' AND surah=? AND ayah=?", (sample['surah'], sample['ayah'])).fetchone()
                    self.assertEqual(len(text), sample['characters'])
                    self.assertEqual(hashlib.sha256(text.encode('utf-8')).hexdigest(), sample['sha256'])
                plan = db.execute("EXPLAIN QUERY PLAN SELECT text,content_status FROM tafseer_entries WHERE tafseer_id='ibn_kathir' AND surah=1 AND ayah=1 LIMIT 2").fetchall()
                self.assertIn('SEARCH tafseer_entries USING PRIMARY KEY', str(plan))
            self.assertTrue(all(set(a) == {'surah', 'ayah', 'unicode'} for a in passage['ayahs']))
            # An agent receiving the generated handoff can detect later corruption.
            checked = subprocess.run(['python3', 'tools/prepare_artifacts.py', 'verify-prepared',
                '--output', str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            # Prepared pack corruption must fail before it can be bundled.
            with pack.open('r+b') as stream:
                original = stream.read(1)
                stream.seek(0)
                stream.write(b'!')
            checked = subprocess.run(['python3', 'tools/prepare_artifacts.py', 'verify-prepared',
                '--output', str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn('Prepared digest mismatch: app/arabic-three-tafsirs.sqlite', checked.stderr)
            with pack.open('r+b') as stream:
                stream.write(original)
            (output / 'app/quran.json').write_text('{}')
            checked = subprocess.run(['python3', 'tools/prepare_artifacts.py', 'verify-prepared',
                '--output', str(output)], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(checked.returncode, 0)
            self.assertIn('Prepared digest mismatch: app/quran.json', checked.stderr)

    def test_corrupt_source_is_rejected_before_any_output_is_written(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.local') as temp:
            reference = Path(temp) / 'reference'
            reference.mkdir()
            (reference / 'base.apk').write_bytes(b'corrupt retained bytes')
            output = Path(temp) / 'handoff'
            result = subprocess.run(['python3', 'tools/prepare_artifacts.py', 'prepare',
                '--reference-root', str(reference), '--output', str(output)],
                cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Digest mismatch: base.apk', result.stderr)
            self.assertFalse(output.exists())

    def test_existing_handoff_is_never_overwritten(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.local') as temp:
            output = Path(temp) / 'handoff'
            output.mkdir()
            marker = output / 'keep.txt'
            marker.write_text('preserved preparation')
            result = subprocess.run(['python3', 'tools/prepare_artifacts.py', 'prepare',
                '--reference-root', REFERENCE, '--output', str(output)],
                cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Output already exists', result.stderr)
            self.assertEqual(marker.read_text(), 'preserved preparation')

if __name__ == '__main__':
    unittest.main()
