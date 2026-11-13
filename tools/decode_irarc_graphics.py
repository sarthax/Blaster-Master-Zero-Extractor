#!/usr/bin/env python3
"""Decode pixel/IOBJ/TLPI resources from *already decompressed* Inti Creates .17 files.

Format observations verified on Blaster Master Zero resarc_cmm.
This is a best-effort texture and axis-aligned sprite-frame renderer, not a
complete game-engine-compatible animation reassembler.

Requires: Python 3.9+, Pillow (`py -3 -m pip install pillow`)

Examples:
  py -3 decode_irarc_graphics.py irarc_extracted --recursive --frames
  py -3 decode_irarc_graphics.py irarc_extracted -o irarc_graphics --recursive --frames --max-frames 0
  py -3 decode_irarc_graphics.py irarc_extracted/resarc_cmm/00002202.17 --frames
"""
import argparse
from collections import Counter
import csv
import math
from pathlib import Path
import struct
import sys

try:
    from PIL import Image, ImageChops
except ImportError:
    raise SystemExit('Missing Pillow: install with  py -3 -m pip install pillow')

SECT_SIZE = struct.Struct('<IIII')
MAX_PIXELS = 32 * 1024 * 1024


def u32(data, ofs):
    return struct.unpack_from('<I', data, ofs)[0]


def sections(blob):
    """Outer resource structure: count then 16-byte section directory."""
    if len(blob) < 4:
        raise ValueError('resource too short')
    count = u32(blob, 0)
    if count > 512 or 4 + 16 * count > len(blob):
        raise ValueError('bad outer section table')
    result = []
    for i in range(count):
        code, _, offset, length = SECT_SIZE.unpack_from(blob, 4 + i * 16)
        if offset + length > len(blob) or length < 16:
            raise ValueError(f'bad section range #{i}')
        body = blob[offset:offset + length]
        kind = body[:4].decode('ascii', errors='replace') if body[:4] in (b'IOBJ', b'TLPI', b'ICDB', b'CGFX') else 'PIXEL'
        result.append((kind, code, body))
    return result


def read_texture(body, offset):
    if offset + 0x80 > len(body):
        raise ValueError('texture header out of bounds')
    size, w, h, fmt = struct.unpack_from('<IIII', body, offset)
    if not (0 < w <= 8192 and 0 < h <= 8192 and w * h <= MAX_PIXELS):
        raise ValueError(f'invalid image dimensions {w}x{h}')
    nbytes_per_pixel = {4: 4, 5: 2}.get(fmt)
    if nbytes_per_pixel is None:
        raise ValueError(f'unsupported pixel encoding {fmt}')
    if size != w * h * nbytes_per_pixel:
        raise ValueError(f'bad texture byte size {size} for {w}x{h}, format {fmt}')
    if offset + 0x80 + size > len(body):
        raise ValueError('truncated texture')
    return w, h, fmt, body[offset + 0x80:offset + 0x80 + size]


def decode_bgra(w, h, fmt, pix):
    if fmt == 4:
        return Image.frombytes('RGBA', (w, h), pix, 'raw', 'BGRA')
    # documented 16-bit BGRA4444 variant; not present in resarc_cmm.
    rgba = bytearray(w * h * 4)
    for i in range(w * h):
        lo, hi = pix[2 * i], pix[2 * i + 1]
        rgba[4*i:4*i+4] = bytes(((hi & 15)*17, ((lo >> 4) & 15)*17,
                                   (lo & 15)*17, ((hi >> 4) & 15)*17))
    return Image.frombytes('RGBA', (w, h), bytes(rgba))


def parse_tlpi(body):
    if body[:4] != b'TLPI' or len(body) < 16:
        raise ValueError('not TLPI')
    count, colors = struct.unpack_from('<HH', body, 4)
    if colors != 256 or not (1 <= count <= 256):
        raise ValueError(f'unexpected TLPI structure: {count} palettes x {colors} colors')
    if 16 + count * colors * 4 > len(body):
        raise ValueError('truncated TLPI color tables')
    palette_tables = []
    for i in range(count):
        bgra = body[16 + 1024 * i:16 + 1024 * (i+1)]
        rgb = bytearray(768)
        alpha = bytearray(256)
        for j in range(256):
            b, g, r, a = bgra[j*4:j*4+4]
            rgb[j*3:j*3+3] = bytes((r,g,b))
            alpha[j] = a
        palette_tables.append((bytes(rgb),bytes(alpha)))
    return palette_tables


