# Inti Asset Explorer

**Read-only archive explorer, texture decoder, and game-format research project.** The first supported target is the **Windows/PC release of Blaster Master Zero**. The application opens `.irlst` + `.irarc` pairs *directly*—no separate extraction step is required—and lets you browse IDs, inspect palette variants, preview experimental sprite frames, and export PNGs or original decompressed resources.

The project is designed around independently testable formats so more Inti Creates games and unrelated asset formats can be supported in future adapters. The repository includes no copyrighted game binaries, artwork, or extracted assets.

## Quick start (Windows)

1. Install [Python 3.9+](https://www.python.org/downloads/) (prefer a normal Windows Python installation with Tkinter).
2. Download the repository, unzip it, and double-click **`start_windows.bat`**. It installs Pillow if it is not already installed.
3. Click **Open game folder…** and select your game’s `data\resarc` directory, or open a single `.irlst` or `.irarc` file.
4. Pick an archive on the left, then a resource ID in the middle. Browse texture/palette variants and experimental sprite frames on the right.
5. Select **All game assets** → **Index game assets** to search graphics across every archive at once. Filter by resource ID, archive, section type, or image dimensions; click any thumbnail to jump to its archive, palette variants, and frames. The display decodes up to 20 thumbnails per page, not the whole game at once.
6. Click **Export inventory…** to scan the selected game folder and save metadata-only JSON + CSV reports. Use **Export current PNG…**, **Export raw…**, or **Extract archive…** only when you want to save actual assets. Originals are not modified.

Command-line launch on all desktop platforms with Tk support:

```shell
python -m pip install -r requirements.txt
python -m inti_explorer
```

### What is supported today

| Feature | Status |
| --- | --- |
| Recursive scan and direct read of `.irlst` + `.irarc` pairs | Implemented for tested PC layout |
| Custom LZ decompression of archive entry kinds `0x12` and `0x17` | Implemented; other kinds preserved as raw bytes |
| Search archive resources by ID / numeric type | Implemented |
| BGRA32 textures and BGRA4444 decode path | Implemented; BGRA4444 not validated on sample |
| IOBJ image textures | Implemented for observed structure |
| TLPI palette variants (BMZ red-channel indexing) | Implemented for observed single-texture variant |
| PTGT composite frame preview | Experimental: axis-aligned quads, not full animation playback |
| Thumbnail gallery for selected archive | Implemented, generated on demand |
| **All game assets** cross-archive catalog | Implemented: metadata search/filter and 20-thumbnails-per-page browse; local full-game acceptance pending |
| Export decoded PNG / raw decompressed entry / all entries | Implemented; no repacking |
| Unknown resource inspection | Structured section signatures, metadata-only JSON/CSV inventory, raw export |
| Animation timing, non-axis-aligned geometry, audio, maps, scripts | Research/backlog |
| Other titles, consoles, and PC releases | **Not yet validated** |

The new **All game assets** tab scans all opened archive pairs with the same metadata-only inventory backend, then decodes only the currently visible catalog page. Search terms match archive paths, hexadecimal or decimal resource IDs, classification and texture dimensions; filter by graphics, sprite-frame metadata, palettes or unrecognized resources. Duplicate IDs in different archives are kept separate. There is **no persistent thumbnail cache yet**, and scanning an entire game can take time; it runs on a worker thread without exporting game data.

The per-archive gallery shows **one thumbnail per graphical resource**, not one per palette or frame. The `Texture` tab can show all currently decoded palette variants. A file not recognized as a texture can still be exported for investigation.

## Extra command-line tools

The original tested two-stage tools are retained under `tools/` for automation and headless pipelines:

```shell
python tools/extract_irarc.py "C:\Games\Blaster Master Zero\data\resarc" --recursive -o "C:\Extracted"
python tools/decode_irarc_graphics.py "C:\Extracted" --recursive --frames -o "C:\Graphics"
```

The CLI decoder defaults to 24 experimental frame previews per resource; use `--max-frames 0` to render all. It writes a `graphics_manifest.csv` (whereas the GUI works directly from archive bytes).

### Full-game metadata inventory (no sprite PNGs)

Scan the entire game directory, including other archive pairs, without exporting or modifying game assets:

```powershell
py -3 -m inti_explorer.inventory "C:\Games\Blaster Master Zero\data\resarc" -o "C:\Reports\bmz_inventory.json"
```

This generates `bmz_inventory.json` and `bmz_inventory.csv` (companion file). In the GUI, choose **Export inventory…** after opening a game folder. The report lists archive SHA-256 hashes, IDs, entry types, compressed/uncompressed sizes, resource SHA-256 hashes, raw section signatures, texture dimensions, palette/frame counts, and failures (including missing archive partners).

A format signature such as `ICDB` or `UNKNOWN` is recorded without guessing the meaning. A previously observed `resarc_cmm` index comprises 227 resources, 226 graphics-metadata-readable and one ICDB unrecognized; other archive pairs have not been tested here. See [docs/INVENTORY.md](docs/INVENTORY.md) for report fields, limits and interpretation.

## Validation baseline

On the supplied `resarc_cmm.irlst` + `resarc_cmm.irarc` pair (Blaster Master Zero PC), the pure read/decode path inspected **227 resources** with **0 parser failures**, recognized **88 IOBJ**, **135 IOBJ+TLPI**, **3 PIXEL**, and **1 ICDB** resources, and produced **578 texture/palette images**. There are 5,703 PTGT frame records, **not all guaranteed renderable**. This is evidence for that archive only, not a blanket compatibility promise across all game releases. Synthetic tests and a headless Tk startup check accompany the code.

Run tests:

```shell
python -m unittest discover -s tests -v
```

## Architecture and research

- `inti_explorer/inti.py`: read-only source/index/entry API, decoded resource representation, BMZ preview adapter. Independent of GUI.
- `inti_explorer/inventory.py`: headless game-wide index/section scan and JSON/CSV report writer; does not create PNGs.
- `inti_explorer/catalog.py`: metadata-only cross-archive catalog, filters, exact source/entry mapping and bounded pagination.
- `inti_explorer/gui.py`: desktop Tkinter browser. Worker threads perform resource reads and image processing; GUI updates stay on the main thread.
- `tools/extract_irarc.py`: standalone IRARC extractor and custom LZ decoder.
- `tools/decode_irarc_graphics.py`: standalone resource-section, IOBJ/TLPI and PTGT decoder.
- `tests/`: synthetic header, compression, palette and source-navigation tests. No game files.
- `docs/FORMATS.md`: researched and directly observed data structures, caveats, references.
- `docs/ROADMAP.md`: prioritized features and verification criteria for future games/formats.
- `docs/CATALOG.md`: cross-archive catalog behavior, known limits, and acceptance procedure.

**Current limitation:** decoder wiring uses the standalone tool modules under `tools/`; a future plugin protocol will isolate each game's formats and allow per-release detection. Do not infer support just because two games share a filename extension.

## Prior art and credit

This project contains an independently implemented Python decoder and does not bundle third-party PHP scripts. The community research by [rufaswan / Web2D_Games](https://github.com/rufaswan/Web2D_Games/tree/053e9ad099b4e6247dad5652429baa03db1a7891) is an important historical reference. The [VG Resource discussion](https://archive.vg-resource.com/thread-38568.html) documents the IRLST/IRARC format family and the BMZ TLPI problem. The red-channel palette-index observation used here was validated on the provided BMZ sample and should be re-tested against future titles.

## Scope and legality

Use your own lawfully obtained game data, subject to your local laws and applicable licenses. Do not commit game files or extracted sprite PNGs to this repository. This is a fan-made research utility, not affiliated with or endorsed by Inti Creates. Licensed under MIT (see `LICENSE`).
