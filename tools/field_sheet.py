"""Artwork checklist for the field graphics: every unique 16x16 map tile
(metatile) of the overworld, towns/castles/shrines and dungeons, as numbered
sheets for drawing HD replacements.

Input: tools/capture_field.py output. For each captured map, each of its 32
metatiles ($7600 tile numbers, $76C0 sub-palette; overworld adds 16
shoreline variants at $7680, sub-palette 0) is rendered from the map's CHR RAM
and palette. A piece of art is identified by its 4 tiles' CHR bytes + its 4
colours; pieces with the same tiles in other colours are listed as colour
variants of one item (a, b, c ...), next to each other.

Items are numbered per section in the order the game's maps first use them,
so pieces of one building or wall set stay together:
  S  shared: used in more than one kind of area (chests, stairs, doors...)
  W  overworld (incl. the underworld and other overworld-style areas)
  T  towns, castles, shrines and houses
  D  dungeons, caves and towers
Each sheet cell shows one item large (its most used colours) with every
colour variant small underneath. Colour variants come from each map's own
palette; one drawing per item can usually serve all of them. Variants whose
colours are all black (a map faded or unlit) and tiles that are nothing but
the backdrop colour are left out.

Writes OUT/field_<section>.png (4x, labelled), OUT/field_tiles.csv and
OUT/field_tiles.json (id, variant, maps that use it, NES colours, CHR bytes).

usage: field_sheet.py CAPTURE OUT [--scale 4]
"""
import argparse, csv, glob, json, os, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load

def _nes_palette():
    """The game's own colours: a port of nesrecomp runner/cyc/hw_palette.c
    (NTSC signal decode of the 2C02 levels), emphasis off."""
    import math
    lo, hi = (0.350, 0.518, 0.962, 1.550), (1.094, 1.506, 1.962, 1.962)
    black, white = 0.518, 1.962
    byte = lambda c: 0 if c <= 0 else 255 if c >= 1 else int(c * 255.0 + 0.5)
    out = []
    for i in range(64):
        hue, level = i & 15, (i >> 4) & 3
        if hue > 13: level = 1
        l, h = lo[level], hi[level]
        if hue == 0: l = h
        if hue > 12: h = l
        y = u = v = 0.0
        for p in range(12):
            sig = h if (hue + p) % 12 < 6 else l
            sig = (sig - black) / (white - black); ang = math.pi * (p - 0.5) / 6.0
            y += sig; u += sig * math.cos(ang); v -= sig * math.sin(ang)
        y /= 12; u *= 2 / 12; v *= 2 / 12
        r, g, b_ = y + 1.140 * v, y - 0.395 * u - 0.581 * v, y + 2.032 * u
        out.append(byte(r) << 16 | byte(g) << 8 | byte(b_))
    return out
NES = _nes_palette()
MAPS = ['Keeleon','Santeem','Burland','Dire Palace','Endor','Bonmalmo','Branca','Soretta','Gardenbur','Stancia','Aktemto','Riverton',
        'Bazaar','Mintos','Tempe','Frenor','Aneaux','Haville','Izmit','Surene','Hometown','Monbaraba','Lakanaba','Kievs','Foxville',
        'Seaside Village','Gottside','Rosaville','Secret Playground Entrance','House of Prophecy','Shrine to Endor','Shrine NW of Endor',
        "Woodsman's Shack",'Desert Inn','Small Medal King','Shrine N of Soretta','Small Island Shack','Royal Crypt Entrance','Last Refuge',
        'SW barrier shrine','SE barrier shrine','NW barrier shrine','Final Cave entrance','Travel Door near Riverton',
        'Shrine of Colossus (outside)','Aktemto Mine','Shrine of Breaking Waves','Padaquea Cave',"Bakor's Hideout",
        'Sphere of Silence Cave','Golden Bracelet Cave','Secret Playground Dungeon','Cascade Cave','Final Cave','Iron Safe Cave',
        'Cave of Betrayal','Silver Statuette Cave','Branca-Izmit tunnel','Branca-Endor tunnel','Royal Crypt',"Necrosaro's Lair",
        'Zenethian Tower','Outside Zenethia','Birdsong Tower','World Tree','Loch Tower','Lighthouse','Konenber','NE barrier shrine',
        "Necrosaro's Palace",'Zenethia','Shrine of the Horn','Shrine of Colossus']