def decode_tlpi_texture(w, h, fmt, pix, palette):
    if fmt != 4:
        raise ValueError('TLPI image expected 32-bit BGRA container')
    # Verified on BMZ: B=0, R=index (0..255), G often 255-index, A=transparency.
    # Older scripts used B & 0x7F, producing wrong images on this title.
    indices = pix[2::4]
    pixel_alpha = pix[3::4]
    indexed = Image.frombytes('P', (w,h), indices)
    rgb, alpha = palette
    indexed.putpalette(rgb)
    indexed.info['transparency'] = alpha
    rgba = indexed.convert('RGBA')
    rgba.putalpha(ImageChops.multiply(rgba.getchannel('A'), Image.frombytes('L',(w,h),pixel_alpha)))
    return rgba


def parse_iobj(body):
    if body[:4] != b'IOBJ':
        raise ValueError('not IOBJ')
    anim_off, ptgt_off, n_tex = struct.unpack_from('<III', body,4)
    if not (0 <= n_tex <= 64 and 16 + n_tex * 4 <= len(body)):
        raise ValueError('invalid IOBJ texture count')
    textures = []
    for j in range(n_tex):
        offset = u32(body, 16 + j * 4)
        textures.append(read_texture(body, offset))
    if body[ptgt_off:ptgt_off+4] != b'PTGT':
        raise ValueError('missing PTGT frames')
    if not (16 <= anim_off <= ptgt_off):
        raise ValueError('invalid animation/frames offsets')
    count = u32(body, ptgt_off + 8)
    if count > 50000 or ptgt_off + 12 + count*8 > len(body):
        raise ValueError('invalid frame table')
    frames = []
    quadptr = ptgt_off + 12 + count*8
    for fi in range(count):
        row = ptgt_off + 12 + fi*8
        quad_count = body[row + 4]
        tex_id = body[row + 5]
        if quadptr + quad_count*64 > len(body):
            raise ValueError(f'frame {fi} quads past IOBJ end')
        quads = []
        for qi in range(quad_count):
            raw = struct.unpack_from('<16f',body,quadptr)
            quadptr += 64
            quads.append(([(raw[k],raw[k+1]) for k in (0,4,8,12)],
                          [(raw[k],raw[k+1]) for k in (2,6,10,14)]))
        frames.append((tex_id, quads))
    return textures, frames


def render_frame(textures, tex_id, quads, max_dim=1600):
    if not quads or not (0 <= tex_id < len(textures)):
        return None
    # Most BMZ quads are axis aligned. Skewed/perspective transforms omitted here.
    clean = []
    for dst, uv in quads:
        vals = [k for tup in (dst + uv) for k in tup]
        if not all(math.isfinite(x) and abs(x) < 100000 for x in vals):
            continue
        left, right = min(x for x,y in dst), max(x for x,y in dst)
        top, bottom = min(y for x,y in dst), max(y for x,y in dst)
        if right - left < 0.1 or bottom - top < 0.1:
            continue
        clean.append((dst, uv, left, right, top, bottom))
    if not clean:
        return None
    x0 = math.floor(min(q[2] for q in clean))
    y0 = math.floor(min(q[4] for q in clean))
    x1 = math.ceil(max(q[3] for q in clean))
    y1 = math.ceil(max(q[5] for q in clean))
    if x1-x0 > max_dim or y1-y0 > max_dim or x1 <= x0 or y1 <= y0:
        return None
    out = Image.new('RGBA',(x1-x0,y1-y0),(0,0,0,0))
    texture = textures[tex_id]
    tw,th=texture.size
    for dst,uv,left,right,top,bottom in clean:
        # Source quads are normalized 0..1 (usually pixel-accurate fractions).
        u0 = min(p[0] for p in uv); u1 = max(p[0] for p in uv)
        v0 = min(p[1] for p in uv); v1 = max(p[1] for p in uv)
        srcbox=(max(0,min(tw,round(u0*tw))),max(0,min(th,round(v0*th))),
                max(0,min(tw,round(u1*tw))),max(0,min(th,round(v1*th))))
        if srcbox[2]<=srcbox[0] or srcbox[3]<=srcbox[1]:
            continue
        patch=texture.crop(srcbox)
        ox,oy=round(left-x0),round(top-y0)
        ow,oh=round(right-left),round(bottom-top)
        if ow<=0 or oh<=0: continue
        if patch.size != (ow,oh):
            patch=patch.resize((ow,oh), Image.Resampling.NEAREST)
        # In corner order right/top, right/bottom, left/bottom, left/top,
        # flip if source orientation differs from destination orientation.
        dx = dst[0][0]-dst[3][0]
        sx = uv[0][0]-uv[3][0]
        dy = dst[1][1]-dst[0][1]
        sy = uv[1][1]-uv[0][1]
        if dx*sx < 0: patch=patch.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if dy*sy < 0: patch=patch.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        out.alpha_composite(patch,(ox,oy))
    return out


