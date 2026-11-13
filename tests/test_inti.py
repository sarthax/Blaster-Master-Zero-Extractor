"""Tiny synthetic fixtures; no copyrighted game data required."""
from pathlib import Path
import struct
import tempfile
import unittest

from inti_explorer.inti import decode_preview, discover_sources, open_pair
from tools.extract_irarc import decode_lz


def literal_pack(payload):
    assert len(payload) <= 8
    wrapper = struct.pack('<IIIIII', 24, 0, 0, len(payload), 0, 0)
    return wrapper + b'\x00' + payload


def pixel_section():
    px = bytes([0, 0, 255, 255]) * 4  # red BGRA pixels
    body = struct.pack('<IIII', len(px), 2, 2, 4) + bytes(0x80 - 16) + px
    return struct.pack('<I', 1) + struct.pack('<IIII', 0, 0, 20, len(body)) + body


class ArchiveTests(unittest.TestCase):
    def test_lz_literals(self):
        self.assertEqual(bytes(decode_lz(literal_pack(b'ABC'), 1024)), b'ABC')

    def test_lz_invalid_output_size(self):
        with self.assertRaises(ValueError):
            decode_lz(literal_pack(b'ABC'), 2)

    def test_read_archive_and_decode_png(self):
        payload = pixel_section()
        with tempfile.TemporaryDirectory(prefix='BMZ path with spaces ') as temp:
            root = Path(temp)
            (root/'demo.irarc').write_bytes(payload)
            (root/'demo.irlst').write_bytes(struct.pack('<IIIII', 1, 0x2100, 0, len(payload), 7))
            source = open_pair(root/'demo.irlst')
            self.assertEqual(source.entries[0].name, '00002100.7')
            result = decode_preview(source.get_data(source.entries[0]))
            self.assertEqual(result.classification, 'PIXEL')
            self.assertEqual(result.images[0].size, (2, 2))
            self.assertEqual(result.images[0].getpixel((0, 0)), (255, 0, 0, 255))
            discovered = discover_sources(root)
            self.assertEqual(len(discovered), 1)

    def test_compressed_entry_path(self):
        payload = b'HI'
        packed = literal_pack(payload)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'a.irarc').write_bytes(packed)
            (root/'a.irlst').write_bytes(struct.pack('<IIIII', 1, 0x10, 0, len(packed), 0x17))
            src = discover_sources(root)[0]
            self.assertEqual(src.get_data(src.entries[0]), payload)

    def test_unpaired_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'a.irlst').write_bytes(struct.pack('<I', 0))
            with self.assertRaises(ValueError):
                discover_sources(root)

    def test_skipped_pairs_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'good.irarc').write_bytes(b'x')
            (root/'good.irlst').write_bytes(struct.pack('<I', 0))
            (root/'bad.irlst').write_bytes(b'garbage')  # no .irarc partner
            skipped = []
            self.assertEqual(len(discover_sources(root, skipped=skipped)), 1)
            self.assertEqual([name for name, _ in skipped], ['bad.irlst'])

    def test_no_loose_when_pair_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'a.irarc').write_bytes(b'x')
            (root/'a.irlst').write_bytes(struct.pack('<I', 0))
            (root/'00000100.17').write_bytes(b'decoded')
            self.assertEqual(len(discover_sources(root)), 1)

    def test_loose_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'00002100.17').write_bytes(pixel_section())
            src = discover_sources(root)[0]
            self.assertTrue(src.is_loose)
            self.assertEqual(src.entries[0].resource_id, 0x2100)
            self.assertTrue(decode_preview(src.get_data(src.entries[0])).images)


class GraphicsTests(unittest.TestCase):
    def test_unknown_section_matches_inventory_classification(self):
        from inti_explorer.inventory import inspect_resource
        body = b'????' + bytes(124)
        blob = struct.pack('<IIIII', 1, 0, 0, 20, len(body)) + body
        preview = decode_preview(blob)
        self.assertEqual(preview.classification, 'UNKNOWN')
        self.assertEqual(preview.sections, ['UNKNOWN'])
        self.assertEqual(preview.images, [])
        self.assertEqual(preview.classification, inspect_resource(blob)['classification'])

    def test_mixed_pixel_and_unknown_keeps_raw_exportable(self):
        from inti_explorer.inventory import inspect_resource
        known = pixel_section()[20:]
        unknown = b'????' + bytes(124)
        header = struct.pack('<I', 2)
        header += struct.pack('<IIII', 0, 0, 36, len(known))
        header += struct.pack('<IIII', 0, 0, 36 + len(known), len(unknown))
        blob = header + known + unknown
        preview = decode_preview(blob)
        self.assertEqual(preview.classification, 'PIXEL+UNKNOWN')
        self.assertEqual(preview.images, [])
        self.assertEqual(preview.classification, inspect_resource(blob)['classification'])

    def test_unknown_returns_exportable_preview(self):
        p = decode_preview(b'\x00')
        self.assertEqual(p.images, [])

    def test_synthetic_tlpi_palette_and_frame(self):
        # IOBJ with 2x2 indexed texture, one PTGT quad, plus one TLPI palette.
        indices = [1, 2, 1, 2]
        pixels = b''.join(bytes([0, 255-i, i, 255]) for i in indices)
        tex = struct.pack('<IIII', len(pixels), 2, 2, 4) + bytes(0x80-16) + pixels
        ptgt_off = 20 + len(tex)
        quad = struct.pack('<16f', 2,0,1,0, 2,2,1,1, 0,2,0,1, 0,0,0,0)
        ptgt = b'PTGT' + bytes(4) + struct.pack('<I', 1) + struct.pack('<IBBH', 0,1,0,0) + quad
        iobj = b'IOBJ' + struct.pack('<III', 20, ptgt_off, 1) + struct.pack('<I', 20) + tex + ptgt
        colors = bytearray(1024)
        colors[4:8] = bytes([0,0,255,255])  # 1: red
        colors[8:12] = bytes([0,255,0,255])  # 2: green
        tlpi = b'TLPI' + struct.pack('<HH', 1, 256) + bytes(8) + bytes(colors)
        blob = struct.pack('<I', 2)
        offset = 4 + 2*16
        blob += struct.pack('<IIII', 0,0,offset,len(iobj))
        blob += struct.pack('<IIII', 0,0,offset+len(iobj),len(tlpi))
        blob += iobj + tlpi
        p = decode_preview(blob)
        self.assertEqual(p.classification, 'IOBJ + TLPI')
        self.assertEqual(p.images[0].getpixel((0,0)), (255,0,0,255))
        self.assertEqual(p.images[0].getpixel((1,0)), (0,255,0,255))
        self.assertEqual(p.frame_at(0).size,(2,2))


if __name__ == '__main__':
    unittest.main()
