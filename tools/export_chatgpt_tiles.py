"""Package every map tile for OpenAI's image API (tools/openai_sprites.py),
the way tools/export_chatgpt_sprites.py packages the characters.

Each request is one 1536x1024 sheet of 24 map tiles (6 x 4), each tile
drawn pixel-exact at 15x (240x240) in the palette its art is made for
(hd/field/ids.json), on flat grey with 16 px gaps. Tiles are grouped by
kind of area (shared, overworld, towns, dungeons) and kept in ID order, so a
sheet holds tiles that are used together. The same model, settings and
style image for every sheet keeps the look consistent.

Writes OUT/ (and OUT.zip):
  inputs/<SHEET>.png           the sheet to send (W01, T01, D01, S01 ...)
  prompts/<SHEET>.txt          the message for it
  sheets.json                  sheet -> cell -> tile ID, and the layout
  PROJECT_INSTRUCTIONS.txt     rules sent with every request
  style_reference.png          the owner's monster + character art
  openai_sprites.py            the batch script (same as for the characters)
  README.txt

usage: export_chatgpt_tiles.py FIELD_TILES_JSON OUT
"""
import collections, hashlib, json, os, shutil, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from field_sheet import NES, pixels

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1536, 1024
COLS, ROWS = 6, 4
SC = 15; CELL = 16 * SC                       # 240
GAP = 16
X0 = (W - COLS * CELL - (COLS - 1) * GAP) // 2      # 8
Y0 = (H - ROWS * CELL - (ROWS - 1) * GAP) // 2      # 8
GREY = (140, 140, 140)
SKIP = set()       # tiles come from hd/field/ids.json (the overworld junk tiles W036-W044 aren't in it)

