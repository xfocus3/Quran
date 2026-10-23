"""Fail closed on tracked credentials, private evidence and workstation identifiers."""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'credential': r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-)?[A-Za-z0-9_-]{32,}|AKIA[A-Z0-9]{16})',
    'private key': r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',
    'private host/path': r'192\.168\.\d+\.\d+|/home/xfocus/|/mnt/dev-workspace/',
}


def violations(name, data):
    parts = Path(name).parts
    if (any(part in {'.local', '.sandcastle', '.git', '.codex', 'node_modules',
                     'build', '__pycache__'} for part in parts) or
            Path(name).suffix.lower() in {'.apk', '.aab', '.jks', '.keystore', '.db',
                                         '.sqlite', '.ttf', '.zip', '.enc', '.pyc'} or
            Path(name).name in {'auth.json', 'hosts.yml', 'key.properties',
                                'local.properties', '.env'}):
        return ['private/generated path']
    # This scanner's own documented detectors are public, not credentials.
    if name == '.ci/public_boundary.py':
        return []
    text = data.decode('utf-8', errors='replace')
    return [label for label, pattern in PATTERNS.items() if re.search(pattern, text)]


def main():
    files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    failures = []
    for name in filter(None, files):
        path = ROOT / name
        if path.is_symlink() or path.stat().st_size > 1024 * 1024:
            failures.append((name, ['link/oversized tracked file']))
        else:
            found = violations(name, path.read_bytes())
            if found:
                failures.append((name, found))
    for name, reasons in failures:
        print(name + ': ' + ', '.join(reasons))
    if failures:
        return 1
    print(f'Public boundary passed for {len(list(filter(None, files)))} tracked files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
