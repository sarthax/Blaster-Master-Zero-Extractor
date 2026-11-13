"""Read-only Inti Creates archive adapter and Blaster Master Zero graphics preview.

Public functions are kept independent of the GUI so other frontends and format
adapters can be added without touching Tkinter.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tools.extract_irarc import (COMPRESSED_TYPES, decode_lz, find_partner, load_index)
from tools.decode_irarc_graphics import (
    sections, parse_iobj, parse_tlpi, decode_bgra, decode_tlpi_texture,
    read_texture, render_frame,
)

MAX_UNPACKED_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class Entry:
    ordinal: int
    resource_id: int
    offset: int
    packed_size: int
    kind: int
    path: Optional[Path] = None

    @property
    def name(self) -> str:
        return f'{self.resource_id:08X}.{self.kind:x}'

    @property
    def key(self) -> str:
        return f'{self.ordinal:06d}-{self.resource_id:08X}-{self.kind:x}'

    @property
    def export_name(self) -> str:
        # Index position disambiguates duplicate resource IDs.
        return f'{self.resource_id:08X}_{self.ordinal:04d}.{self.kind:x}'


@dataclass
class Source:
    label: str
    path: Path
    entries: list[Entry]
    archive: Optional[Path] = None

    @property
    def is_loose(self) -> bool:
        return self.archive is None

    def get_data(self, entry: Entry, max_unpacked_bytes: int = MAX_UNPACKED_BYTES) -> bytes:
        if entry not in self.entries:
            raise ValueError('Resource does not belong to the current source')
        if entry.path is not None:
            if entry.path.stat().st_size > max_unpacked_bytes:
                raise ValueError('Loose resource exceeds size limit')
            return entry.path.read_bytes()
        if self.archive is None:
            raise ValueError('Missing source archive')
        if entry.packed_size > max_unpacked_bytes:
            raise ValueError('Packed resource exceeds size limit')
        with self.archive.open('rb') as stream:
            stream.seek(entry.offset)
            packed = stream.read(entry.packed_size)
        if len(packed) != entry.packed_size:
            raise ValueError('Short archive read')
        if entry.kind in COMPRESSED_TYPES:
            return bytes(decode_lz(packed, max_unpacked_bytes))
        return packed


def open_pair(index_path: Path) -> Source:
    index_path = Path(index_path).resolve()
    partner = find_partner(index_path)
    archive_size = partner.stat().st_size
    tuples = load_index(index_path, archive_size)
    entries = [Entry(i, rid, offset, size, kind) for i, rid, offset, size, kind in tuples]
    return Source(index_path.stem, index_path, entries, partner)


def open_loose(directory: Path, recursive: bool = False) -> Source:
    directory = Path(directory).resolve()
    paths = sorted(directory.rglob('*.17') if recursive else directory.glob('*.17'))
    if not paths:
        raise ValueError(f'No loose .17 resources in {directory}')
    entries = []
    for i, path in enumerate(paths):
        try:
            rid = int(path.stem.split('_', 1)[0], 16)
        except ValueError:
            rid = i
        entries.append(Entry(i, rid, 0, path.stat().st_size, 0x17, path))
    return Source(f'Loose: {directory.name}', directory, entries)


def discover_sources(path: Path, recursive: bool = True,
                     skipped: Optional[list] = None) -> list[Source]:
    """Prefer original pairs; fall back to already extracted resources.

    Invalid pairs are skipped; when ``skipped`` is a list they are appended to it
    as ``(index filename, error)`` so callers can report them.
    """
    path = Path(path).expanduser().resolve()
    if path.is_file():
        if path.suffix.lower() in {'.irlst', '.irarc'}:
            index = path
            if path.suffix.lower() == '.irarc':
                peers = [p for p in path.parent.iterdir()
                         if p.is_file() and p.stem.casefold() == path.stem.casefold()
                         and p.suffix.lower() == '.irlst']
                if not peers:
                    raise ValueError('No corresponding .irlst index')
                index = peers[0]
            return [open_pair(index)]
        if path.suffix.lower() == '.17':
            return [open_loose(path.parent)]
        raise ValueError('Select an .irlst or .irarc file, a .17 resource, or a folder')
    if not path.is_dir():
        raise FileNotFoundError(path)
    indices = sorted((path.rglob('*.irlst') if recursive else path.glob('*.irlst')))
    if indices:
        results = []
        for index in indices:
            try:
                results.append(open_pair(index))
            except (OSError, ValueError) as exc:
                # A broken pair should not prevent other pairs from being browsed.
                if skipped is not None:
                    skipped.append((index.name, str(exc).replace(str(index), index.name)))
                continue
        if results:
            return results
        raise ValueError('Found .irlst indexes, but none have valid .irarc partners')
    return [open_loose(path, recursive)]


@dataclass
class Preview:
    classification: str
    images: list  # Pillow Images (lazy import via graphics module)
    frames: list
    tex_count: int
    palette_count: int
    sections: list[str]
    note: str = ''

    def frame_at(self, frame_index: int, variant_index: int = 0):
        if not 0 <= frame_index < len(self.frames):
            return None
        tex_id, quads = self.frames[frame_index]
        if self.palette_count:
            if tex_id != 0:
                return None
            textures = [self.images[variant_index]]
        else:
            textures = self.images
        return render_frame(textures, tex_id, quads)


def decode_preview(data: bytes) -> Preview:
    """Recognize a decompressed resource. Unknown kinds remain exportable."""
    try:
        sects = sections(data)
    except (ValueError, IndexError) as exc:
        return Preview('Unknown / non-texture', [], [], 0, 0, [], str(exc))
    # The graphics parser calls unknown sections PIXEL before validating them.
    # Match the inventory's classification rather than reporting a false
    # texture-decode failure for ordinary non-image resources.
    kinds = []
    pixel_textures = []
    for name, _code, body in sects:
        if name != 'PIXEL':
            kinds.append(name)
            continue
        try:
            texture = read_texture(body, 0)
        except ValueError:
            kinds.append('UNKNOWN')
        else:
            kinds.append('PIXEL')
            pixel_textures.append(texture)
    if 'IOBJ' in kinds:
        obj = next(body for name, _, body in sects if name == 'IOBJ')
        textures, frames = parse_iobj(obj)
        tlpi = next((body for name, _, body in sects if name == 'TLPI'), None)
        if tlpi is not None:
            palettes = parse_tlpi(tlpi)
            if len(textures) != 1:
                return Preview('IOBJ+TLPI (unsupported multi-texture)', [], frames,
                               len(textures), len(palettes), kinds)
            w, h, fmt, pix = textures[0]
            images = [decode_tlpi_texture(w, h, fmt, pix, pal) for pal in palettes]
            return Preview('IOBJ + TLPI', images, frames, len(textures), len(palettes), kinds,
                           'Palette variants; sprite assembly is experimental')
        images = [decode_bgra(*tex) for tex in textures]
        return Preview('IOBJ', images, frames, len(textures), 0, kinds,
                       'Sprite assembly is experimental')
    if kinds and all(k == 'PIXEL' for k in kinds):
        imgs = [decode_bgra(*texture) for texture in pixel_textures]
        return Preview('PIXEL', imgs, [], len(imgs), 0, kinds)
    return Preview('+'.join(kinds) if kinds else 'Empty', [], [], 0, 0, kinds,
                   'No supported texture in this resource')
