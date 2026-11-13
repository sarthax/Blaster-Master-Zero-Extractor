"""Metadata-only IRLST/IRARC archive inventory.

Reports decoded structure metadata and fingerprints, never saves game payloads.
Do not interpret an unrecognized section as a texture without validation.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import struct

from .inti import Source, open_pair, open_loose
from tools.decode_irarc_graphics import parse_iobj, read_texture

KNOWN_SIGNATURES = {b'IOBJ', b'TLPI', b'ICDB', b'CGFX'}
CSV_FIELDS = ('source', 'index', 'resource_id', 'entry_kind', 'packed_bytes',
              'unpacked_bytes', 'resource_sha256', 'classification', 'sections',
              'textures', 'palettes', 'frames', 'dimensions', 'status', 'error')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_resource(blob: bytes) -> dict:
    """Inspect a decompressed resource without constructing any PIL images."""
    if len(blob) < 4:
        raise ValueError('resource shorter than section count')
    section_count = struct.unpack_from('<I', blob)[0]
    if section_count > 512 or 4 + section_count * 16 > len(blob):
        raise ValueError('invalid resource section table')

    records = []
    for number in range(section_count):
        code, flags, start, length = struct.unpack_from('<IIII', blob, 4 + number * 16)
        if length < 16 or start < 4 + section_count * 16 or start + length > len(blob):
            raise ValueError(f'section {number}: invalid offset/length')
        body = blob[start:start + length]
        raw_sig = body[:4]
        if raw_sig in KNOWN_SIGNATURES:
            signature = raw_sig.decode('ascii')
        else:
            # The prior graphics parser called all unknown signatures PIXEL.
            # Here a texture is PIXEL only if its dimensions/format validate.
            try:
                read_texture(body, 0)
                signature = 'PIXEL'
            except (ValueError, struct.error):
                signature = 'UNKNOWN'
        records.append({
            'ordinal': number, 'code': code, 'flags': flags,
            'offset': start, 'length': length, 'signature': signature,
            'magic_hex': raw_sig.hex(),
        })

    signatures = [item['signature'] for item in records]
    info = {'classification': '+'.join(signatures) if signatures else 'EMPTY',
            'sections': records, 'textures': 0, 'palettes': 0, 'frames': 0,
            'dimensions': [], 'status': 'unrecognized', 'error': ''}

    if 'IOBJ' in signatures:
        record = records[signatures.index('IOBJ')]
        body = blob[record['offset']:record['offset'] + record['length']]
        textures, frames = parse_iobj(body)
        info['textures'] = len(textures)
        info['frames'] = len(frames)
        info['dimensions'] = [f'{w}x{h}' for w, h, _fmt, _pix in textures]
        info['status'] = 'metadata_ok'
    elif signatures and all(sig == 'PIXEL' for sig in signatures):
        info['dimensions'] = []
        for record in records:
            w, h, _fmt, _pix = read_texture(
                blob[record['offset']:record['offset'] + record['length']], 0)
            info['dimensions'].append(f'{w}x{h}')
        info['textures'] = len(records)
        info['status'] = 'metadata_ok'

    if 'TLPI' in signatures:
        record = records[signatures.index('TLPI')]
        body = blob[record['offset']:record['offset'] + record['length']]
        if len(body) < 16:
            raise ValueError('TLPI header truncated')
        count, colors = struct.unpack_from('<HH', body, 4)
        if colors != 256 or not (1 <= count <= 256) or 16 + count * colors * 4 > len(body):
            raise ValueError('TLPI palette table invalid')
        info['palettes'] = count
    return info


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _find_sources(path: Path, recursive: bool) -> tuple[list[Source], list[dict]]:
    """Continue past bad pairs and include their errors in the report."""
    failures: list[dict] = []
    if path.is_file():
        if path.suffix.lower() == '.irarc':
            indices = [p for p in path.parent.iterdir() if p.is_file()
                       and p.stem.casefold() == path.stem.casefold()
                       and p.suffix.casefold() == '.irlst']
            if not indices:
                return [], [{'path': path.name, 'error': 'unpaired .irarc archive'}]
            path = indices[0]
        if path.suffix.lower() == '.irlst':
            try:
                return [open_pair(path)], failures
            except (OSError, ValueError) as exc:
                return [], [{'path': path.name, 'error': str(exc).replace(str(path), path.name)}]
        if path.suffix.lower() == '.17':
            return [open_loose(path.parent)], failures
        raise ValueError('Expected a .irlst, .irarc, .17 file, or directory')
    if not path.is_dir():
        raise FileNotFoundError(path)
    files = (p for p in (path.rglob('*') if recursive else path.iterdir()) if p.is_file())
    candidates = list(files)
    indices = sorted((p for p in candidates if p.suffix.casefold() == '.irlst'),
                     key=lambda p: str(p).casefold())
    archives = sorted((p for p in candidates if p.suffix.casefold() == '.irarc'),
                      key=lambda p: str(p).casefold())
    index_names = {(p.parent, p.stem.casefold()) for p in indices}
    for archive in archives:
        if (archive.parent, archive.stem.casefold()) not in index_names:
            failures.append({'path': _safe_rel(archive, path), 'error': 'unpaired .irarc archive'})
    sources = []
    for index in indices:
        try:
            sources.append(open_pair(index))
        except (OSError, ValueError) as exc:
            failures.append({'path': _safe_rel(index, path),
                             'error': str(exc).replace(str(index), _safe_rel(index, path))})
    if not indices and not archives:
        try:
            sources = [open_loose(path, recursive)]
        except ValueError:
            pass
    return sources, failures


def scan_path(path: Path, recursive: bool = True,
              max_unpacked_mib: int = 256) -> dict:
    """Inventory every readable pair; record unreadable pairs and resource errors."""
    path = Path(path).expanduser().resolve()
    if not 1 <= max_unpacked_mib <= 4096:
        raise ValueError('max_unpacked_mib must be between 1 and 4096')
    root = path if path.is_dir() else path.parent
    sources, failures = _find_sources(path, recursive)
    result = {'schema_version': 1, 'format_hint': 'IRLST/IRARC (BMZ PC tested)',
              'sources': [], 'resources': [], 'pair_errors': failures, 'summary': {}}
    statuses = Counter()
    classifications = Counter()
    signatures = Counter()
    for source in sources:
        source_path = _safe_rel(source.path, root)
        src = {'name': source.label, 'index_path': source_path,
               'index_sha256': sha256_file(source.path), 'entries': len(source.entries),
               'archive_path': None, 'archive_sha256': None, 'archive_bytes': None}
        if source.archive:
            src['archive_path'] = _safe_rel(source.archive, root)
            src['archive_sha256'] = sha256_file(source.archive)
            src['archive_bytes'] = source.archive.stat().st_size
        result['sources'].append(src)
        for entry in source.entries:
            row = {'source': source_path, 'index': entry.ordinal,
                   'resource_id': f'0x{entry.resource_id:08X}',
                   'entry_kind': f'0x{entry.kind:02X}',
                   'packed_bytes': entry.packed_size, 'unpacked_bytes': 0,
                   'resource_sha256': '', 'classification': '', 'sections': [],
                   'textures': 0, 'palettes': 0, 'frames': 0,
                   'dimensions': [], 'status': 'read_error', 'error': ''}
            try:
                payload = source.get_data(entry, max_unpacked_mib * 1024 * 1024)
                row['unpacked_bytes'] = len(payload)
                row['resource_sha256'] = hashlib.sha256(payload).hexdigest()
                try:
                    row.update(inspect_resource(payload))
                except (ValueError, struct.error, IndexError, OverflowError) as exc:
                    row['status'] = 'parse_error'
                    row['error'] = str(exc)
            except (OSError, ValueError, struct.error) as exc:
                row['error'] = str(exc)
            statuses[row['status']] += 1
            classifications[row['classification']] += 1
            for section in row['sections']:
                signatures[section['signature']] += 1
            result['resources'].append(row)
    result['summary'] = {'sources': len(result['sources']),
                         'resources': len(result['resources']),
                         'pair_errors': len(result['pair_errors']),
                         'statuses': dict(sorted(statuses.items())),
                         'classifications': dict(sorted(classifications.items())),
                         'section_signatures': dict(sorted(signatures.items()))}
    return result


def write_reports(report: dict, json_path: Path) -> tuple[Path, Path]:
    json_path = Path(json_path)
    if json_path.suffix.lower() != '.json':
        raise ValueError('Output must be a .json filename')
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path = json_path.with_suffix('.csv')
    with json_path.open('w', encoding='utf-8', newline='\n') as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write('\n')
    with csv_path.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS, extrasaction='ignore')
        writer.writeheader()
        for resource in report['resources']:
            record = dict(resource)
            record['sections'] = '|'.join(x['signature'] for x in record['sections'])
            record['dimensions'] = '|'.join(record['dimensions'])
            writer.writerow(record)
    return json_path, csv_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Read-only Inti archive metadata inventory')
    parser.add_argument('input', type=Path, help='Game resarc folder or .irlst/.irarc file')
    parser.add_argument('-o', '--output', type=Path, default=Path('inti_inventory.json'),
                        help='JSON report path; companion CSV written alongside')
    parser.add_argument('--shallow', action='store_true', help='Do not search subfolders')
    parser.add_argument('--max-unpacked-mib', type=int, default=256)
    args = parser.parse_args(argv)
    try:
        result = scan_path(args.input, recursive=not args.shallow,
                           max_unpacked_mib=args.max_unpacked_mib)
        json_path, csv_path = write_reports(result, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Inventory failed: {exc}\n')
    summary = result['summary']
    print(f"Scanned {summary['sources']} sources, {summary['resources']} resources, "
          f"{summary['pair_errors']} invalid pairs")
    print(f"Report: {json_path}\nCSV: {csv_path}")
    return 0 if summary['sources'] and not summary['pair_errors'] and not (
        summary['statuses'].get('read_error') or summary['statuses'].get('parse_error')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
