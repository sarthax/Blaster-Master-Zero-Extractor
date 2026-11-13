#!/usr/bin/env python3
"""Extract and decompress Inti Creates IRLST / IRARC resource pairs.

Compatible with the archive layout used by Blaster Master Zero and various
Gunvolt titles. Python 3.9+; no third-party dependencies.

Examples (Windows PowerShell / CMD):
  py extract_irarc.py "C:\\Game\\data\\resarc\\resarc_cmm.irlst"
  py extract_irarc.py "C:\\Game\\data\\resarc" -o "C:\\Extracted"
  py extract_irarc.py "C:\\Game\\data" --recursive -o "C:\\Extracted"
  py extract_irarc.py "C:\\Game\\data\\resarc" --list
  py extract_irarc.py "C:\\Game\\data\\resarc" --raw

Reference: https://github.com/rufaswan/Web2D_Games/
  blob/053e9ad099b4e6247dad5652429baa03db1a7891/tools/psxtools/
  pc_gunvolt_irlst-irarc.php
The LZ-style back-reference format and the four-field index layout were
previously described by community reverse engineers.

This is an extractor for entries, not a conversion tool for the embedded
IOBJ/texture/model resource formats.
"""

import argparse
import csv
from pathlib import Path
import struct
import sys

COMPRESSED_TYPES = {0x12, 0x17}
INDEX_RECORD = struct.Struct('<IIII')  # ID, archive offset, archive size, type
WRAPPER_SIZE = 0x18  # compressed entry header length


def find_partner(index_path):
    """Find .irarc with identical basename (case-insensitive for Windows)."""
    wanted = index_path.stem.casefold()
    for candidate in index_path.parent.iterdir():
        if candidate.is_file() and candidate.stem.casefold() == wanted and candidate.suffix.casefold() == '.irarc':
            return candidate
    raise FileNotFoundError(f'No matching .irarc for {index_path}')


def index_file_for(path):
    if path.suffix.casefold() == '.irlst':
        return path
    if path.suffix.casefold() == '.irarc':
        for candidate in path.parent.iterdir():
            if candidate.is_file() and candidate.stem.casefold() == path.stem.casefold() and candidate.suffix.casefold() == '.irlst':
                return candidate
        raise FileNotFoundError(f'No matching .irlst for {path}')
    raise ValueError(f'Expected an .irlst file, .irarc file or folder: {path}')


def discover(input_path, recursive):
    if input_path.is_file():
        return [index_file_for(input_path)], False
    if not input_path.is_dir():
        raise FileNotFoundError(f'Not a file or directory: {input_path}')
    finder = input_path.rglob if recursive else input_path.glob
    files = sorted((p for p in finder('*') if p.is_file() and p.suffix.casefold() == '.irlst'), key=lambda p: str(p).lower())
    if not files:
        raise ValueError(f'No .irlst files in {input_path}' + (' (recursively)' if recursive else ''))
    return files, True


def load_index(index_path, archive_size):
    buf = index_path.read_bytes()
    if len(buf) < 4:
        raise ValueError(f'Index too small: {index_path}')
    count = struct.unpack_from('<I', buf, 0)[0]
    if len(buf) != 4 + count * INDEX_RECORD.size:
        raise ValueError(f'Invalid index length: count={count}, bytes={len(buf)}; expected={4 + count * INDEX_RECORD.size}')

    entries = []
    for i in range(count):
        resource_id, offset, size, kind = INDEX_RECORD.unpack_from(buf, 4 + i * INDEX_RECORD.size)
        if offset > archive_size or size > archive_size - offset:
            raise ValueError(f'Entry #{i} points outside .irarc (offset={offset}, size={size}, archive={archive_size})')
        entries.append((i, resource_id, offset, size, kind))
    return entries


def decode_lz(packed, max_output):
    """Decode a type 0x12/0x17 entry, including its 24-byte wrapper.

    Wrapper: first u32 is 0x18, and little-endian u32 at +0x0C is the
    expected uncompressed byte count. Bit flags are used LSB-first:
    0=literal byte, 1=two-byte back-reference. Back-reference distance is
    1..4096, and match length is 2..17, with overlapping copies allowed.
    """
    if len(packed) < WRAPPER_SIZE:
        raise ValueError('Missing 24-byte compressed-entry wrapper')
    wrapper_len = struct.unpack_from('<I', packed, 0)[0]
    expected_size = struct.unpack_from('<I', packed, 12)[0]
    if wrapper_len != WRAPPER_SIZE:
        raise ValueError(f'Unknown compressed wrapper length {wrapper_len:#x}; expected 0x18')
    if expected_size > max_output:
        raise ValueError(f'Declared uncompressed size {expected_size:,} exceeds safety limit {max_output:,}')

    decoded = bytearray()
    cursor = WRAPPER_SIZE
    end = len(packed)
    flags = 0
    bits_left = 0
    while cursor < end:
        if bits_left == 0:
            flags = packed[cursor]
            cursor += 1
            bits_left = 8
            continue
        if flags & 1:
            if cursor + 2 > end:
                raise ValueError('Incomplete LZ back-reference at end of entry')
            first, second = packed[cursor], packed[cursor + 1]
            cursor += 2
            distance = 1 + ((second & 0x0F) << 8) + first
            length = (second >> 4) + 2
            if distance > len(decoded):
                raise ValueError(f'Invalid back-reference distance {distance} at byte {cursor}')
            if len(decoded) + length > expected_size:
                raise ValueError('Decoded output exceeds declared size')
            for _ in range(length):
                decoded.append(decoded[-distance])
        else:
            if cursor >= end:
                raise ValueError('Incomplete LZ literal at end of entry')
            if len(decoded) >= expected_size:
                raise ValueError('Decoded output exceeds declared size')
            decoded.append(packed[cursor])
            cursor += 1
        flags >>= 1
        bits_left -= 1

    if len(decoded) != expected_size:
        raise ValueError(f'Decompressed {len(decoded):,} bytes; expected {expected_size:,}')
    return decoded


