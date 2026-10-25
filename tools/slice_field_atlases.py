"""Cut the owner's finished map-tile atlases back into one 160x160 tile each.

hd/field/source/<name>.png is a 1024x1024 atlas made from the export
(tools/export_ai_tiles.py): 6x6 cells, 160 px, 8 px black gutters, 12 px
margin; <name>.json lists the tile ID of each cell, row by row. Image
generators move the gutters by a few pixels and sometimes paint across them
(two-tile objects), so each atlas's gutters are found from its own dark
bands near the expected positions, falling back to the export grid.

usage: slice_field_atlases.py OUTDIR   (writes OUTDIR/<ID>.png)
"""
import glob, json, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, 'hd', 'field', 'source')

def bounds(dark_frac):
    """Cell edges along one axis: [start_0, end_0, start_1, ...] for 6 cells."""
    edges = []
    for k in range(7):                              # gutters/margins at 0..6
        expect = 4 + 168 * k if k < 6 else 1018     # centre of margin/gutter in the export
        lo, hi = max(0, expect - 16), min(len(dark_frac), expect + 16)
        dark = [i for i in range(lo, hi) if dark_frac[i] > 0.85]
        if k == 0: edges.append((max(dark) + 1) if dark else 12)
        elif k == 6: edges.append(min(dark) if dark else 1012)
        else:
            if dark: edges += [min(dark), max(dark) + 1]
            else: edges += [172 + 168 * (k - 1), 180 + 168 * (k - 1)]
    return [(edges[2 * i], edges[2 * i + 1]) for i in range(6)]

def main():
    out = sys.argv[1]; os.makedirs(out, exist_ok=True); n = 0
    for js in sorted(glob.glob(os.path.join(SRC, '*.json'))):
        png = js[:-5] + '.png'
        if not os.path.exists(png): continue
        im = Image.open(png).convert('RGB'); a = np.asarray(im.convert('L'))
        cols, rows = bounds((a < 25).mean(0)), bounds((a < 25).mean(1))
        for i, tid in enumerate(json.load(open(js))['cells']):
            (x0, x1), (y0, y1) = cols[i % 6], rows[i // 6]
            im.crop((x0, y0, x1, y1)).resize((160, 160), Image.LANCZOS).save(os.path.join(out, tid + '.png')); n += 1
    print(f'{n} tiles -> {out}')

if __name__ == '__main__':
    main()
