import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import export_source


class ExportTest(unittest.TestCase):
    def test_committed_source_only_and_private_content_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src, dst = root / 'source', root / 'public'
            src.mkdir(); dst.mkdir()
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=src, text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (src / 'lib').mkdir()
            (src / 'lib/main.dart').write_text('committed reader')
            (src / 'auth.json').write_text('private fixture')
            git('add', '.'); git('commit', '-qm', 'test: source fixture')
            head = git('rev-parse', 'HEAD')
            (src / 'lib/main.dart').write_text('dirty source must not export')
            export_source.export(src, head, dst)
            self.assertEqual((dst / 'lib/main.dart').read_text(), 'committed reader')
            self.assertFalse((dst / 'auth.json').exists())
            receipt = json.loads((dst / '.ci/source.json').read_text())
            self.assertEqual(receipt['candidate_commit'], head)
            self.assertFalse(receipt['candidate_accepted'])
            (src / 'lib/main.dart').write_text('gh' + 'p_' + 'a' * 36)
            git('add', '.'); git('commit', '-qm', 'test: unsafe fixture')
            with self.assertRaises(ValueError):
                export_source.export(src, git('rev-parse', 'HEAD'), dst)
            self.assertEqual((dst / 'lib/main.dart').read_text(), 'committed reader')


if __name__ == '__main__':
    unittest.main()
