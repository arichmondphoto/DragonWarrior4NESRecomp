"""Export every field map tile at 10x (160x160) for AI image generation.

Input: tools/field_sheet.py's field_tiles.json (one row per palette version;
the first row of each item is its most used colours).

Writes OUT/ (and OUT.zip):
  tiles_pixel/<ID>.png    crisp nearest-neighbour 10x of the original tile
  tiles_smooth/<ID>.png   same colours, staircase edges smoothed into curves
                          and anti-aliased (often a better img2img start)
  atlases/<section>_NN.png  6x6 tiles per 1024x1024 sheet (8 px black gutters)
                          for generators that prefer bigger images, plus
                          atlases/<section>_NN.json (cell -> tile ID)
  palette_versions/<ID>/<ID><v>.png  the tile's other colour versions (only
                          for reference; one drawing per tile is the default)
  style_reference.png     a sample of the owner's monster art
  tiles.csv               ID, section, maps it appears in, number of colour versions
  README.txt              how to generate and how to hand the art back

usage: export_ai_tiles.py FIELD_TILES_JSON OUT
"""
import csv, json, os, shutil, sys
import numpy as np
from PIL import Image
from scipy import ndimage
sys.path.insert(0, os.path.dirname(__file__))
from field_sheet import NES, pixels

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S, N = 10, 160
SECTIONS = {'S': 'shared', 'W': 'overworld', 'T': 'towns', 'D': 'dungeons'}

def colours(cols):
    return np.array([[(NES[c & 0x3F] >> 16) & 255, (NES[c & 0x3F] >> 8) & 255, NES[c & 0x3F] & 255] for c in cols], float)

def pixel_10x(tiles, cols):
    idx = np.array(pixels(tiles))
    return Image.fromarray(colours(cols)[np.kron(idx, np.ones((S, S), int))].astype(np.uint8))

def epx(g):
    A = np.roll(g, 1, 0); D = np.roll(g, -1, 0); C = np.roll(g, 1, 1); B = np.roll(g, -1, 1)
    o = np.zeros((2 * g.shape[0], 2 * g.shape[1]), g.dtype)
    o[0::2, 0::2] = np.where((C == A) & (C != D) & (A != B), A, g)
    o[0::2, 1::2] = np.where((A == B) & (A != C) & (B != D), B, g)
    o[1::2, 0::2] = np.where((D == C) & (D != B) & (C != A), C, g)
    o[1::2, 1::2] = np.where((B == D) & (B != A) & (D != C), D, g)
    return o

def smooth_10x(tiles, cols):
    """EPX x2 (64x64) on the wrapped tile, per-colour soft masks at 320x320,
    winner-takes-all for clean curved shapes, then a 2x downsample for
    anti-aliasing. Wrapping keeps the tile seamless with itself."""
    g4 = epx(epx(np.array(pixels(tiles))))
    labels = np.unique(g4)
    score = np.array([ndimage.gaussian_filter(np.kron((g4 == l).astype(float), np.ones((5, 5))), 2.4, mode='wrap')
                      for l in labels])
    lab = labels[np.argmax(score, 0)]                         # 320x320
    rgb = colours(cols)[lab].reshape(N, 2, N, 2, 3).mean((1, 3))
    return Image.fromarray(np.round(rgb).astype(np.uint8))

