"""Prepared SQLite/data contracts; native production adapter still needs Android."""
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ThreeBookContract(unittest.TestCase):
    def test_exact_prepared_pack_all_keys_and_ordered_context_sources(self):
        checked = subprocess.run(['python3', 'tools/prepare_artifacts.py', 'verify-prepared'],
                                 cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        contract = json.loads((ROOT / 'docs/phase-4/content-contract.json').read_text())
        keys = [(a['surah'], a['ayah']) for a in json.loads(
            (ROOT / '.local/handoff/app/quran.json').read_text())['ayahs']]
        with sqlite3.connect('file:' + str(ROOT / '.local/handoff/app/arabic-three-tafsirs.sqlite') + '?mode=ro&immutable=1', uri=True) as db:
            for book, pinned in contract['books'].items():
                digest = hashlib.sha256()
                rows = db.execute('SELECT surah,ayah,text,content_status FROM tafseer_entries WHERE tafseer_id=? ORDER BY surah,ayah', (book,))
                actual_keys = []
                empty = []
                for s, a, text, status in rows:
                    actual_keys.append((s, a))
                    raw = text.encode('utf-8')
                    digest.update(struct.pack('>IIQ', s, a, len(raw)))
                    digest.update(raw)
                    if status == 'empty_markup':
                        empty.append((s, a))
                        self.assertEqual(text, '<br>')
                    else:
                        self.assertEqual(status, 'source_text')
                self.assertEqual(actual_keys, keys)
                self.assertEqual(len(actual_keys), pinned['count'])
                self.assertEqual(digest.hexdigest(), pinned['raw_rows_sha256'])
                self.assertEqual(empty, [(c['surah'], c['selected']) for c in contract['contexts']] if book == 'al_tabari' else [])
                s, a, length = pinned['longest']
                text, = db.execute('SELECT text FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah=?', (book, s, a)).fetchone()
                self.assertEqual(len(text), length)
            for c in contract['contexts']:
                s, a = c['surah'], c['selected']
                actual = db.execute('SELECT from_ayah,to_ayah,heading_ayah,heading_text,basis FROM tafseer_context_ranges WHERE tafseer_id=? AND surah=? AND ayah=?', (c['book'], s, a)).fetchone()
                self.assertEqual(actual[:3], (c['from'], c['to'], c['heading']))
                self.assertEqual(hashlib.sha256(actual[3].encode()).hexdigest(), c['heading_sha256'])
                self.assertEqual(actual[4], c['basis'])
                rows = db.execute('SELECT ayah,text,content_status FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah BETWEEN ? AND ? ORDER BY ayah LIMIT 6', (c['book'], s, c['from'], c['to'])).fetchall()
                self.assertEqual(len(rows), len(c['source_rows']))
                for (a, text, status), pinned in zip(rows, c['source_rows']):
                    self.assertEqual((a, status, len(text), hashlib.sha256(text.encode()).hexdigest()),
                                     (pinned['ayah'], pinned['status'], pinned['characters'], pinned['sha256']))
            queries = [
                ("SELECT text,content_status FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah=? LIMIT 2", ('al_tabari', 4, 168)),
                ("SELECT from_ayah,to_ayah FROM tafseer_context_ranges WHERE tafseer_id=? AND surah=? AND ayah=? LIMIT 2", ('al_tabari', 4, 168)),
                ("SELECT ayah,text,content_status FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah BETWEEN ? AND ? ORDER BY ayah LIMIT 6", ('al_tabari', 4, 168, 169)),
            ]
            for sql, parameters in queries:
                plan = str(db.execute('EXPLAIN QUERY PLAN ' + sql, parameters).fetchall())
                self.assertIn('SEARCH', plan)
                self.assertNotIn('SCAN', plan)
                self.assertNotIn('TEMP B-TREE', plan)
