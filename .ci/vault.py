"""Authenticated private build inputs/results; never print plaintext or keys."""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import tarfile

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HEADER = b'QURAN-CI-1\n'
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_EXPANDED = 1024 * 1024 * 1024


def seal(data, key):
    if len(data) > MAX_ARCHIVE:
        raise ValueError('Archive exceeds bound')
    nonce = os.urandom(12)
    return HEADER + nonce + AESGCM(key).encrypt(nonce, data, HEADER)


def unseal(data, key):
    if not data.startswith(HEADER) or len(data) > MAX_ARCHIVE + 64:
        raise ValueError('Invalid encrypted archive')
    nonce = data[len(HEADER):len(HEADER) + 12]
    return AESGCM(key).decrypt(nonce, data[len(HEADER) + 12:], HEADER)


def extract(data, destination):
    # Validate the entire archive before creating any output. Only regular files
    # and directories; no links, devices, duplicate paths or traversal aliases.
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = archive.getmembers()
        total = 0
        seen = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or
                    str(path) != member.name or '\\' in member.name or
                    not (member.isfile() or member.isdir()) or
                    member.name in seen):
                raise ValueError('Unsafe archive member')
            seen.add(member.name)
            total += member.size
            if total > MAX_EXPANDED or len(members) > 10000:
                raise ValueError('Expanded archive exceeds bound')
        if destination.exists():
            raise ValueError('Extraction requires a new destination')
        destination.mkdir(parents=True, mode=0o700)
        for member in members:
            target = destination / member.name
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with target.open('xb') as output:
                    output.write(archive.extractfile(member).read())
                target.chmod(0o600)


def pack(root):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for path in sorted(root.rglob('*')):
            if path.is_symlink():
                raise ValueError('Refusing symlink in private pack')
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
    return output.getvalue()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['seal', 'open', 'verify'])
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path, nargs='?')
    args = parser.parse_args()
    if args.command == 'verify':
        manifest = json.loads(args.source.read_text())
        root = args.destination
        for name, expected in manifest['files'].items():
            path = (root / name).resolve()
            if not path.is_relative_to(root.resolve()) or path.is_symlink():
                raise ValueError('Input path escapes root')
            if sha(path) != expected:
                raise ValueError('Input digest mismatch')
        print(f"Verified {len(manifest['files'])} pinned input files")
        return
    key = base64.b64decode(os.environ['QURAN_CI_KEY'], validate=True)
    if len(key) != 32:
        raise ValueError('Expected a 256-bit key')
    if args.command == 'seal':
        args.destination.parent.mkdir(parents=True, exist_ok=True)
        with args.destination.open('xb') as output:
            output.write(seal(pack(args.source), key))
        args.destination.chmod(0o600)
    else:
        extract(unseal(args.source.read_bytes(), key), args.destination)


if __name__ == '__main__':
    main()
