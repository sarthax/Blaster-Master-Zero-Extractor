# Cross-archive asset catalog — first slice

The **All game assets** tab provides a read-only catalog across all IRLST/IRARC pairs in the opened Blaster Master Zero PC folder. It reuses `scan_path` from `inventory.py`, and each catalog item resolves back to an exact `(source index, ordinal)` pair in memory. Resource IDs **are not globally unique**. Clicking an item selects its original archive and resource to inspect its full texture and experimental sprite-frame previews.

## Workflow

1. Launch `start_windows.bat` and open the game's `data\resarc` folder.
2. Choose **All game assets** → **Index game assets**. The initial full scan uses archive SHA-256 calculations, decompression and metadata parsing; it may take time on large folders, but happens off the UI thread.
3. Search by archive filename, hex or decimal resource ID, section classification or dimensions (e.g. `0x2100`, `8448`, `TLPI`, `64x64`). Combine words for conjunctive matching.
4. Filter by `Graphics` (default), `Sprite frames` (has frame records), `Paletted`, `Other / unknown`, or `All resources`. Narrow to a specific archive using the archive combo box.
5. Use **Previous** and **Next** to move through pages of at most 20 items. Thumbnails are decoded only for the current page, and at most the first texture/palette is shown. Selecting a catalog entry switches to the original detailed view, where variants and experimental frames can be explored.

Unknown or malformed resource payloads remain visible with `Other / unknown` or `All resources`; failed thumbnails never prevent accessing the original resource by ID.

## Limits and safety

- No game files are copied, committed, modified, or repacked by the catalog. The in-memory index contains metadata, while texture previews are held only for the visible page.
- Thumbnail reads are bounded to 32 MiB decompressed resource size. Large resources remain listed and exportable from their archive; an unavailable thumbnail is not a missing resource.
- The scan itself shares the inventory scanner's 256 MiB per-resource default limit. A resource exceeding it is listed as a read error.
- This first iteration uses explicit pagination, **not** scroll virtualization or a persistent thumbnail cache. Repeat scans will re-read the archive; in-memory filtering after a scan does not.
- The sprite-frame filter means a parsed PTGT frame record was seen, **not** verified in-game animation or an accurately cropped sprite.
- Archive hashes and metadata are calculated locally. Only synthetic fixtures are committed to the repository.

## Validation

- Synthetic unit tests cover duplicate IDs across archive paths, metadata filters, pagination bounds, and stale/mismatched mapping.
- Headless Tk smoke: index uploaded `resarc_cmm` pair, filter for resource `0x2100`, select a catalog card, and confirm its preview loads. This does **not** substitute for native Windows testing.
- **Pending:** open the complete game directory on Windows, verify multiple archive navigation, measure scan duration/memory, inspect 10+ representative images and report issues with specific archive names/resource IDs but no copyrighted game assets.