def cell_origin(i):
    return X0 + (i % COLS) * (CELL + GAP), Y0 + (i // COLS) * (CELL + GAP)

KIND = {'S': 'tiles shared by towns, castles and dungeons (floors, walls, stairs, furniture, doors)',
        'W': 'overworld map tiles (grass, forest, hills, mountains, water, shores, desert, swamp, bridges, towns and castles seen from afar)',
        'T': 'town, castle, shrine and house tiles (floors, walls, roofs, counters, furniture, decorations)',
        'D': 'dungeon, cave and tower tiles (rock floors, cave walls, stairs, pits, lava, bricks, statues)'}

PROMPT = """Redraw Image 1 as high-resolution, hand-painted map tiles in the art style of Image 2.

Image 1 is a sheet of 24 separate square map tiles from a top-down 2D fantasy RPG (Dragon Warrior IV): {kind}. Each square is one tile seen from directly above.

Hard rules:
1. Output exactly 1536 x 1024. Keep the same 6 x 4 grid: every tile stays in its own square, at exactly the same position and size as in Image 1, separated by the same grey gaps. Do not move, merge, resize, add or remove tiles.
2. Each tile must fill its whole square, edge to edge, with no border, frame, shadow or vignette: in the game tiles sit side by side and repeat, so textures (grass, water, bricks, floors) must run straight off every edge and continue seamlessly into the next copy of the same tile.
3. Keep each tile's layout: the same shapes in the same places (a wall stays a wall, a path stays where it is, edges between two materials stay on the same line), the same top-down view, the same colours.
4. Same materials look the same in every tile: one consistent grass, water, stone, wood and brick throughout.
5. Add painted detail, soft shading and texture only. No text, no labels, no characters or creatures unless Image 1 shows them.
"""

INSTRUCTIONS = """You redraw 8-bit Dragon Warrior IV (NES) map tiles as high-resolution, hand-painted art for an HD texture pack. Each request attaches:
  Image 1 - a 1536 x 1024 sheet of 24 square map tiles (6 x 4) on flat grey
  Image 2 - the style reference (hand-painted monster and character art from the same pack)

Every result is cut back into tiles by position and laid over the original tiles in the game, side by side. So these rules always apply:
  - Output exactly 1536 x 1024, one image, nothing else.
  - Same grid as Image 1: each tile in the same square at the same size, grey gaps between them.
  - Each tile fills its square to the edges and repeats seamlessly; no frames, borders, drop shadows or vignettes.
  - Keep each tile's layout and colours; same materials look the same everywhere.
  - Top-down orthographic view, painterly but clean, crisp dark outlines on objects, rich but not neon colours.
Generate the image directly; don't ask questions or describe a plan first.
"""

README = """Dragon Warrior IV map tiles - package for OpenAI's image API
==========================================================

{n} map tiles on {s} sheets of 24 (1536x1024 each).

  export OPENAI_API_KEY=sk-...
  python3 openai_sprites.py --dry-run                    # the plan and cost
  python3 openai_sprites.py --ids {pilot}               # pilot: one sheet of each kind
  python3 openai_sprites.py --budget 10                  # the rest

Send back generated/results/ and generated/log.jsonl. The sheets are cut
back into tiles, recoloured for every other palette the game uses (other
towns, night, fades) and made seamless when the pack is built.

sheets.json lists which tile is in which square.
"""

def tile_image(t, pal):
    idx = np.array(pixels(t))
    rgb = np.array([[(NES[c & 0x3F] >> 16) & 255, (NES[c & 0x3F] >> 8) & 255, NES[c & 0x3F] & 255] for c in pal], np.uint8)
    return Image.fromarray(rgb[np.kron(idx, np.ones((SC, SC), int))])

def render_sheet(tiles):
    """[(chr, palette)] -> the 1536x1024 input sheet."""
    im = Image.new('RGB', (W, H), GREY)
    for i, (t, pal) in enumerate(tiles): im.paste(tile_image(t, pal), cell_origin(i))
    return im

def art_tiles(rows):
    """field_tiles.json rows -> {art ID: (chr, palette the art is made for)}
    for the tiles listed in hd/field/ids.json."""
    ids = json.load(open(os.path.join(HERE, 'hd', 'field', 'ids.json')))['ids']
    by_fp = {v[0]: (aid, v[1]) for aid, v in ids.items()}
    out = {}
    for r in rows:
        t = bytes.fromhex(r['chr'])
        hit = by_fp.get(hashlib.sha1(t).hexdigest()[:16])
        if hit is None: continue                       # not in hd/field/ids.json: not a tile to draw
        out.setdefault(hit[0], (t, bytes.fromhex(hit[1])))
    return out

def main():
    rows = json.load(open(sys.argv[1])); out = sys.argv[2]
    tiles = [(aid, t, pal) for aid, (t, pal) in art_tiles(rows).items() if aid not in SKIP]
    tiles.sort(key=lambda x: ('SWTD'.index(x[0][0]), x[0]))
    if os.path.exists(out): shutil.rmtree(out)
    for d in ('inputs', 'prompts'): os.makedirs(os.path.join(out, d))
    sheets = {}
    groups = collections.OrderedDict()
    for t in tiles: groups.setdefault(t[0][0], []).append(t)
    for kind, ts in groups.items():
        for n in range(0, len(ts), COLS * ROWS):
            name = f'{kind}{n // (COLS * ROWS) + 1:02d}'
            part = ts[n:n + COLS * ROWS]
            render_sheet([(t, pal) for aid, t, pal in part]).save(os.path.join(out, 'inputs', name + '.png'))
            cells = [aid for aid, t, pal in part]
            open(os.path.join(out, 'prompts', name + '.txt'), 'w').write(PROMPT.format(kind=KIND[kind]))
            sheets[name] = cells
    json.dump({'layout': {'w': W, 'h': H, 'cols': COLS, 'rows': ROWS, 'cell': CELL, 'gap': GAP, 'x0': X0, 'y0': Y0, 'scale': SC},
               'sheets': sheets}, open(os.path.join(out, 'sheets.json'), 'w'), indent=0)
    # style: the owner's monsters and a few of the new characters
    b = json.load(open(os.path.join(HERE, 'hd/monsters/boxes.json')))
    src = Image.open(os.path.join(HERE, 'hd/monsters/source/DW4Sprites.jpg')).convert('RGB')
    ref = Image.new('RGB', (1024, 1024), GREY)
    for i, s in enumerate((0, 9, 20, 28, 40, 60)):
        m = src.crop(b[s]); m.thumbnail((320, 320))
        ref.paste(m, ((i % 3) * 341 + (341 - m.width) // 2, (i // 3) * 341 + (341 - m.height) // 2))
    for i, cid in enumerate(('C007', 'C017', 'C049')):
        p = os.path.join(HERE, 'hd/sprites/source', cid + '.png')
        if not os.path.exists(p): continue
        sh = Image.open(p).convert('RGBA'); fr = sh.crop((39 + 2 * 374, 117, 39 + 2 * 374 + 336, 117 + 336))
        fr.thumbnail((320, 320)); bg = Image.new('RGBA', fr.size, GREY + (255,)); bg.alpha_composite(fr)
        ref.paste(bg.convert('RGB'), (i * 341 + (341 - fr.width) // 2, 682 + (341 - fr.height) // 2))
    ref.save(os.path.join(out, 'style_reference.png'))
    open(os.path.join(out, 'PROJECT_INSTRUCTIONS.txt'), 'w').write(INSTRUCTIONS)
    shutil.copy(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'openai_sprites.py'), os.path.join(out, 'openai_sprites.py'))
    pilot = ','.join(k for k in sheets if k.endswith('01'))
    open(os.path.join(out, 'README.txt'), 'w').write(README.format(n=len(tiles), s=len(sheets), pilot=pilot))
    shutil.make_archive(out, 'zip', os.path.dirname(out), os.path.basename(out))
    print(f'{len(tiles)} tiles on {len(sheets)} sheets -> {out} (+ .zip); pilot: {pilot}')

if __name__ == '__main__':
    main()
