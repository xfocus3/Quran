#!/usr/bin/env python3
"""Verify the existing handoff and prepare only selected members. No downloads/REA runtime.

All manifest source paths are relative to the caller-selected read-only reference
root. The private output may be deleted and regenerated. The exact existing tafsir database is packaged without rebuilding its corpus.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import struct
import sys
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / 'docs/phase-1/artifact-manifest.json'
CONTEXTS = [
    (4, 168, 168, 169, 169),
    (26, 16, 15, 17, 15),
    (26, 205, 205, 207, 206),
    (37, 25, 24, 27, 24),
    (37, 62, 62, 66, 63),
    (37, 103, 103, 106, 104),
    (50, 13, 12, 14, 12),
]
TAFSIR_BOOKS = ('ibn_kathir', 'al_tabari', 'al_saadi')
TAFSIR_DATABASE = 'tafseer-followup/arabic-three/arabic-three-tafsirs.sqlite'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f'Path escapes root: {relative}')
    return path


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def readonly(path):
    return sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)


def bmp_font_characters(path):
    """Read the shipped TrueType BMP cmap; this does not verify Arabic shaping."""
    data = path.read_bytes()
    require(data[:4] == b'\x00\x01\x00\x00', f'Expected TrueType font: {path.name}')
    tables = {}
    for index in range(struct.unpack_from('>H', data, 4)[0]):
        tag, _, offset, size = struct.unpack_from('>4sIII', data, 12 + index * 16)
        require(offset + size <= len(data), 'Font table outside file')
        tables[tag] = offset
    cmap = tables[b'cmap']
    characters = set()
    for index in range(struct.unpack_from('>H', data, cmap + 2)[0]):
        platform, encoding, offset = struct.unpack_from('>HHI', data, cmap + 4 + index * 8)
        start = cmap + offset
        if platform not in (0, 3) or (platform == 3 and encoding != 1):
            continue
        if struct.unpack_from('>H', data, start)[0] != 4:
            continue
        count = struct.unpack_from('>H', data, start + 6)[0] // 2
        ends = start + 14
        starts = ends + 2 * count + 2
        deltas = starts + 2 * count
        offsets = deltas + 2 * count
        for segment in range(count):
            end = struct.unpack_from('>H', data, ends + 2 * segment)[0]
            first = struct.unpack_from('>H', data, starts + 2 * segment)[0]
            delta = struct.unpack_from('>h', data, deltas + 2 * segment)[0]
            address = offsets + 2 * segment
            relative = struct.unpack_from('>H', data, address)[0]
            for code in range(first, min(end + 1, 0xFFFF)):
                glyph = code
                if relative:
                    glyph_address = address + relative + 2 * (code - first)
                    glyph = struct.unpack_from('>H', data, glyph_address)[0]
                    if glyph == 0:
                        continue
                glyph_id = (glyph + delta) % 65536
                if glyph_id:
                    characters.add(chr(code))
    require(characters, f'No supported Unicode BMP cmap: {path.name}')
    return characters


def verify_prepared(output):
    receipt = json.loads((output / 'receipt.json').read_text())
    require(receipt['schema_version'] == 3, 'Prepared schema differs; regenerate into a new handoff path')
    require(receipt['manifest_sha256'] == digest(MANIFEST), 'Prepared manifest differs; regenerate handoff')
    for relative, expected in receipt['outputs'].items():
        require(digest(checked_path(output, relative)) == expected,
                f'Prepared digest mismatch: {relative}')
    return receipt


def verify(root, manifest):
    for item in manifest['files']:
        path = checked_path(root, item['path'])
        require(digest(path) == item['sha256'], f"Digest mismatch: {item['path']}")
        if 'evidence_id' in item:
            require(json.loads(path.read_text())['evidence_id'] == item['evidence_id'],
                    f"Evidence identity mismatch: {item['path']}")
    with zipfile.ZipFile(root / 'base.apk') as archive:
        for item in manifest['members']:
            require(hashlib.sha256(archive.read(item['member'])).hexdigest() == item['sha256'],
                    f"Member digest mismatch: {item['member']}")
    tafsir = root / TAFSIR_DATABASE
    with readonly(tafsir) as db:
        require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'Tafsir integrity')
        require(not db.execute('PRAGMA foreign_key_check').fetchall(), 'Tafsir foreign keys')
        books = dict(db.execute('SELECT tafseer_id,count(*) FROM tafseer_entries GROUP BY tafseer_id'))
        require(books == dict.fromkeys(TAFSIR_BOOKS, 6236), 'Tafsir identities')
        contexts = db.execute('SELECT surah,ayah,from_ayah,to_ayah,heading_ayah FROM tafseer_context_ranges ORDER BY surah,ayah').fetchall()
        require(contexts == CONTEXTS, 'Seven context mappings differ')
        empty = db.execute("SELECT surah,ayah FROM tafseer_entries WHERE content_status='empty_markup' ORDER BY surah,ayah").fetchall()
        require(empty == [x[:2] for x in CONTEXTS], 'Empty markup identities differ')
    return {'lookup_identities':18708,'context_mappings':7,'app_books':list(TAFSIR_BOOKS),'app_packaged':False,'device_verified':False}


def read_quran(database, tafsir_database):
    """Validate Quran identities against each retained tafsir before selecting rows."""
    with readonly(database) as db:
        require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'Quran integrity')
        keys = db.execute('SELECT surah,verse FROM Quran ORDER BY surah,verse').fetchall()
        require(len(keys) == 6236 and len(set(keys)) == 6236, 'Quran identity count')
        for surah in range(1, 115):
            verses = [ayah for source_surah, ayah in keys if source_surah == surah]
            require(verses == list(range(1, len(verses) + 1)) and verses,
                    'Noncontiguous Quran keys')
        with readonly(tafsir_database) as tafsir_db:
            for book in TAFSIR_BOOKS:
                tafsir_keys = tafsir_db.execute(
                    'SELECT surah,ayah FROM tafseer_entries WHERE tafseer_id=? ORDER BY surah,ayah',
                    (book,),
                ).fetchall()
                require(tafsir_keys == keys, 'Quran/tafsir key mismatch')
        return db.execute(
            'SELECT surah,verse,text_madina FROM Quran ORDER BY surah,verse'
        ).fetchall()


def prepare_quran(stage, root, manifest):
    """Preserve source Unicode while checking the separate page-glyph/font pairing."""
    fonts = json.loads((stage / 'source/FontManifest.json').read_text())
    for family, asset in [
        ('madina2', 'assets/UthmanicHafs1_Ver16.ttf'),
        ('Mishaf1', 'assets/mishaf/QCF_P001.ttf'),
    ]:
        require(any(font['family'] == family and font['fonts'] == [{'asset': asset}]
                    for font in fonts), 'Font pairing differs')

    rows = read_quran(stage / 'source/offlinedb.db', root / TAFSIR_DATABASE)
    metadata = json.loads((stage / 'inventory/content-followup/rea-surah-all.json').read_text())
    retained = metadata['normalized_result']['rows']
    require(retained['returned_rows'] == 114 and not retained['truncated'], 'Incomplete surah metadata')
    surahs = []
    for cells in retained['values']:
        row = dict(zip(retained['columns'], (cell['value'] for cell in cells)))
        surahs.append({'surah': int(row['id']), 'name': row['arabic'], 'ayah_count': int(row['ayah'])})
    surahs.sort(key=lambda row: row['surah'])
    require([s['surah'] for s in surahs] == list(range(1, 115)), 'Surah metadata identities')
    require([(s, a) for s, a, _ in rows] == [
        (s['surah'], a) for s in surahs for a in range(1, s['ayah_count'] + 1)
    ], 'Surah metadata/Quran key mismatch')
    with readonly(stage / 'source/offlinedb.db') as db:
        declarations = db.execute('SELECT DISTINCT surah,surah_name_in_arab,total_verse_in_surah FROM Quran ORDER BY surah').fetchall()
    require(declarations == [(s['surah'], s['name'], str(s['ayah_count'])) for s in surahs],
            'Quran embedded metadata mismatch')
    require(all(isinstance(text, str) and text.strip() for _, _, text in rows), 'Empty Quran Unicode')
    page = json.loads((stage / 'source/page-1.json').read_text())['suras'][0]
    require(page['ayaNumbers'] == list(range(1, 8)) and len(page['texts']) == 7,
            'Al-Fatihah identity mapping')
    page_glyphs = page['texts']
    require(all(text != glyphs for (_, _, text), glyphs in zip(rows[:7], page_glyphs)),
            'Unicode/glyph separation')
    for field, texts, font in [
        ('unicode', [text for _, _, text in rows], stage / 'app/UthmanicHafs1_Ver16.ttf'),
        ('page_glyphs', page_glyphs, stage / 'source/QCF_P001.ttf'),
    ]:
        supported = bmp_font_characters(font)
        require(all(set(text) <= supported for text in texts),
                f'Font cmap missing {field} characters')

    # Page glyphs stay beside their font in source/, outside the app payload.
    database_digest = next(member['sha256'] for member in manifest['members']
                           if member['destination'] == 'source/offlinedb.db')
    passage = {
        'schema_version': 2,
        'surahs': surahs,
        'source_metadata_sha256': digest(stage / 'inventory/content-followup/rea-surah-all.json'),
        'source_database_sha256': database_digest,
        'unicode_column': 'text_madina',
        'unicode_font': 'madina2',
        'ayahs': [{'surah': s, 'ayah': a, 'unicode': text} for s, a, text in rows],
    }
    (stage / 'app/quran.json').write_text(json.dumps(passage, ensure_ascii=False, indent=2) + '\n')


def prepare(root, output, manifest):
    require(not output.exists(), f'Output already exists: {output}; use a new path or remove only this generated handoff')
    require(not output.is_relative_to(root) and not root.is_relative_to(output),
            'Output must be separate from reference root')
    tafsir = verify(root, manifest)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.handoff-', dir=output.parent) as temp:
        stage = Path(temp) / 'handoff'
        stage.mkdir()
        for item in manifest['files']:
            if 'destination' in item:
                target = checked_path(stage, item['destination'])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / item['path'], target)
                require(digest(target) == item['sha256'], 'Source changed during preparation')
        with zipfile.ZipFile(root / 'base.apk') as archive:
            for item in manifest['members']:
                target = checked_path(stage, item['destination'])
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item['member']))
                require(digest(target) == item['sha256'], 'Selected member changed during preparation')
        prepare_quran(stage, root, manifest)
        # Byte-for-byte copy, no corpus serialization or regeneration.
        pack = stage / 'app/arabic-three-tafsirs.sqlite'
        shutil.copyfile(root / TAFSIR_DATABASE, pack)
        expected = next(x['sha256'] for x in manifest['files'] if x['path'] == TAFSIR_DATABASE)
        require(digest(pack) == expected, 'Tafsir changed during preparation')
        tafsir['app_packaged'] = True
        receipt = {'schema_version':3,'manifest_sha256':digest(MANIFEST),
                   'quran':{'identities':6236,'app_ayahs':6236,'app_surahs':114,'unicode_column':'text_madina'},'tafsir':tafsir,
                   'outputs':{str(p.relative_to(stage)):digest(p) for p in sorted(stage.rglob('*')) if p.is_file()},
                   'device_verified':False,'reference_comparison_verified':False,'owner_checkpoint_complete':False}
        (stage/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        stage.rename(output)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['verify','prepare','verify-prepared'])
    parser.add_argument('--reference-root', type=Path)
    parser.add_argument('--output', type=Path, default=REPO/'.local/handoff')
    args = parser.parse_args()
    try:
        manifest = json.loads(MANIFEST.read_text())
        if args.command == 'verify-prepared':
            result = verify_prepared(args.output.resolve())
        else:
            require(args.reference_root is not None, '--reference-root is required')
            root = args.reference_root.resolve(strict=True)
            if args.command == 'prepare':
                result = prepare(root, args.output.resolve(), manifest)
            else:
                result = verify(root, manifest)
        print(json.dumps({'status':'verified','result':result},indent=2))
    except (ValueError,OSError,sqlite3.Error,zipfile.BadZipFile,KeyError) as error:
        print(f'Artifact preparation failed: {error}',file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
