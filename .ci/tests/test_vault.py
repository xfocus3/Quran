import io
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import vault


class VaultTest(unittest.TestCase):
    def test_authenticated_round_trip_and_corruption(self):
        key = os.urandom(32)
        data = b'private build fixture'
        sealed = vault.seal(data, key)
        self.assertNotIn(data, sealed)
        self.assertEqual(vault.unseal(sealed, key), data)
        for invalid in (sealed[:-1], sealed[:-1] + bytes([sealed[-1] ^ 1])):
            with self.assertRaises(Exception):
                vault.unseal(invalid, key)
        with self.assertRaises(Exception):
            vault.unseal(sealed, os.urandom(32))

    def test_reject_unsafe_archive_before_writing(self):
        for name, kind in [('../escape', tarfile.REGTYPE),
                           ('/absolute', tarfile.REGTYPE),
                           ('safe/link', tarfile.SYMTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode='w:gz') as archive:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    info.linkname = '/outside'
                    archive.addfile(info)
                destination = Path(tmp) / 'output'
                with self.assertRaises(ValueError):
                    vault.extract(stream.getvalue(), destination)
                self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
