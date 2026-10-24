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
# Measured API35/36 bundles are 1,062,779,214 / 1,063,040,585 bytes
# before the wider reader captures. Keep 1.25 GiB expansion / 512 MiB sealed
# bounds rather than failing collection at the previous bundle's ~10 MiB margin.
MAX_EXPANDED = 1280 * 1024 * 1024
MAX_MEMBERS = 10000


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
        files = {PurePosixPath(member.name) for member in members if member.isfile()}
        for member in members:
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or
                    str(path) != member.name or '\\' in member.name or
                    not (member.isfile() or member.isdir()) or
                    member.name in seen or any(parent in files for parent in path.parents)):
                raise ValueError('Unsafe archive member')
            seen.add(member.name)
            total += member.size
            if total > MAX_EXPANDED or len(members) > MAX_MEMBERS:
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
    files = []
    total = 0
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Refusing symlink in private pack')
        if path.is_file():
            files.append(path)
            total += path.stat().st_size
            if total > MAX_EXPANDED or len(files) > MAX_MEMBERS:
                raise ValueError('Expanded archive exceeds bound')
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for path in files:
            archive.add(path, arcname=str(path.relative_to(root)), recursive=False)
    return output.getvalue()


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify(manifest, root):
    root = root.resolve()
    for name, expected in manifest['files'].items():
        relative = PurePosixPath(name)
        path = root / name
        if (relative.is_absolute() or '..' in relative.parts or str(relative) != name or
                '\\' in name or any(p.is_symlink() for p in (path, *path.parents)) or
                not path.resolve().is_relative_to(root)):
            raise ValueError('Input path escapes root or follows a link')
        if sha(path) != expected:
            raise ValueError('Input digest mismatch')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['seal', 'open', 'verify'])
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path, nargs='?')
    args = parser.parse_args()
    if args.command == 'verify':
        manifest = json.loads(args.source.read_text())
        verify(manifest, args.destination)
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
