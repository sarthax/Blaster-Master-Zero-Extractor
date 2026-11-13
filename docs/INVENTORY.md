# Archive inventory research workflow

The inventory is a **read-only, metadata-only** exploration of a local Inti archive directory. It does not create texture PNGs, sprite sheets, audio files or extracted game resources. Only archives in the tested BMZ PC IRLST/IRARC layout are recognized; files from other games require independent compatibility testing.

## Collecting full-game evidence

On Windows, open the application, choose the game's `data\resarc` folder, then click **Export inventory…**. Save the JSON (a CSV is written alongside). Or use the headless command:

```powershell
py -3 -m inti_explorer.inventory "C:\Games\Blaster Master Zero\data\resarc" -o "C:\Reports\bmz_inventory.json"
```

The scanner recursively finds every `.irlst`/`.irarc` pair, checks entry bounds, decompresses one resource at a time under a 256 MiB per-entry limit, parses section directories, and records known texture metadata without generating images. Use `--shallow` to scan only the selected directory and `--max-unpacked-mib 64` to lower the per-entry cap. It also supports a single `.irlst` or `.irarc` file.

- **JSON:** one `sources` record per readable pair (archive/index SHA-256, relative filenames, sizes), one `resources` record per resource, a `pair_errors` array, and aggregate `summary` counts.
- **CSV:** one row per resource for spreadsheet filtering by source, ID, type, section signature, dimensions, count, and status. It does not include a separate row for broken pairs; check the JSON `pair_errors` for those.
- **Statuses:** `metadata_ok` for structurally recognized graphics, `unrecognized` for valid section tables without a supported graphics decoder, `parse_error` for malformed/unsupported payload structure, `read_error` for entries that cannot be read or decompressed. A parse error is evidence to investigate, *not* proof that an archive is corrupt.
- **Section signatures:** `IOBJ`, `TLPI`, `ICDB`, `CGFX` are recognized by literal bytes; `PIXEL` is assigned only after a standalone texture header validates. Other signatures are `UNKNOWN`, with first four bytes retained as `magic_hex`.
- **Resource fingerprints:** SHA-256 hashes of decoded resources help identify duplicates across archives. They are metadata, not the resource bytes.

The report uses **relative paths** (relative to the scanned root) to avoid saving local Windows usernames/drive paths. The JSON may still contain archive/resource hashes and structural metadata, so inspect it before posting publicly. Neither format contains copyrighted textures themselves.

## Verified baseline (one supplied archive only)

`resarc_cmm.irlst` + `resarc_cmm.irarc`, BMZ PC, scanned November 13, 2026:

| Classification | Resource count |
|---|---:|
| IOBJ | 88 |
| IOBJ+TLPI | 135 |
| PIXEL (single section) | 2 |
| PIXEL×5 (five sections) | 1 |
| ICDB | 1 |
| **Total** | **227** |

- 226 resources have parsable graphics metadata; `0x00000F00` is an `ICDB` resource, preserved without a speculative decoder.
- The total `PIXEL` section count is seven across three resources.
- The scan reported zero read or parse failures on this pair.
- It does not establish support for any other archive pair, console release, or game.

## Follow-up research

1. Run the inventory against **all** original `.irlst/.irarc` pairs from a locally owned BMZ PC game folder and retain the metadata reports. Review `pair_errors`, then group `unrecognized` and `parse_error` by `source`, `entry_kind`, and `magic_hex`.
2. Compare hashes for exact duplicate decoded resources across archives. An ID collision with a different resource hash should not automatically be treated as an update; verify archive precedence from the game first.
3. Prioritize `ICDB` and newly observed signatures. Do not infer content based on marker text alone; link structural hypotheses to representative byte offsets and reproducible tests.
4. Keep local archive bytes and extracted sprites out of this public repository. Only share metadata after inspection.

The inventory is **not** a renderer and cannot prove sprite correctness. Continue frame/sprite parity work separately under issue #3.
