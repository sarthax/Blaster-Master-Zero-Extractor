# Inti Creates format notebook — PC Blaster Master Zero baseline

Status labels in this document are intentionally precise:

- **Observed**: inspected in the uploaded `resarc_cmm` archive and successfully decoded by our implementation.
- **Reported**: described by external researchers, may need independent confirmation.
- **Experimental**: produces a recognizable render but is not confirmed equivalent to the original renderer.
- **Unknown**: no validated parser yet.

## Container files

**Observed — `.irlst`:** little-endian 32-bit record count, followed by exactly that many 16-byte entries (`resource_id`, `archive_offset`, `packed_size`, `kind`; all u32 little-endian). Entries point into the matching `.irarc` file, whose basename must match. The existing index parser verifies the exact index size and checks archive offsets and lengths.

**Observed — `.irarc`:** concatenated resource payloads. Resource kinds 0x12 and 0x17 use a 24-byte wrapper and custom LZ-style backreferences. Other resource kinds are preserved unchanged; do **not** equate the kind with a standardized file type or assume all types use the same wrapper. The extractor names the result by numeric ID plus a kind-derived suffix (e.g. `.17`); these are **not** ordinary OS image extensions.

**Observed — compressed entries:** first little-endian u32 in the wrapper is `0x18` (24); uncompressed byte length is at byte +0x0C. A stream of flag bytes follows the wrapper; low bit first: `0` = literal byte, `1` = 2-byte LZ backreference. Distance is `1 + byte0 + ((byte1 & 0x0F) << 8)` (range 1–4096), and length is `(byte1 >> 4) + 2` (range 2–17). Overlapping copies are valid. The decoder checks declared sizes and malformed copies. **This is not zlib, ZIP, or standard LZ4.**

## Decompressed resource sections

**Observed:** resources can start with a count and an array of 16-byte section descriptors. Each carries a code, an unknown 32-bit field, offset and length. The sections commonly include `IOBJ`, `TLPI`, `ICDB`, or standalone `PIXEL` data. Section codes and the unknown field need more research. Nontexture resources currently remain exportable but undecoded.

**Observed — IOBJ:** points to one or more texture headers and a `PTGT` structure. Texture header stores byte size, width, height and pixel-format code, followed by a 0x80-byte texture-header region. Format code 4 is BGRA8888. A format-5 BGRA4444 decode path exists but was not observed in our baseline archive and therefore remains unqualified.

**Observed — TLPI in BMZ (corrected from GPU capture):** a `TLPI` section contains a count of palettes, 256 BGRA colors per palette. The tested `IOBJ+TLPI` entries have one BGRA8888 texture in which the **red byte** encodes the palette index **with the high bit set** on most visible pixels. The shader-equivalent lookup for this PC sample is **`palette_index = red & 0x7F`**, *not* the literal red byte. Thus `0x2105`'s visible red bytes `129–138` select TLPI entries `1–10`; reading slots `129–138` produces incorrect all-black silhouettes. The pixel alpha multiplies the palette alpha. Observed blue is zero and green frequently `255 - red`; don't use the blue channel as the palette index. Other games/releases may differ, so this is scoped to the tested BMZ PC textures.

**GPU corroboration, November 2026:** a Ninja Ripper capture (`frame_2.zip`) includes `29649A74.dds` at 128×1024: its alpha channel matches BMZ `0x2105` exactly (all 131,072 pixels), and its decoded BGRA index channels match the source closely except BC3 quantization. The same capture contains a 256×1 strip `29649E34.dds`, whose 256-entry palette is closest to the original `0x2105` TLPI palette 0 (mean absolute difference ~0.54 over RGBA bytes, dominated by lossy BC3 artifacts). The captured NR meshes do *not* explicitly bind this pair; treat it as a strong source/palette correspondence rather than a proven draw-call association. Rendering `0x2104` and `0x2105` with `red & 0x7F` produces side-view pink and overhead red/white/green player sprite frames consistent with the provided screenshots. This resolves the previously reported black-paletted artwork for these two resources. The correct palette *variant* still depends on game state.

**Experimental — PTGT sprite-frame geometry:** after IOBJ metadata, `PTGT` stores frame records and quad geometry. This decoder reads 16 little-endian floats per quad (destination XY and source UV for four corners), builds a bounding box, crops the source atlas, and combines axis-aligned parts. It does not faithfully model general skew, rotation, layered transforms, motion/timing or the complete animation hierarchy. Many resource IDs are atlases rather than complete character sheets.

## One-archive verification record

From the supplied `resarc_cmm` pair, analyzed November 13, 2026:

| Check | Result |
| --- | ---: |
| Index entries | 227 |
| Resources parsed by current image decoder | 227, with 0 failures |
| IOBJ-only | 88 |
| IOBJ + TLPI | 135 |
| Standalone PIXEL | 3 |
| ICDB (nontexture) | 1 |
| Texture/palette images produced | 578 |
| PTGT frame records found | 5,703 |

These numbers are **format and structural validation**, not a guarantee that every rendered sprite frame is visually correct. A separate earlier PNG export with a four-frame cap yielded 765 previews; avoid treating that preview count as the total frame count.

## Research sources

1. [rufaswan — Web2D_Games archived 2021 tools](https://github.com/rufaswan/Web2D_Games/tree/053e9ad099b4e6247dad5652429baa03db1a7891/tools/psxtools), including `pc_gunvolt_irlst-irarc.php` and `quad_pc_gunvolt_IOBJ.php`. Third-party GPL project: **reference only, do not copy into MIT repo**.
2. [VG Resource: Azure Striker Gunvolt 1, 2 and Luminous Avenger iX Sprite Rips](https://archive.vg-resource.com/thread-38568.html), with a May 2021 confirmation that BMZ uses IRLST/IRARC and adds TLPI.

## Unknowns and test plan

- Resource kind values beyond `0x12`/`0x17`, especially `.7` game assets; separate compression vs data-format concerns.
- `ICDB`, `CGFX`, script/config/map/audio sections and full section-code meanings.
- Reliable game/version detection using fingerprints and header structures, rather than filename or title guesses.
- True sprite-animation keyframes, timing, layers, attachment points and non-axis-aligned transforms.
- Palette-selection rules and whether palettes and textures can be referenced across archive resources.
- Asset-name mappings and references from game code/metadata (resource IDs currently have no human-readable names).
- Platform variation: PC/Switch/3DS formats should be treated as separate test targets until verified.

**Next evidence request:** scan **all** `.irlst/.irarc` pairs in the owned BMZ `data/resarc` directory, collect counts and unknown signatures only, manually compare at least 10 sprite frames to in-game reference, and record game build/version plus archive hashes. Keep game files private/local.
