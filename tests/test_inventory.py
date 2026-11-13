"""Synthetic inventory coverage: metadata only, no third-party game assets."""
import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from inti_explorer.inventory import inspect_resource, scan_path, write_reports, main


def section_resource(bodies):
    off = 4 + 16 * len(bodies)
    headers = bytearray(struct.pack('<I', len(bodies)))
    payload = bytearray()
    for body in bodies:
        headers += struct.pack('<IIII', 0, 0, off, len(body))
        payload += body
        off += len(body)
    return bytes(headers + payload)


def pixel_resource():
    pixels = bytes([20, 30, 40, 255]) * 4
    body = struct.pack('<IIII', 16, 2, 2, 4) + bytes(0x80 - 16) + pixels
    return section_resource([body])


def write_pair(folder, basename, records):
    folder.mkdir(exist_ok=True, parents=True)
    arc = bytearray()
    ix = bytearray(struct.pack('<I', len(records)))
    for rid, payload, kind in records:
        ix += struct.pack('<IIII', rid, len(arc), len(payload), kind)
        arc += payload
    (folder / (basename + '.irlst')).write_bytes(ix)
    (folder / (basename + '.irarc')).write_bytes(arc)


class InventoryTests(unittest.TestCase):
    def test_pixel_metadata_dimensions_no_images(self):
        info = inspect_resource(pixel_resource())
        self.assertEqual(info['classification'], 'PIXEL')
        self.assertEqual(info['dimensions'], ['2x2'])
        self.assertEqual(info['status'], 'metadata_ok')
        self.assertNotIn('images', info)

    def test_unrecognized_not_misidentified_as_pixel(self):
        data = section_resource([b'????' + bytes(20)])
        info = inspect_resource(data)
        self.assertEqual(info['classification'], 'UNKNOWN')
        self.assertEqual(info['sections'][0]['magic_hex'], '3f3f3f3f')
        self.assertEqual(info['status'], 'unrecognized')

    def test_unknown_known_signature(self):
        data = section_resource([b'ICDB' + bytes(28)])
        self.assertEqual(inspect_resource(data)['classification'], 'ICDB')

    def test_bad_offset_rejected(self):
        blob = struct.pack('<I', 1) + struct.pack('<IIII', 0, 0, 99, 20)
        with self.assertRaisesRegex(ValueError, 'invalid offset'):
            inspect_resource(blob)

    def test_multi_archive_report_and_errors(self):
        with tempfile.TemporaryDirectory(prefix='BMZ path with spaces ') as folder:
            root = Path(folder)
            write_pair(root, 'good', [(0x2100, pixel_resource(), 7),
                                      (0xF00, section_resource([b'ICDB' + bytes(28)]), 7)])
            write_pair(root / 'nested', 'broken_resource', [(0x30, b'not a table', 7)])
            (root / 'orphan.irarc').write_bytes(b'orphan')
            (root / 'bad_index.irlst').write_bytes(b'x')
            r = scan_path(root)
            self.assertEqual(r['summary']['sources'], 2)
            self.assertEqual(r['summary']['resources'], 3)
            self.assertEqual(r['summary']['pair_errors'], 2)
            self.assertTrue(all(folder not in failure['error'] for failure in r['pair_errors']))
            self.assertEqual(r['summary']['statuses'], {'metadata_ok': 1, 'parse_error': 1, 'unrecognized': 1})
            self.assertEqual(r['summary']['section_signatures'], {'ICDB': 1, 'PIXEL': 1})
            self.assertEqual(r['resources'][0]['resource_sha256'], hashlib.sha256(pixel_resource()).hexdigest())
            self.assertEqual(r['sources'][0]['archive_sha256'], hashlib.sha256((root/'good.irarc').read_bytes()).hexdigest())
            self.assertFalse('BMZ path with spaces' in r['resources'][0]['source'])
            j, c = write_reports(r, root / 'reports' / 'scan.json')
            self.assertEqual(json.loads(j.read_text())['summary'], r['summary'])
            self.assertEqual(len(c.read_text().splitlines()), 4)

    def test_limit_exceeded_logged(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_pair(root, 'big', [(1, b'x' * (1024 * 1024 + 1), 7)])
            r = scan_path(root, max_unpacked_mib=1)
            self.assertEqual(r['summary']['statuses'], {'read_error': 1})
            self.assertIn('exceeds', r['resources'][0]['error'])

    def test_cli_single_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_pair(root, 'archive', [(1, pixel_resource(), 7)])
            self.assertEqual(main([str(root/'archive.irlst'), '-o', str(root/'metadata.json')]), 0)
            self.assertTrue((root/'metadata.csv').exists())


if __name__ == '__main__':
    unittest.main()
