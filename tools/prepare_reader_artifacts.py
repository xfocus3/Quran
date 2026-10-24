"""Narrow issue-30 presentation handoff; reuse the already prepared corpus.

No downloads, bulk extraction, personal data, translations or corpus changes.
The original juz_no is sparse; validate/derive context from contiguous juz text
at this producing boundary. The consumer never guesses it from labels/pages.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import zipfile

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/issue-30/asset-manifest.json'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def derive_metadata(database):
    manifest = json.loads(MANIFEST.read_text())
    if digest(database) != manifest['database_sha256']:
        raise ValueError('Original database identity mismatch')
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        rows = db.execute('SELECT surah,verse,surah_name_in_latin,'
                          'surah_name_in_english,juz FROM Quran ORDER BY ID').fetchall()
    if len(rows) != 6236:
        raise ValueError('Quran identity coverage mismatch')
    surahs, juz = [], []
    last_surah = last_verse = last_juz = 0
    for index, (surah, verse, latin, english, juz_text) in enumerate(rows):
        number = int(juz_text)
        if surah != last_surah:
            if surah != last_surah + 1 or verse != 1 or not latin or not english:
                raise ValueError('Invalid chapter metadata')
            surahs.append({'number': surah, 'latin': latin, 'english': english})
            last_surah, last_verse = surah, 0
        if verse != last_verse + 1:
            raise ValueError('Noncontiguous ayah identities')
        last_verse = verse
        if (latin, english) != (surahs[-1]['latin'], surahs[-1]['english']):
            raise ValueError('Inconsistent chapter labels')
        if number != last_juz:
            if number != last_juz + 1:
                raise ValueError('Noncontiguous juz membership')
            juz.append({'number': number, 'offset': index})
            last_juz = number
    if len(surahs) != 114 or len(juz) != 30 or rows[-1][:2] != (114, 6):
        raise ValueError('Incomplete metadata')
    return (json.dumps({'schema': 1, 'database_sha256': manifest['database_sha256'],
                        'surahs': surahs, 'juz_starts': juz}, ensure_ascii=False,
                       separators=(',', ':')) + '\n').encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'verify'])
    parser.add_argument('--reference-root', type=Path, required=True)
    parser.add_argument('--handoff', type=Path, default=ROOT / '.local/handoff')
    parser.add_argument('--output', type=Path, default=ROOT / '.local/reader')
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    apk = args.reference_root / 'base.apk'
    if digest(apk) != manifest['apk_sha256']:
        raise ValueError('Original APK identity mismatch')
    metadata = derive_metadata(args.handoff / 'source/offlinedb.db')
    if args.command == 'prepare':
        args.output.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(apk) as archive:
            for item in manifest['files']:
                data = archive.read(item['member'])
                if hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise ValueError('Original member identity mismatch')
                (args.output / item['output']).write_bytes(data)
        (args.output / 'metadata.json').write_bytes(metadata)
    # The whole directory is a Flutter asset entry. Reject stale presentation
    # files, including superseded raster arrows, rather than bundling them.
    expected_files = {item['output'] for item in manifest['files']} | {'metadata.json'}
    if {path.name for path in args.output.iterdir()} != expected_files:
        raise ValueError('Prepared presentation file set differs from manifest')
    for item in manifest['files']:
        if digest(args.output / item['output']) != item['sha256']:
            raise ValueError('Prepared member identity mismatch')
    if (args.output / 'metadata.json').read_bytes() != metadata:
        raise ValueError('Prepared metadata differs from original source')
    receipt = {'status': 'verified', 'manifest_sha256': digest(MANIFEST),
               'metadata_sha256': hashlib.sha256(metadata).hexdigest(),
               'surahs': 114, 'juz': 30, 'source_keys_examined': 6236,
               'asset_count': len(manifest['files']), 'device_verified': False}
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
