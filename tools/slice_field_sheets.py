"""Cut map-tile sheets generated from tools/export_chatgpt_tiles.py back into
one 160x160 tile per ID (the format tools/make_field_hdpack.py reads).

hd/field/sheets/<SHEET>.png are the generated sheets, hd/field/sheets/
sheets.json the cell -> tile ID list written by the export. The model tends
to redraw the whole sheet slightly larger/smaller or shifted, so each sheet
is first lined up with its input (rebuilt from the game's tiles) by a small
scale + shift search on blurred brightness; then each 240 px cell is cut a
few pixels inside its edges (the model softens tile edges into the grey
gaps) and scaled to 160x160, and its colours are pulled most of the way to the
original tile's (the model paints darker and duller than the NES palette).
Tiles cut here replace the atlas art
(hd/field/source) for the same IDs.

usage: slice_field_sheets.py FIELD_TILES_JSON OUTDIR [--sheets DIR]
"""
import argparse, json, os, sys
import numpy as np
from PIL import Image, ImageFilter
sys.path.insert(0, os.path.dirname(__file__))
from export_chatgpt_tiles import W, H, CELL, cell_origin, render_sheet, art_tiles, HERE

INSET = 5
MATCH = 0.4          # how far each tile's colours are pulled to the original's

def colour_match(tile, orig, k=MATCH):
    """The model paints in its own palette (often darker and duller than
    the NES colours, black areas turn grey). Fit an RGB affine map (3x3 +
    offset, regularised toward identity) from the tile at 16x16 to the
    original 16x16 tile, and move the art that fraction of the way."""
    a = np.asarray(tile).astype(float); X = np.asarray(tile.resize((16, 16), Image.BOX)).reshape(-1, 3).astype(float)
    Y = np.asarray(orig.resize((16, 16), Image.BOX)).reshape(-1, 3).astype(float)
    Xa = np.hstack([X, np.full((len(X), 1), 255.0)])
    lam = 2000.0 * np.eye(4); prior = np.vstack([np.eye(3), np.zeros((1, 3))])
    M = np.linalg.solve(Xa.T @ Xa + lam, Xa.T @ Y + lam @ prior)
    flat = a.reshape(-1, 3); fit = np.hstack([flat, np.full((len(flat), 1), 255.0)]) @ M
    out = flat + k * (fit - flat)
    return Image.fromarray(np.clip(np.round(out), 0, 255).astype(np.uint8).reshape(a.shape))

def lum(im, f=4):
    a = np.asarray(im.convert('L').resize((W // f, H // f), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2))).astype(float)
    return (a - a.mean()) / (a.std() + 1e-6)

def _search(src, r0, f, scales, centre, rng):
    best = (-1e9, 1.0, 0, 0)
    for s in scales:
        sw, sh = round(W * s), round(H * s)
        sm = src.resize((max(1, sw // f), max(1, sh // f)), Image.BILINEAR).filter(ImageFilter.GaussianBlur(2))
        a = np.asarray(sm).astype(float); a = (a - a.mean()) / (a.std() + 1e-6)
        if centre is None: cx, cy = round((W - sw) / 2 / f), round((H - sh) / 2 / f)
        else: cx, cy = round(centre[0] / f), round(centre[1] / f)
        for dy in range(cy - rng, cy + rng + 1):
            for dx in range(cx - rng, cx + rng + 1):
                y0, x0 = max(0, dy), max(0, dx)
                y1, x1 = min(r0.shape[0], dy + a.shape[0]), min(r0.shape[1], dx + a.shape[1])
                if y1 - y0 < r0.shape[0] * 0.8 or x1 - x0 < r0.shape[1] * 0.8: continue
                v = (r0[y0:y1, x0:x1] * a[y0 - dy:y1 - dy, x0 - dx:x1 - dx]).mean()
                if v > best[0]: best = (v, float(s), dx * f, dy * f)
    return best

def register(res, ref):
    """Best (score, scale, dx, dy) mapping the result onto the input layout:
    a coarse search at 1/4 size, then a fine one at 1/2 around it."""
    src = res.convert('L')
    v, s, dx, dy = _search(src, lum(ref, 4), 4, np.arange(0.95, 1.051, 0.01), None, 10)
    return _search(src, lum(ref, 2), 2, np.arange(s - 0.006, s + 0.0061, 0.002), (dx, dy), 3)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('field_tiles'); ap.add_argument('out')
    ap.add_argument('--sheets', default=os.path.join(HERE, 'hd', 'field', 'sheets'))
    ap.add_argument('--match', type=float, default=MATCH, help='colour pull toward the original (0-1)'); a = ap.parse_args()
    meta = os.path.join(a.sheets, 'sheets.json')
    if not os.path.exists(meta): print('  no generated sheets'); return
    sheets = json.load(open(meta))['sheets']
    tiles = art_tiles(json.load(open(a.field_tiles)))
    os.makedirs(a.out, exist_ok=True); n = 0
    for name, cells in sheets.items():
        p = os.path.join(a.sheets, name + '.png')
        if not os.path.exists(p): continue
        src = Image.open(p).convert('RGBA')
        res = Image.new('RGBA', src.size, (0, 0, 0, 255)); res.alpha_composite(src)   # transparent = black (as in the game)
        res = res.convert('RGB').resize((W, H), Image.LANCZOS)
        ref = render_sheet([tiles[c] for c in cells])
        score, s, dx, dy = register(res, ref)
        # put the result into the input's frame: scale about the origin, then shift
        placed = Image.new('RGB', (W, H), (140, 140, 140))
        placed.paste(res.resize((round(W * s), round(H * s)), Image.LANCZOS), (dx, dy))
        for i, aid in enumerate(cells):
            x, y = cell_origin(i)
            cut = placed.crop((x + INSET, y + INSET, x + CELL - INSET, y + CELL - INSET)).resize((160, 160), Image.LANCZOS)
            if a.match > 0: cut = colour_match(cut, ref.crop((x, y, x + CELL, y + CELL)), a.match)
            cut.save(os.path.join(a.out, aid + '.png'))
            n += 1
        print(f'  {name}: {len(cells)} tiles (scale {s:.2f}, shift {dx:+d},{dy:+d}, match {score:.2f})')
    print(f'{n} tiles from generated sheets -> {a.out}')

if __name__ == '__main__':
    main()
