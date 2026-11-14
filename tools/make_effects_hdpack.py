"""Battle sprite effects (the Impostor's Transform smoke and sparkles) from
the owner's art: hd/battle_effects/FX*.png, painted on the sheets of
tools/export_gaps.py (battle_effects/), with pieces.json from that export
(per frame: where the 8-bit frame sits on the sheet, its scale, and every
8x8 sprite's CHR, palette and flips).

Each frame's art (whatever the model drew around that frame's place on the
sheet) is fitted to the 8-bit frame's outline, cut into the frame's 8x8
sprites (stored un-flipped) and appended to OUTDIR/hires.txt. Blank sprites
are skipped (their key would match every empty sprite).

usage: make_effects_hdpack.py ART_DIR OUTDIR [--scale 10]
"""
import argparse, glob, json, os
import numpy as np
from scipy import ndimage
from PIL import Image

SHEET_W, SHEET_H, CELL = 1536, 1024, 256

def bits(chr_hex):
    d = bytes.fromhex(chr_hex)
    return [[((d[y] >> (7 - x)) & 1) | (((d[y + 8] >> (7 - x)) & 1) << 1) for x in range(8)] for y in range(8)]

def outline(frame):
    """The 8-bit frame's opaque pixels as an L mask (its own size)."""
    w, h = frame['size']; m = Image.new('L', (w, h))
    for t in frame['tiles']:
        px = bits(t['chr'])
        for y in range(8):
            for x in range(8):
                if px[7 - y if t['vflip'] else y][7 - x if t['hflip'] else x]:
                    m.putpixel((t['x'] + x, t['y'] + y), 255)
    return m

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('art'); ap.add_argument('outdir'); ap.add_argument('--scale', type=int, default=10)
    a = ap.parse_args(); S = a.scale; T = 8 * S
    pieces = json.load(open(os.path.join(a.art, 'pieces.json')))
    hires = os.path.join(a.outdir, 'hires.txt')
    lines = open(hires).read().splitlines() if os.path.exists(hires) else ['<ver>106', f'<scale>{S}']
    img_index = sum(1 for l in lines if l.startswith('<img>'))
    os.makedirs(os.path.join(a.outdir, 'effects'), exist_ok=True)
    done, n = set(), 0
    for sheet_png in sorted(glob.glob(os.path.join(a.art, 'FX*.png'))):
        name = os.path.splitext(os.path.basename(sheet_png))[0]
        if name not in pieces: continue
        art = Image.open(sheet_png).convert('RGBA').resize((SHEET_W, SHEET_H), Image.LANCZOS)
        frames = pieces[name]
        cuts = []
        for i, f in enumerate(frames):
            w, h = f['size']; k = f['scale']; ox, oy = f['origin']
            # this frame's part of the sheet: halfway to its neighbours
            cx = ox + w * k // 2
            left = (cx + frames[i - 1]['origin'][0] + frames[i - 1]['size'][0] * frames[i - 1]['scale'] // 2) // 2 if i else 0
            right = (cx + frames[i + 1]['origin'][0] + frames[i + 1]['size'][0] * frames[i + 1]['scale'] // 2) // 2 if i + 1 < len(frames) else SHEET_W
            part = art.crop((left, 0, right, SHEET_H))
            # the painted frames overlap: keep only the shapes centred on this
            # frame's place (connected pieces whose centre is inside its box)
            a8 = np.asarray(part.getchannel('A')).copy(); a8[a8 < 24] = 0
            lab, nl = ndimage.label(a8 > 0)
            x0, x1, y0, y1 = ox - left - 24, ox - left + w * k + 24, oy - 24, oy + h * k + 24
            # a neighbour's cloud cut by the window's side edge is not ours
            # (ours may reach the edge too, but is centred on this frame)
            cut = set(np.unique(lab[:, 0])) | set(np.unique(lab[:, -1]))
            mid = ox - left + w * k / 2
            keep = [j + 1 for j, (cy, cx) in enumerate(ndimage.center_of_mass(a8 > 0, lab, range(1, nl + 1)))
                    if x0 <= cx <= x1 and y0 <= cy <= y1 and (j + 1 not in cut or abs(cx - mid) <= w * k * 0.3)]
            a8[~np.isin(lab, keep)] = 0
            al = Image.fromarray(a8); part.putalpha(al)
            bb = al.getbbox()
            if not bb: continue
            part = part.crop(bb)
            # fit to the 8-bit outline's box, centred
            ob = outline(f).getbbox()
            canvas = Image.new('RGBA', (w * S, h * S), (0, 0, 0, 0))
            tw, th = (ob[2] - ob[0]) * S, (ob[3] - ob[1]) * S
            kk = min(tw / part.width, th / part.height)
            sw, sh = max(1, round(part.width * kk)), max(1, round(part.height * kk))
            canvas.alpha_composite(part.resize((sw, sh), Image.LANCZOS),
                                   (ob[0] * S + (tw - sw) // 2, ob[1] * S + (th - sh) // 2))
            for t in f['tiles']:
                key = (t['chr'], t['pal'])
                if key in done or not any(bytes.fromhex(t['chr'])): continue
                done.add(key)
                sl = canvas.crop((t['x'] * S, t['y'] * S, t['x'] * S + T, t['y'] * S + T))
                if t['hflip']: sl = sl.transpose(Image.FLIP_LEFT_RIGHT)
                if t['vflip']: sl = sl.transpose(Image.FLIP_TOP_BOTTOM)
                if sl.getchannel('A').getbbox() is None: sl.putpixel((0, 0), (0, 0, 0, 1))   # replace with nothing
                cuts.append((key, sl))
        if not cuts: continue
        cols = min(16, len(cuts)); rows = (len(cuts) + cols - 1) // cols
        out = Image.new('RGBA', (cols * T, rows * T), (0, 0, 0, 0))
        tiles = []
        for j, ((c, p), sl) in enumerate(cuts):
            x, y = (j % cols) * T, (j // cols) * T
            out.alpha_composite(sl, (x, y))
            tiles.append(f'<tile>{img_index},{c},{p},{x},{y},1,N')
        rel = f'effects/{name}.png'; out.save(os.path.join(a.outdir, rel))
        lines.append(f'<img>{rel}'); lines += tiles; img_index += 1; n += len(tiles)
    open(hires, 'w').write('\n'.join(lines) + '\n')
    print(f'  battle effects: {n} sprites')

if __name__ == '__main__':
    main()
