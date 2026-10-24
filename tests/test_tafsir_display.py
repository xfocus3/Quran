"""Real production formatter on JVM, independent exact source oracle; no Android proof."""
import collections
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
# The same committed test runs in the private controller and selected-source CI.
HARNESS = ROOT / '.sandcastle/hosted/reader.py'
if not HARNESS.is_file():
    HARNESS = ROOT / '.ci/reader.py'
SPEC = importlib.util.spec_from_file_location('tafsir_expectations', HARNESS)
expectations = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(expectations)


class TafsirDisplayContract(unittest.TestCase):
    def test_authenticated_hosted_expectations_reject_other_book_or_key(self):
        owner = expectations.TafsirExpectations(ROOT, ROOT / '.local/handoff')
        self.assertEqual(len(owner.notices), 4)
        notices = [text for notice in owner.notices for text in (notice['title'], notice['text'])]
        traversal = expectations.TextTraversal(notices)
        self.assertTrue(traversal.observe(notices))
        traversal.finish()
        # Validate every declared sampled route before any negative assertion.
        # Full 27:59 coverage must not hide a broken source-return sample.
        self.assertEqual(set(owner.SAMPLES), {(book, key) for book in expectations.BOOK_TITLES
                                            for key in ('27:59', '2:282')})
        routes = []
        for book, key in owner.SAMPLES:
            entry = owner.entry(book, key)
            lines = entry['display'].split('\n')
            content = owner.content(book, key, full=False)
            expected = content['expected']
            self.assertEqual(content['scope'], 'sampled-source-lines')
            self.assertEqual(content['verified_line_indices'], list(owner.SAMPLES[(book, key)]))
            self.assertEqual(expected, [lines[i] for i in owner.SAMPLES[(book, key)]])
            self.assertEqual(content['raw_sha256'], entry['raw_sha256'])
            self.assertEqual(content['display_sha256'], expectations.digest(entry['display'].encode()))
            traversal = expectations.TextTraversal(expected)
            self.assertTrue(traversal.observe(lines), (book, key))
            traversal.finish()
            routes.append(content)
        for book in expectations.BOOK_TITLES:
            lines = owner.entry(book, '27:59')['display'].split('\n')
            content = owner.content(book, '27:59')
            expected = content['expected']
            self.assertEqual(content['scope'], 'all-nonempty-source-lines')
            self.assertEqual(content['verified_line_indices'], [i for i, line in enumerate(lines) if line])
            self.assertEqual(expected, [line for line in lines if line] + ['نهاية تفسير الآية 27:59'])
            traversal = expectations.TextTraversal(expected)
            self.assertTrue(traversal.observe(lines + ['نهاية تفسير الآية 27:59']), book)
            traversal.finish()
            routes.append(content)
        self.assertEqual(owner.entry('ibn_kathir', '27:59')['raw_sha256'],
                         '37dab0df8828b6f5760eaeeb8b956f74cb5995c2917b64fff3bf665bba819d18')
        for content in routes:
            book, key, expected = content['book'], content['key'], content['expected']
            with self.subTest(book=book, key=key, scope=content['scope']):
                stale_key = '27:58' if key == '27:59' else '2:281'
                for other_book, wrong_key in [(book, stale_key)] + [
                    (other, key) for other in expectations.BOOK_TITLES if other != book
                ]:
                    wrong = owner.entry(other_book, wrong_key)['display'].split('\n')
                    # Correct title and key, actual authenticated but wrong body.
                    traversal = expectations.TextTraversal(expected)
                    with self.assertRaisesRegex(AssertionError, 'incomplete|skipped|order differs'):
                        traversal.observe([expectations.BOOK_TITLES[book], 'تفسير الآية ' + key]
                                          + wrong + ['نهاية تفسير الآية ' + key])
                        traversal.finish()
                # Only the source's quote/heading cannot pass as loaded prose.
                lines = owner.entry(book, key)['display'].split('\n')
                # Authenticated quote/heading boundaries checked against the
                # pinned pack, independently of which anchors SAMPLES selects.
                prose_start = {('ibn_kathir', '27:59'): 2, ('al_tabari', '27:59'): 2,
                               ('al_saadi', '27:59'): 1, ('ibn_kathir', '2:282'): 2,
                               ('al_tabari', '2:282'): 3, ('al_saadi', '2:282'): 2}
                traversal = expectations.TextTraversal(expected)
                with self.assertRaisesRegex(AssertionError, 'incomplete'):
                    traversal.observe(lines[:prose_start[(book, key)]])
                    traversal.finish()

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
                        # Same independent literal oracle now owns hosted UI
                        # expectations too; still independent of the Java scanner.
                        expected = expectations.expected_tafsir_display(raw)
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