def process_one(path, dest, args, rows):
    blob=path.read_bytes()
    sects=sections(blob)
    kinds=[s[0] for s in sects]
    outdir=dest / path.stem
    images=[]
    frames=[]
    classifications=[]
    if 'IOBJ' in kinds:
        obj=next(body for name,code,body in sects if name=='IOBJ')
        textures,frames=parse_iobj(obj)
        palbody=next((body for name,code,body in sects if name=='TLPI'),None)
        if palbody is not None:
            palettes=parse_tlpi(palbody)
            if len(textures)!=1:
                raise ValueError('TLPI resource with more than 1 texture not yet supported')
            w,h,fmt,pix=textures[0]
            images=[decode_tlpi_texture(w,h,fmt,pix,pal) for pal in palettes]
            classifications.append('IOBJ+TLPI')
        else:
            images=[decode_bgra(*t) for t in textures]
            classifications.append('IOBJ')
    elif all(name=='PIXEL' for name,code,body in sects):
        images=[decode_bgra(*read_texture(body,0)) for name,code,body in sects]
        classifications.append('PIXEL')
    else:
        classifications.extend(kinds)
    classification='+'.join(classifications)
    if not images:
        rows.append(dict(resource=str(path), classification=classification, image='', width='',height='',frames=0, status='nontexture'))
        return 0,0,classification
    outdir.mkdir(parents=True,exist_ok=True)
    saved=0
    for i, im in enumerate(images):
        target=outdir / f'texture_{i:02d}.png'
        if args.overwrite or not target.exists():
            im.save(target)
        saved+=1
        rows.append(dict(resource=str(path), classification=classification, image=str(target),width=im.width,height=im.height,frames=len(frames),status='png'))
    rendered=0
    if args.frames and frames:
        sub=outdir/'frames'
        limit=len(frames) if args.max_frames==0 else min(len(frames),args.max_frames)
        for i,(tex_id,quads) in enumerate(frames[:limit]):
            frame=render_frame(images,tex_id,quads)
            if frame is None: continue
            sub.mkdir(exist_ok=True)
            target=sub / f'frame_{i:04d}.png'
            if args.overwrite or not target.exists():
                frame.save(target)
            rendered+=1
    return saved,rendered,classification


def main():
    p=argparse.ArgumentParser(description='Convert extracted Inti Creates .17 resources to PNG atlases and optional sprite frames')
    p.add_argument('input',type=Path,help='A .17 file or an already-extracted directory')
    p.add_argument('-o','--output',type=Path,help='Output root directory (default: <input>/irarc_graphics or sibling)')
    p.add_argument('--recursive',action='store_true',help='Include .17 files in subfolders')
    p.add_argument('--frames',action='store_true',help='Also render reconstructed sprite frames (best effort)')
    p.add_argument('--max-frames',type=int,default=24,help='Max preview frames per resource, 0 for all (default: 24)')
    p.add_argument('--overwrite',action='store_true')
    args=p.parse_args()
    if args.max_frames<0:
        p.error('--max-frames must be >= 0')
    src=args.input.expanduser().resolve()
    if src.is_file():
        files=[src]
        root=src.parent
        outroot=args.output or src.parent/'irarc_graphics'
    else:
        if not src.is_dir():p.error(f'Input does not exist: {src}')
        files=sorted(src.rglob('*.17') if args.recursive else src.glob('*.17'))
        root=src
        outroot=args.output or src/'irarc_graphics'
    outroot=outroot.expanduser().resolve()
    if not files:p.error(f'No .17 resource files found in {src}')
    outroot.mkdir(parents=True,exist_ok=True)
    rows=[];ok=0;failed=0;atlas=0;render=0;types=Counter()
    for idx,file in enumerate(files,1):
        try:
            relative=file.parent.relative_to(root)
            dest=outroot/relative
            a,r,k=process_one(file,dest,args,rows)
            ok+=1;atlas+=a;render+=r;types[k]+=1
            print(f'[{idx}/{len(files)}] {file.name}: {k}: {a} texture(s), {r} frame(s)')
        except (OSError, ValueError,struct.error,IndexError, OverflowError) as exc:
            failed+=1
            print(f'[{idx}/{len(files)}] ERROR {file}: {exc}',file=sys.stderr)
            rows.append(dict(resource=str(file),classification='',image='',width='',height='',frames=0,status='ERROR: '+str(exc)))
    manifest=outroot/'graphics_manifest.csv'
    with manifest.open('w',newline='',encoding='utf-8-sig') as fh:
        writer=csv.DictWriter(fh,fieldnames=['resource','classification','image','width','height','frames','status'])
        writer.writeheader();writer.writerows(rows)
    print(f'\nDone: {ok} resources scanned, {failed} failed; {atlas} texture PNGs; {render} frame previews')
    print('Resource types:',dict(types))
    print('Manifest:',manifest)
    return 1 if failed else 0

if __name__=='__main__':sys.exit(main())
