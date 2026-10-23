"""Export selected committed app source; never export a private Git history."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess

from public_boundary import violations

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = ('lib/', 'android/', 'test/', 'tests/')
FILES = {
    '.nvmrc', 'analysis_options.yaml', 'pubspec.yaml', 'pubspec.lock',
    'tools/prepare_artifacts.py', 'tools/prepare_reader_artifacts.py',
    'docs/phase-1/artifact-manifest.json', 'docs/phase-3/content-contract.json',
    'docs/phase-4/content-contract.json', 'docs/issue-30/asset-manifest.json',
}


def selected(name):
    path = PurePosixPath(name)
    return (not path.is_absolute() and '..' not in path.parts and
            str(path) == name and '\\' not in name and
            (name in FILES or name.startswith(PREFIXES)))


def export(source, ref, destination):
    source, destination = Path(source), Path(destination)
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=source)
    head = git('rev-parse', '--verify', ref + '^{commit}').decode().strip()
    staged = {}
    for entry in git('ls-tree', '-rz', head).split(b'\0'):
        if not entry:
            continue
        meta, raw_name = entry.split(b'\t', 1)
        name = raw_name.decode('utf-8')
        if not selected(name):
            continue
        mode, kind, oid = meta.split()
        if mode not in (b'100644', b'100755') or kind != b'blob':
            raise ValueError('Selected source contains a link or non-file')
        data = git('cat-file', 'blob', oid.decode())
        if len(data) > 1024 * 1024 or violations(name, data):
            raise ValueError('Selected source violates the public boundary: ' + name)
        staged[name] = (data, mode == b'100755')
    if not staged:
        raise ValueError('No selected app source at the requested commit')
    receipt_path = destination / '.ci/source.json'
    previous = json.loads(receipt_path.read_text())['files'] if receipt_path.exists() else {}
    # Validate destination ownership before changing any file. Never follow a
    # symlink in an existing checkout or delete files outside this export's scope.
    for name in set(staged) | {name for name in previous if selected(name)} | {'.ci/source.json'}:
        path = destination / name
        if any(parent.is_symlink() for parent in (path, *path.parents)):
            raise ValueError('Refusing a linked export destination')
    for name in previous:
        if selected(name) and name not in staged:
            (destination / name).unlink(missing_ok=True)
    for name, (data, executable) in staged.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if executable else 0o644)
    receipt = {
        'schema': 1, 'candidate_commit': head, 'candidate_accepted': False,
        'files': {name: hashlib.sha256(data).hexdigest()
                  for name, (data, _) in sorted(staged.items())},
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-repo', type=Path, required=True)
    parser.add_argument('--ref', required=True)
    parser.add_argument('--destination', type=Path, default=ROOT)
    args = parser.parse_args()
    result = export(args.source_repo, args.ref, args.destination)
    print(f"Exported {len(result['files'])} committed app files")