def process_pair(index_path, out_dir, args):
    archive_path = find_partner(index_path)
    with archive_path.open('rb') as file:
        file.seek(0, 2)
        archive_size = file.tell()
    entries = load_index(index_path, archive_size)
    print(f'\n{index_path.name} + {archive_path.name}: {len(entries)} entries, {archive_size:,} archive bytes')

    if args.list:
        print('  #     resource ID   type    offset      packed bytes')
        for i, rid, offset, size, kind in entries:
            print(f'{i:4d}   0x{rid:08X}    0x{kind:02X}   0x{offset:08X}   {size:>10,}')
        return (len(entries), 0)

    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    successes = 0
    errors = 0
    manifest = []
    with archive_path.open('rb') as source:
        for i, rid, offset, size, kind in entries:
            # IDs can repeat in other games: keep the original ID but disambiguate.
            key = (rid, kind)
            occurrence = counts.get(key, 0)
            counts[key] = occurrence + 1
            suffix = f'_{i:04d}' if occurrence else ''
            extension = f'{kind:x}'
            filename = f'{rid:08X}{suffix}.{extension}' + ('.packed' if args.raw else '')
            destination = out_dir / filename
            row = {'index': i, 'id_hex': f'0x{rid:08X}', 'id_decimal': rid,
                   'type_hex': f'0x{kind:02X}', 'offset_hex': f'0x{offset:X}',
                   'packed_bytes': size, 'unpacked_bytes': '', 'output_file': filename,
                   'status': '', 'error': ''}
            try:
                if destination.exists() and not args.overwrite:
                    row['status'] = 'skipped_exists'
                    print(f'  SKIP {filename} (already exists)')
                    manifest.append(row)
                    continue
                source.seek(offset)
                data = source.read(size)
                if len(data) != size:
                    raise ValueError('Unable to read full archived entry')
                if args.raw:
                    decoded = data
                elif kind in COMPRESSED_TYPES:
                    decoded = decode_lz(data, args.max_unpacked_mib * 1024 * 1024)
                else:
                    decoded = data
                destination.write_bytes(decoded)
                row['unpacked_bytes'] = len(decoded)
                row['status'] = 'extracted'
                successes += 1
                print(f'  OK   {filename}   {len(data):,} -> {len(decoded):,} bytes')
            except (OSError, ValueError, IndexError) as exc:
                row['status'] = 'error'
                row['error'] = str(exc)
                errors += 1
                print(f'  ERROR {filename}: {exc}', file=sys.stderr)
            manifest.append(row)

    with (out_dir / 'manifest.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['index', 'id_hex', 'id_decimal', 'type_hex',
                         'offset_hex', 'packed_bytes', 'unpacked_bytes', 'output_file',
                         'status', 'error'])
        writer.writeheader()
        writer.writerows(manifest)
    print(f'Finished: {successes} extracted, {errors} errors; manifest: {out_dir / "manifest.csv"}')
    return (successes, errors)


def main():
    parser = argparse.ArgumentParser(description='Extract IRLST/IRARC Inti Creates archives (Python standard library only).')
    parser.add_argument('input', type=Path, help='An .irlst, .irarc, or directory containing matching pairs')
    parser.add_argument('-o', '--output', type=Path, help='Output root; creates one subfolder per archive')
    parser.add_argument('--recursive', action='store_true', help='Search directories recursively for pairs')
    parser.add_argument('--list', action='store_true', help='Show index entries only; no files are written')
    parser.add_argument('--raw', action='store_true', help='Extract packed bytes without decompressing')
    parser.add_argument('--overwrite', action='store_true', help='Replace existing extracted files')
    parser.add_argument('--max-unpacked-mib', type=int, default=1024,
                        help='Per-resource decompression safety limit in MiB (default: 1024)')
    args = parser.parse_args()
    if args.max_unpacked_mib < 1:
        parser.error('--max-unpacked-mib must be >= 1')
    try:
        input_path = args.input.expanduser().resolve()
        indices, is_directory = discover(input_path, args.recursive)
        if is_directory:
            out_root = args.output or (input_path / 'irarc_extracted')
        else:
            out_root = args.output or (indices[0].parent / (indices[0].stem + '_extracted'))
        out_root = out_root.expanduser().resolve()
        succeeded, failed = 0, 0
        for index_path in indices:
            try:
                if is_directory:
                    relative_parent = index_path.parent.relative_to(input_path)
                    dest = out_root / relative_parent / index_path.stem
                else:
                    dest = out_root
                ok, bad = process_pair(index_path, dest, args)
                succeeded += ok
                failed += bad
            except (OSError, ValueError) as exc:
                print(f'ERROR {index_path}: {exc}', file=sys.stderr)
                failed += 1
        print(f'\nDone: {len(indices)} pair(s), {succeeded} extracted/listed, {failed} errors')
        return 1 if failed else 0
    except (OSError, ValueError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
