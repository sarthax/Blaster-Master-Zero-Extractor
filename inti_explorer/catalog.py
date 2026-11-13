"""Stable, metadata-only cross-archive catalog and filtering.

Only the currently displayed page needs its image data decoded. Rows originate
from an inventory scan and are mapped back to their exact source/entry pair,
never just a resource ID (IDs may be repeated between archives).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .inti import Source

PAGE_SIZE = 20
FILTERS = ('Graphics', 'Sprite frames', 'Paletted', 'Other / unknown', 'All resources')


@dataclass(frozen=True)
class CatalogItem:
    source_index: int
    ordinal: int
    source_path: str
    source_label: str
    resource_id: int
    classification: str
    textures: int
    palettes: int
    frames: int
    dimensions: tuple[str, ...]
    status: str
    packed_bytes: int

    @property
    def graphic(self) -> bool:
        return self.status == 'metadata_ok' and self.textures > 0

    @property
    def search_text(self) -> str:
        return ' '.join((f'{self.resource_id:08X}', f'0x{self.resource_id:X}',
                         str(self.resource_id), self.source_path, self.source_label,
                         self.classification, ' '.join(self.dimensions))).casefold()


def catalog_from_report(report: dict, sources: list[Source], root: Path) -> list[CatalogItem]:
    """Map inventory rows to exact loaded sources, validating IDs and ordinals.

    An inventory may mention an invalid pair that the explorer could not open;
    those entries have no browser target and are never turned into catalog cards.
    """
    root = Path(root).resolve()
    root = root if root.is_dir() else root.parent
    indexed = {source.path.resolve(): i for i, source in enumerate(sources)}
    items = []
    for row in report.get('resources', []):
        source_path = str(row['source'])
        index = indexed.get((root / source_path).resolve())
        if index is None:
            continue
        source = sources[index]
        ordinal = int(row['index'])
        if ordinal < 0 or ordinal >= len(source.entries):
            raise ValueError(f'Inventory references invalid entry {ordinal} in {source_path}')
        entry = source.entries[ordinal]
        rid = int(str(row['resource_id']), 16)
        if entry.resource_id != rid or entry.ordinal != ordinal:
            raise ValueError(f'Inventory mismatch at {source_path}:{ordinal}')
        items.append(CatalogItem(
            source_index=index, ordinal=ordinal, source_path=source_path,
            source_label=source.label, resource_id=rid,
            classification=str(row.get('classification', '')),
            textures=int(row.get('textures', 0)), palettes=int(row.get('palettes', 0)),
            frames=int(row.get('frames', 0)), dimensions=tuple(row.get('dimensions', [])),
            status=str(row.get('status', 'unrecognized')),
            packed_bytes=entry.packed_size))
    return sorted(items, key=lambda x: (x.source_path.casefold(), x.resource_id, x.ordinal))


def filter_catalog(items: list[CatalogItem], query: str = '', category: str = 'Graphics',
                   archive: str = '') -> list[CatalogItem]:
    """Filter without opening archives or decoding thumbnails."""
    if category not in FILTERS:
        raise ValueError(f'Unknown category: {category}')
    terms = query.casefold().split()
    result = []
    for item in items:
        if archive and item.source_path != archive:
            continue
        if category == 'Graphics' and not item.graphic:
            continue
        if category == 'Sprite frames' and not (item.graphic and item.frames > 0):
            continue
        if category == 'Paletted' and not (item.graphic and item.palettes > 0):
            continue
        if category == 'Other / unknown' and item.graphic:
            continue
        haystack = item.search_text
        if all(term in haystack for term in terms):
            result.append(item)
    return result


def catalog_page(items: list[CatalogItem], page: int, size: int = PAGE_SIZE) -> tuple[list[CatalogItem], int, int]:
    """Return bounded cards, the current valid 0-based page and total pages."""
    if size < 1 or size > 200:
        raise ValueError('Page size must be 1..200')
    page_count = max(1, (len(items) + size - 1) // size)
    index = min(max(0, page), page_count - 1)
    return items[index * size:(index + 1) * size], index, page_count
