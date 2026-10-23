"""Real production formatter on JVM, independent exact source oracle; no Android proof."""
import collections
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TafsirDisplayContract(unittest.TestCase):
    def test_all_source_characters_breaks_and_context_rows(self):
        with tempfile.TemporaryDirectory() as output:
            subprocess.run(['javac', '-encoding', 'UTF-8', '-d', output,
                            str(ROOT / 'android/app/src/main/java/com/xfocus/quranly/local/TafsirDisplay.java'),
                            str(ROOT / 'tests/java/TafsirDisplayProbe.java')], check=True)
            process = subprocess.Popen(['java', '-cp', output, 'TafsirDisplayProbe'],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)
            def render(raw):
                data = raw.encode('utf-8')
                process.stdin.write(struct.pack('>I', len(data)) + data)
                process.stdin.flush()
                header = process.stdout.read(4)
                self.assertEqual(len(header), 4, 'Production formatter exited')
                return process.stdout.read(struct.unpack('>I', header)[0]).decode('utf-8')
            try:
                # Source-shaped regression plus inert unknown syntax: no HTML
                # interpretation, BOM stripping, recursive entity decode or edits.
                self.assertEqual(render('\ufeff<br>القولُ ¬حاشية¥ <<br>>\r\n<p>نص</p></div>&nbsp;'),
                                 '\ufeff\nالقولُ ¬حاشية¥ <\n>\n\nنص\n\n\u00a0')
                literal = '\ufeffأ &lt; <b>ب</b> &amp; <br/> \ufeff'
                self.assertEqual(render(literal), literal)
                contract = json.loads((ROOT / 'docs/phase-4/content-contract.json').read_text())
                pack = ROOT / '.local/handoff/app/arabic-three-tafsirs.sqlite'
                with pack.open('rb') as stream:
                    self.assertEqual(hashlib.file_digest(stream, 'sha256').hexdigest(),
                                     '2422b6e57acb21184e14c15a86b36b23e58a140c78e3e7a17b45863524fb9150')
                tokens = collections.Counter()
                bom_count = 0
                with sqlite3.connect(f'file:{pack}?mode=ro&immutable=1', uri=True) as db:
                    def check_row(book, s, a, raw):
                        # Independent oracle: fixed literal replacements, unlike
                        # production's forward scanner. Compare exact Unicode,
                        # including whitespace and all source irregularities.
                        expected = raw.replace('\r\n', '\n').replace('\r', '\n')
                        for token in ('<br>', '<p>', '</p>', '</div>'):
                            expected = expected.replace(token, '\n')
                        expected = expected.replace('&nbsp;', '\u00a0')
                        self.assertEqual(render(raw), expected, f'{book} {s}:{a}')
                    for book, pinned in contract['books'].items():
                        digest = hashlib.sha256()
                        count = 0
                        for s, a, raw in db.execute('SELECT surah,ayah,text FROM tafseer_entries WHERE tafseer_id=? ORDER BY surah,ayah', (book,)):
                            check_row(book, s, a, raw)
                            data = raw.encode('utf-8')
                            digest.update(struct.pack('>IIQ', s, a, len(data)))
                            digest.update(data)
                            tokens.update(re.findall(r'<[^<>]*>|&[^&<>\s;]*;', raw))
                            bom_count += raw.count('\ufeff')
                            count += 1
                        self.assertEqual(count, 6236)
                        self.assertEqual(digest.hexdigest(), pinned['raw_rows_sha256'])
                    self.assertEqual(tokens, {'<br>': 94888, '<p>': 1, '</p>': 1, '</div>': 3, '&nbsp;': 4})
                    self.assertEqual(bom_count, 113)
                    for context in contract['contexts']:
                        rows = db.execute('SELECT ayah,text FROM tafseer_entries WHERE tafseer_id=? AND surah=? AND ayah BETWEEN ? AND ? ORDER BY ayah',
                                          (context['book'], context['surah'], context['from'], context['to']))
                        count = 0
                        for a, raw in rows:
                            check_row(context['book'], context['surah'], a, raw)
                            count += 1
                        self.assertEqual(count, len(context['source_rows']))
            finally:
                process.stdin.close()
                process.stdout.close()
                self.assertEqual(process.wait(timeout=10), 0)