def atlas(cells):
    img = Image.new('RGB', (1024, 1024), (0, 0, 0))
    for i, im in enumerate(cells):
        img.paste(im, (12 + (i % 6) * 168, 12 + (i // 6) * 168))
    return img

README = """Dragon Warrior IV — map tiles for AI image generation
=====================================================

{n} tiles, each 160x160 (the game's 16x16 tile at 10x). File names are the
tile IDs from the artwork sheets (field_shared / field_world / field_town /
field_dungeon.png):
  S = shared by several kinds of area   W = overworld
  T = towns, castles, shrines, houses   D = dungeons, caves, towers

Folders
  tiles_pixel/   crisp 10x of the original (exact layout and colours)
  tiles_smooth/  the same with staircase edges smoothed into curves; often the
                 better starting image for image-to-image
  atlases/       36 tiles per 1024x1024 image (6x6 grid, 160 px cells, 8 px black
                 gutters, 12 px margin) for generators that want bigger images.
                 Each atlas has a .json listing the tile ID in each cell, row by
                 row. Keep the grid where it is and I can slice them back apart.
  palette_versions/  other colour versions of a tile, from different maps
                 (underworld, caves, other towns). For reference only.
  style_reference.png  a sample of your monster art
  tiles.csv      every tile with the maps it appears in

Generating
  * Use image-to-image (or a structure/edge control) with each tile as the
    input, plus style_reference.png as the style image, so layout and colours
    are kept while the rendering matches the monsters.
  * Keep the size 160x160 (or generate larger at a multiple and downscale).
    Composition must stay where it is: the game places tiles edge to edge,
    so walls, paths, water and building parts must line up with neighbours.
  * Ground tiles (grass, sand, water, floors, carpets, cave rock, bricks)
    repeat across the map and must tile seamlessly. Ask for "seamless
    tileable texture", or send them back as they are and I'll make the
    edges wrap.
  * Black areas in the originals are mostly outlines or shadows; small
    stray black pixels can be ignored.
  * Suggested prompt: "top-down 2D RPG map tile, {{subject}}, hand-painted
    fantasy illustration in the style of the reference, rich shading, crisp
    dark outlines, same layout and colours as the input, no text, no border".

Handing the art back
  * One PNG per tile, named by ID (S001.png, W012.png, ...), any size that
    is a multiple of 160 (it will be scaled to 160x160), in one folder or zip.
  * Optional: a separate drawing for one colour version, named with its
    letter (W003c.png). Otherwise one drawing per tile covers all of them.
  * Finished atlases can be sent back whole; I'll cut them on the grid.
  * Partial batches are fine; tiles without art keep their 8-bit look.
"""

def main():
    rows = json.load(open(sys.argv[1])); out = sys.argv[2]
    if os.path.exists(out): shutil.rmtree(out)
    for d in ('tiles_pixel', 'tiles_smooth', 'atlases', 'palette_versions'): os.makedirs(os.path.join(out, d))
    items = {}
    for r in rows: items.setdefault(r['item'], []).append(r)
    by_section = {}
    with open(os.path.join(out, 'tiles.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['id', 'section', 'colour_versions', 'used_in'])
        for iid, vs in items.items():
            t, c = bytes.fromhex(vs[0]['chr']), bytes.fromhex(vs[0]['nes_colors'])
            pixel_10x(t, c).save(os.path.join(out, 'tiles_pixel', iid + '.png'))
            sm = smooth_10x(t, c); sm.save(os.path.join(out, 'tiles_smooth', iid + '.png'))
            by_section.setdefault(iid[0], []).append((iid, sm))
            if len(vs) > 1:
                pd = os.path.join(out, 'palette_versions', iid); os.makedirs(pd)
                for v in vs:
                    pixel_10x(t, bytes.fromhex(v['nes_colors'])).save(os.path.join(pd, v['id'] + '.png'))
            used = sorted({m for v in vs for m in v['used_in']})
            w.writerow([iid, vs[0]['section'], len(vs), '; '.join(used)])
    for sec, lst in by_section.items():
        for k in range(0, len(lst), 36):
            chunk = lst[k:k + 36]; name = f'{SECTIONS[sec]}_{k // 36 + 1:02d}'
            atlas([im for _, im in chunk]).save(os.path.join(out, 'atlases', name + '.png'))
            json.dump({'grid': '6x6, 160px cells at x=12+168*col, y=12+168*row',
                       'cells': [iid for iid, _ in chunk]}, open(os.path.join(out, 'atlases', name + '.json'), 'w'), indent=0)
    # style reference from the owner's monster art
    b = json.load(open(os.path.join(HERE, 'hd/monsters/boxes.json')))
    sheet = Image.open(os.path.join(HERE, 'hd/monsters/source/DW4Sprites.jpg')).convert('RGB')
    ref = Image.new('RGB', (1024, 512))
    for i, s in enumerate((0, 9, 20, 28, 40, 60, 75, 140)):
        im = sheet.crop(b[s]); im.thumbnail((250, 250)); ref.paste(im, ((i % 4) * 256 + (256 - im.width) // 2, (i // 4) * 256 + (256 - im.height) // 2))
    ref.save(os.path.join(out, 'style_reference.png'))
    open(os.path.join(out, 'README.txt'), 'w').write(README.format(n=len(items)))
    shutil.make_archive(out, 'zip', os.path.dirname(out), os.path.basename(out))
    print(f'{len(items)} tiles -> {out} (+ .zip)')

if __name__ == '__main__':
    main()
