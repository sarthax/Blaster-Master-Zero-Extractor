"""Synthetic sprite exchange validation; no proprietary game images."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from inti_explorer.inti import Entry, Preview, Source
from inti_explorer.sprite_bridge import build_package


class SpriteBridgeTests(unittest.TestCase):
    def sample(self, root):
        file = root / '00002104.17'
        file.write_bytes(b'not a real resource')
        entry = Entry(0, 0x2104, 0, file.stat().st_size, 0x17, file)
        source = Source('synthetic', file, [entry], None)
        corners = [(-8, -24), (8, -24), (8, 0), (-8, 0)]
        uv = [(0, 0), (1, 0), (1, 1), (0, 1)]
        image = Image.new('RGBA', (16, 24), (200, 10, 100, 255))
        return source, entry, Preview('IOBJ + TLPI', [image], [(0, [(corners, uv)])], 1, 1, ['IOBJ', 'TLPI'])

    def test_exports_source_bounds_and_frame_sha(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, entry, preview = self.sample(root)
            with patch('inti_explorer.sprite_bridge.decode_preview', return_value=preview):
                result = build_package(source, entry, root / 'export')
            self.assertEqual(result['schema'], 'inti-assembled-sprite-sequence/1.0')
            self.assertEqual(result['frames'][0]['ptgt_bounds'], {'x': -8, 'y': -24, 'width': 16, 'height': 24})
            data = (root / 'export' / 'frames/frame_0000.png').read_bytes()
            self.assertEqual(result['frames'][0]['png_sha256'], hashlib.sha256(data).hexdigest())
            self.assertEqual(json.loads((root / 'export/manifest.json').read_text())['origin']['resource_id'], '0x00002104')
            self.assertEqual(Image.open(root / 'export/frames/frame_0000.png').getpixel((0,0)), (200,10,100,255))

    def test_fail_closed_variant_and_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, entry, preview = self.sample(root)
            with patch('inti_explorer.sprite_bridge.decode_preview', return_value=preview):
                with self.assertRaises(ValueError):
                    build_package(source, entry, root / 'export', variant=1)
                self.assertFalse((root / 'export').exists())
                build_package(source, entry, root / 'export')
                with self.assertRaises(FileExistsError):
                    build_package(source, entry, root / 'export')

    def test_frame_limit_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, entry, _preview = self.sample(root)
            for count in (0, 513):
                with self.assertRaises(ValueError):
                    build_package(source, entry, root / 'no', limit=count)


if __name__ == '__main__':
    unittest.main()