DUNGEON = set(range(0x2D, 0x43)) | {0x44, 0x45, 0x47, 0x48}
BLACK = {0x0D, 0x0E, 0x0F, 0x1D, 0x1E, 0x1F, 0x2E, 0x2F, 0x3E, 0x3F}
SECTIONS = [('S', 'shared', 'Shared by several kinds of area'), ('W', 'world', 'Overworld'), ('T', 'town', 'Towns, castles, shrines and houses'),
            ('D', 'dungeon', 'Dungeons, caves and towers')]

def pixels(tiles):
    """16x16 colour indices of a metatile (4 x 16 CHR bytes, TL TR BL BR)."""
    out = [[0] * 16 for _ in range(16)]
    for q in range(4):
        d = tiles[16 * q:16 * q + 16]; ox, oy = (q % 2) * 8, (q // 2) * 8
        for y in range(8):
            for x in range(8):
                out[oy + y][ox + x] = ((d[y] >> (7 - x)) & 1) | (((d[y + 8] >> (7 - x)) & 1) << 1)
    return out

def render(tiles, cols, S):
    im = Image.new('RGB', (16, 16)); px = pixels(tiles)
    for y in range(16):
        for x in range(16):
            c = NES[cols[px[y][x]] & 0x3F]; im.putpixel((x, y), (c >> 16, (c >> 8) & 255, c & 255))
    return im.resize((16 * S, 16 * S), Image.NEAREST)

def collect(cap):
    shapes, order = {}, []          # tiles -> {'cat', 'variants': {cols: set(maps)}}
    for path in sorted(glob.glob(os.path.join(cap, '*.mem')), key=lambda p: (not p.endswith('world.mem'), p)):
        m = load(path); w, ch, pal, ram = m['wram'], m['chr_ram'], m['palette'], m['ram']
        if max(pal[:16]) == min(pal[:16]): continue                      # screen still faded out
        world = ram[0x28] == 0
        cat = 'world' if world else 'dungeon' if ram[0x63] in DUNGEON else 'town'
        where = ('Underworld' if ram[0x63] == 0x45 else 'Overworld') if world else MAPS[ram[0x63]]
        defs = [(bytes(w[0x1600 + 4 * i:0x1604 + 4 * i]), w[0x16C0 + i] & 3) for i in range(32)]
        if world: defs += [(bytes(w[0x1680 + 4 * i:0x1684 + 4 * i]), 0) for i in range(16)]
        for t, p in defs:
            if any(x < 0x8D for x in t): continue                         # unused slot
            tiles = b''.join(bytes(ch[0x1000 + 16 * x:0x1010 + 16 * x]) for x in t)
            px = pixels(tiles)
            used = {v for row in px for v in row}
            if used == {0}: continue                                       # backdrop only
            cols = bytes([pal[0], pal[4 * p + 1], pal[4 * p + 2], pal[4 * p + 3]])
            if all(cols[v] & 0x3F in BLACK for v in used): continue          # unlit / faded
            if tiles not in shapes: shapes[tiles] = {'cats': set(), 'variants': {}}; order.append(tiles)
            shapes[tiles]['cats'].add(cat)
            shapes[tiles]['variants'].setdefault(cols, set()).add(where)
    # Second pass: colours actually on screen. Some maps recolour parts of a
    # tileset (palette overrides), so add on-screen colours of known tiles.
    # (Unknown on-screen shapes are half-drawn rows at the scroll seam.)
    for path in sorted(glob.glob(os.path.join(cap, '*.mem'))):
        m = load(path); ci, ch, pal, ram = m['ciram'], m['chr_ram'], m['palette'], m['ram']
        if max(pal[:16]) == min(pal[:16]): continue
        world = ram[0x28] == 0
        where = ('Underworld' if ram[0x63] == 0x45 else 'Overworld') if world else MAPS[ram[0x63]]
        for o in (0, 0x400):
            for r in range(0, 30, 2):
                for c in range(0, 32, 2):
                    t = [ci[o + r * 32 + c], ci[o + r * 32 + c + 1], ci[o + (r + 1) * 32 + c], ci[o + (r + 1) * 32 + c + 1]]
                    if min(t) < 0x8D: continue
                    tiles = b''.join(bytes(ch[0x1000 + 16 * x:0x1010 + 16 * x]) for x in t)
                    if tiles not in shapes: continue
                    at = ci[o + 0x3C0 + (r // 4) * 8 + c // 4]; p = (at >> (((r % 4) // 2) * 4 + ((c % 4) // 2) * 2)) & 3
                    cols = bytes([pal[0], pal[4 * p + 1], pal[4 * p + 2], pal[4 * p + 3]])
                    used = {v for row in pixels(tiles) for v in row}
                    if all(cols[v] & 0x3F in BLACK for v in used): continue
                    shapes[tiles]['variants'].setdefault(cols, set()).add(where)
    for sh in shapes.values():
        sh['cat'] = 'shared' if len(sh['cats']) > 1 else next(iter(sh['cats']))
    return shapes, order

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('capture'); ap.add_argument('out')
    ap.add_argument('--scale', type=int, default=4); a = ap.parse_args(); S = a.scale
    os.makedirs(a.out, exist_ok=True)
    shapes, order = collect(a.capture)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 13)
    bold = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 26)
    small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 15)
    rows, manifest = [], []
    def vname(k): return (chr(97 + k) if k < 26 else chr(97 + k // 26 - 1) + chr(97 + k % 26))
    for prefix, cat, title in SECTIONS:
        items = []
        for n, tiles in enumerate([t for t in order if shapes[t]['cat'] == cat], 1):
            vs = sorted(shapes[tiles]['variants'].items(), key=lambda kv: -len(kv[1]))
            iid = f'{prefix}{n:03d}'
            for k, (cols, where) in enumerate(vs):
                manifest.append({'id': iid + (vname(k) if len(vs) > 1 else ''), 'item': iid, 'section': title,
                                 'used_in': sorted(where), 'nes_colors': cols.hex(), 'chr': tiles.hex()})
            items.append((iid, tiles, vs))
        if not items: continue
        nvar = sum(len(v) for _, _, v in items)
        C, cw, ch_ = 12, 16 * S + 40, 16 * S + 58
        H = 100 + ((len(items) + C - 1) // C) * ch_ + 16
        sheet = Image.new('RGB', (C * cw + 24, H), (30, 30, 34)); d = ImageDraw.Draw(sheet)
        d.text((12, 12), f'Dragon Warrior IV — {title}', font=bold, fill=(240, 240, 240))
        d.text((12, 50), f'{len(items)} tiles to draw ({nvar} palette versions shown small under each).'
               f'  Each tile is 16x16 in game, {16 * 10}x{16 * 10} at 10x.', font=small, fill=(190, 190, 200))
        d.text((12, 70), 'One drawing per tile can usually serve all of its palette versions; draw a separate version'
               ' only where the colours change what it is (e.g. grass vs snow).', font=small, fill=(150, 150, 160))
        for i, (iid, tiles, vs) in enumerate(items):
            x, y = 12 + (i % C) * cw, 100 + (i // C) * ch_
            sheet.paste(render(tiles, vs[0][0], S), (x, y))
            d.text((x + 16 * S + 4, y), iid, font=font, fill=(220, 220, 150))
            if len(vs) > 1:
                d.text((x + 16 * S + 4, y + 18), f'x{len(vs)}', font=font, fill=(150, 150, 160))
            for k, (cols, _) in enumerate(vs[1:13]):
                sheet.paste(render(tiles, cols, 1).resize((14, 14), Image.NEAREST),
                            (x + (k % 6) * 15, y + 16 * S + 4 + (k // 6) * 15))
        path = os.path.join(a.out, f'field_{cat}.png'); sheet.save(path, optimize=True)
        rows.append((title, len(items), nvar, path))
    with open(os.path.join(a.out, 'field_tiles.csv'), 'w', newline='') as f:
        wr = csv.writer(f); wr.writerow(['id', 'item', 'section', 'used_in', 'nes_colors'])
        for r in manifest: wr.writerow([r['id'], r['item'], r['section'], '; '.join(r['used_in']), r['nes_colors']])
    json.dump(manifest, open(os.path.join(a.out, 'field_tiles.json'), 'w'), indent=0)
    for t, n, v, p in rows: print(f'{t}: {n} tiles ({v} palette versions) -> {p}')

if __name__ == '__main__':
    main()
