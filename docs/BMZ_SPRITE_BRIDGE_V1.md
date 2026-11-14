# BMZ assembled sprite frame interchange — Inti Asset Explorer

The existing IOBJ/PTGT frame renderer can now export a **new local folder** of assembled transparent PNGs and a metadata-only `manifest.json` for comparison with an NES sprite in NES2PCE Workbench.

Select a resource with frames (side-view Jason candidate `0x2104`; overhead candidate `0x2105`), choose its palette variant, click **Export BMZ frames…**, and choose a parent folder. The exporter creates `BMZ_<archive>_<id>_i<ordinal>_v<variant>/` and will not overwrite it.

CLI equivalent:

```powershell
py -3 -m inti_explorer.sprite_bridge "C:\Games\Blaster Master Zero\data\resarc\resarc_cmm_patch.irlst" 0x2104 -o "C:\Scratch\BMZ_2104" --variant 0
```

The manifest schema is `inti-assembled-sprite-sequence/1.0`. It includes archive basename, resource ID **and ordinal** (IDs can recur), decompressed source SHA-256, palette variant, frame index, PNG SHA-256/dimensions, PTGT-local bounds and rendered/unrenderable status. The original archive remains untouched.

**Do not interpret bounds as gameplay origin or frame indices as timing.** The current assembler supports mostly axis-aligned quads and is an experimental preview, not fully validated game animation. PNGs can include copyrighted game art: keep generated packages outside public Git. This is neither a Mesen HD pack nor a PCE 4bpp export.
