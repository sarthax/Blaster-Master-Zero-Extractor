"""Export BMZ's existing PTGT sprite-frame assembly for NES2PCE review.

This produces transparent PNGs and a manifest, not a native PCE asset.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import re

from .inti import Source, Entry, decode_preview, discover_sources

SCHEMA = "inti-assembled-sprite-sequence/1.0"
MAX_FRAMES = 512
MAX_TOTAL_PNG = 96 * 1024 * 1024


def _bounds(quads):
    points = [point for dst, _uv in quads for point in dst]
    if not points or not all(math.isfinite(v) and abs(v) < 100000 for p in points for v in p):
        return None
    x0 = math.floor(min(p[0] for p in points))
    y0 = math.floor(min(p[1] for p in points))
    x1 = math.ceil(max(p[0] for p in points))
    y1 = math.ceil(max(p[1] for p in points))
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def build_package(source: Source, entry: Entry, dest: Path, variant: int = 0,
                  limit: int = MAX_FRAMES) -> dict:
    """Write a NEW folder containing manifest.json and frames/frame_NNNN.png."""
    if not isinstance(limit, int) or not 1 <= limit <= MAX_FRAMES:
        raise ValueError(f"limit must be from 1 to {MAX_FRAMES}")
    if entry not in source.entries:
        raise ValueError("Resource does not belong to archive")
    dest = Path(dest)
    if dest.exists():
        raise FileExistsError(f"Destination already exists: {dest}")
    raw = source.get_data(entry)
    preview = decode_preview(raw)
    if not preview.frames:
        raise ValueError("Selected resource contains no assembled PTGT sprite frames")
    if not isinstance(variant, int) or not 0 <= variant < len(preview.images):
        raise ValueError("Palette/texture variant is out of range")
    output = []
    total_png = 0
    for frame_index in range(min(len(preview.frames), limit)):
        texture_index, quads = preview.frames[frame_index]
        bbox = _bounds(quads)
        frame = preview.frame_at(frame_index, variant)
        if frame is None:
            output.append(({"index": frame_index, "status": "not_renderable",
                            "ptgt_bounds": bbox, "ptgt_texture": texture_index,
                            "quad_count": len(quads)}, None))
            continue
        memory = io.BytesIO()
        frame.convert("RGBA").save(memory, format="PNG", optimize=False)
        png = memory.getvalue()
        total_png += len(png)
        if total_png > MAX_TOTAL_PNG:
            raise ValueError("Sequence PNG output exceeds 96 MiB limit")
        filename = f"frames/frame_{frame_index:04d}.png"
        record = {"index": frame_index, "status": "rendered",
                  "file": filename, "png_sha256": hashlib.sha256(png).hexdigest(),
                  "width": frame.width, "height": frame.height,
                  "ptgt_bounds": bbox, "ptgt_texture": texture_index,
                  "quad_count": len(quads)}
        output.append((record, png))
    manifest = {
        "schema": SCHEMA,
        "origin": {
            "game": "Blaster Master Zero (PC)",
            "archive": source.path.name,
            "resource_id": f"0x{entry.resource_id:08X}",
            "resource_ordinal": entry.ordinal,
            "entry_kind": entry.kind,
            "resource_sha256": hashlib.sha256(raw).hexdigest(),
            "variant_index": variant,
            "variant_kind": "palette" if preview.palette_count else "texture",
            "variant_count": len(preview.images),
            "classification": preview.classification,
        },
        "assembly": {
            "algorithm": "inti-ptgt-axis-aligned-preview",
            "verification": "experimental_geometry_not_gameplay_verified",
            "timebase": "unknown",
            "offset_meaning": "ptgt_local_bounds_not_nes_gameplay_anchor",
            "source_frame_count": len(preview.frames),
            "exported_frame_count": len(output),
            "limit_applied": len(output) < len(preview.frames),
        },
        "frames": [record for record, _ in output],
    }
    created = False
    try:
        (dest / "frames").mkdir(parents=True, exist_ok=False)
        created = True
        for record, png in output:
            if png is not None:
                (dest / record["file"]).write_bytes(png)
        (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    except Exception:
        if created:
            import shutil
            shutil.rmtree(dest)
        raise
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Export BMZ PTGT frames for NES2PCE comparison")
    parser.add_argument("source", type=Path, help=".irlst/.irarc archive or extracted .17 resource")
    parser.add_argument("resource", help="Hex resource ID (e.g. 0x2104)")
    parser.add_argument("-o", "--output", required=True, type=Path, help="New output folder")
    parser.add_argument("--variant", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=MAX_FRAMES)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"(?:0[xX])?[0-9a-fA-F]{1,8}", args.resource):
        parser.error("resource must be a hexadecimal ID")
    resource_id = int(args.resource, 16)
    sources = discover_sources(args.source, recursive=False)
    matching = [(s, e) for s in sources for e in s.entries if e.resource_id == resource_id]
    if len(matching) != 1:
        parser.error(f"Expected exactly one resource with ID {args.resource}: found {len(matching)}")
    manifest = build_package(*matching[0], args.output, variant=args.variant, limit=args.max_frames)
    print(f"Exported {len(manifest['frames'])} frame records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
