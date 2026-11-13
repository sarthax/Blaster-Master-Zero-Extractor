"""Cross-archive catalog tests use original synthetic (non-game) resources."""
from pathlib import Path
import tempfile
import unittest

from inti_explorer.catalog import (PAGE_SIZE, catalog_from_report, catalog_page,
                                   filter_catalog)
from inti_explorer.inti import discover_sources
from inti_explorer.inventory import scan_path
from tests.test_inventory import section_resource, pixel_resource, write_pair


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='BMZ folder with spaces ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        a = pixel_resource()
        b = section_resource([b'ICDB' + bytes(28)])
        write_pair(self.root / 'A', 'resarc_cmm', [(0x2100, a, 7), (0xF00, b, 7)])
        write_pair(self.root / 'B', 'resarc_cmm', [(0x2100, a, 7)])
        self.sources = discover_sources(self.root)
        self.report = scan_path(self.root)
        self.items = catalog_from_report(self.report, self.sources, self.root)

    def test_same_id_remains_distinct_across_archives(self):
        same = [i for i in self.items if i.resource_id == 0x2100]
        self.assertEqual(len(same), 2)
        self.assertNotEqual(same[0].source_index, same[1].source_index)
        for item in same:
            entry = self.sources[item.source_index].entries[item.ordinal]
            self.assertEqual(entry.resource_id, 0x2100)

    def test_classification_archive_and_query_filters(self):
        self.assertEqual(len(filter_catalog(self.items)), 2)
        self.assertEqual(len(filter_catalog(self.items, '2100')), 2)
        self.assertEqual(len(filter_catalog(self.items, '8448')), 2)  # decimal resource ID
        self.assertEqual(len(filter_catalog(self.items, '0x2100 B/')), 1)
        self.assertEqual(len(filter_catalog(self.items, '2x2')), 2)
        self.assertEqual(len(filter_catalog(self.items, category='Sprite frames')), 0)
        self.assertEqual(len(filter_catalog(self.items, category='Paletted')), 0)
        self.assertEqual(len(filter_catalog(self.items, category='Other / unknown')), 1)
        self.assertEqual(len(filter_catalog(self.items, category='All resources')), 3)
        self.assertEqual(len(filter_catalog(self.items, archive='A/resarc_cmm.irlst')), 1)
        self.assertEqual(len(filter_catalog(self.items, archive='B/resarc_cmm.irlst')), 1)
        with self.assertRaises(ValueError):
            filter_catalog(self.items, category='Made up')

    def test_pagination_is_bounded(self):
        self.assertEqual(PAGE_SIZE, 20)
        for value, expected in [(-2, 0), (0, 0), (1, 0), (100, 0)]:
            page, index, total = catalog_page(self.items, value)
            self.assertEqual((index, total), (expected, 1))
            self.assertEqual(len(page), 3)
        many = self.items * 21
        page, index, total = catalog_page(many, 2)
        self.assertEqual((len(page), index, total), (20, 2, 4))
        page, index, total = catalog_page([], 2)
        self.assertEqual((page, index, total), ([], 0, 1))

    def test_reject_mismatched_inventory_id(self):
        self.report['resources'][0]['resource_id'] = '0xDEADBEEF'
        with self.assertRaisesRegex(ValueError, 'mismatch'):
            catalog_from_report(self.report, self.sources, self.root)

    def test_unavailable_source_is_skipped(self):
        only_one = catalog_from_report(self.report, self.sources[:1], self.root)
        self.assertEqual(len(only_one), 2)


if __name__ == '__main__':
    unittest.main()
