"""Reject missing, extra or changed app files relative to the export receipt."""
import hashlib
import json
from pathlib import Path
import subprocess

from export_source import selected


def verify(root):
    receipt = json.loads((root / '.ci/source.json').read_text())
    tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    if set(receipt['files']) != {name for name in tracked if selected(name)}:
        raise ValueError('Export receipt does not cover exactly the tracked app source')
    for name, expected in receipt['files'].items():
        path = root / name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Changed exported source: ' + name)
    print(f"Verified {len(receipt['files'])} exact exported source files")


if __name__ == '__main__':
    verify(Path(__file__).resolve().parents[1])
