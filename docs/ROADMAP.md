# Product and research roadmap

## Goal

Provide a general-purpose local read-only **game asset explorer**, beginning with PC *Blaster Master Zero*. Users should be able to choose a game directory and visually discover sprites, atlas images, palettes and eventually animations, audio and metadata without needing a command-line extraction chain.

## Milestone A — usable BMZ explorer (this PR)

- [x] Read a chosen IRLST/IRARC pair or recursively discover pairs in a directory.
- [x] Display resource IDs, kind, compressed size and basic structure metadata.
- [x] Preview BGRA/IOBJ/TLPI textures, choose palette or texture variant.
- [x] Preview PTGT frame geometry (explicitly marked experimental).
- [x] On-demand thumbnail gallery and ID search.
- [x] Export a selected PNG, decompressed resource, or all resources from one archive.
- [x] Safety checks on archive offsets, decompressed size, and pixel dimensions.
- [x] Synthetic automated tests and original-archive read-only validation.
- [ ] Manually inspect Windows native GUI and game sprite correctness against playback.

## Milestone B — make sprite browsing useful

- [x] Multi-archive asset catalog with metadata search, type/archive filters and on-demand, **paged** thumbnail decoding (first slice).
- [ ] True scrolling virtualization and an opt-in persistent thumbnail cache, with fingerprint-based invalidation.
- [ ] Named/annotated assets, tags, categories, favorites, filtering by dimensions/transparency.
- [ ] Proper animation timeline with per-frame durations, offsets/layers and playback.
- [ ] Validate sprite reconstruction against screenshots; fix rotations, flipping, arbitrary quads and subframe transforms.
- [ ] Batch export PNG atlas, cropped sprites, frame sequences and contact sheets with manifests.
- [x] Scan unknown sections without failing the whole resource; produce a structured JSON/CSV signature inventory (first BMZ archive validated; all-game acceptance pending).
- [x] Archive/resource SHA-256 fingerprint and section manifest; game/version identification and decoder confidence remain research tasks.

## Milestone C — platform and game adapters

- [ ] Replace direct `tools/` coupling with a `FormatAdapter` protocol and explicit capability flags.
- [ ] Register decoder by recognized magic/version rather than file suffix alone.
- [ ] Test at least one Azure Striker Gunvolt title against known source examples.
- [ ] Investigate other Inti Creates games/releases without assuming identical format layouts.
- [ ] Explore font, UI, sound, map and script formats, each behind independent decoders.
- [ ] Read-only hex/structure viewer and per-resource cross-reference graph.

## Definition of done for each new game

1. At least two representative archives identified and the archive format/version recorded.
2. Index bounds and decompression negative tests pass; unknown kinds fail safely.
3. Ten or more image previews visually compared to game screenshots, including alpha and alternate palettes.
4. Unrecognized sections counted and preserved for export, never silently discarded.
5. Manifest, supported capabilities, failure modes and commands documented.
6. Test fixtures are synthetic or permission-cleared; do not commit proprietary game assets.

## Explicit non-goals for now

- No archive repacking or in-game modification.
- No distribution of sprites, music, or game binaries.
- No claim that all Inti Creates titles share one engine or compression method.
- No large-scale automated cross-game claims based only on one archive.
