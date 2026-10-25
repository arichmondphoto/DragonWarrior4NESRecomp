"""Inventory of the walking character sprites (party, townspeople, soldiers,
animals, ships...) from tools/capture_field.py captures.

How the game keeps them (found by tracing; bank 31 $D7F1-$D876):
  * every map loads each character type it needs into a slot (up to 16);
  * WRAM $7200 + slot*64 is that type's frame table: 4 directions (up,
    right, down, left) x 2 walking steps x 4 sprites (TL, TR, BL, BR), each
    sprite = tile number (pattern table $0000) + attribute byte (palette in
    bits 0-1, horizontal flip $40, vertical flip $80);
  * the objects on the map (30 of them) say which slot they use at
    $6FE0+i (low nibble); $7020+i is $FF for an empty object and has bit 1
    set for hidden party members (whose slots hold placeholder graphics).

A character is identified by the CHR bytes + flips of its 32 sprites; its
palette versions (every map's sprite palette it was seen with) are kept.

Writes OUT/characters.json (id, frames as CHR/attr, palette versions, maps)
and, unless --json-only, OUT/characters.png (numbered sheet, 3x).

usage: sprite_sheet.py CAPTURE OUT [--json-only]
"""
import argparse, glob, json, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from field_sheet import NES, MAPS, BLACK

DIRS = ['up', 'right', 'down', 'left']

def slot_frames(w, s):
    b = bytes(w[0x1200 + 64 * s: 0x1240 + 64 * s])
    return [[(b[f * 8 + 2 * k], b[f * 8 + 2 * k + 1]) for k in range(4)] for f in range(8)]

def tile_px(chr_bytes):
    d = chr_bytes
    return np.array([[((d[y] >> (7 - x)) & 1) | (((d[y + 8] >> (7 - x)) & 1) << 1) for x in range(8)] for y in range(8)])

def frame_image(frame, colours, scale=1):
    """frame: [(chr16, attr) x4]; colours: [3 NES colours] per sprite."""
    img = np.zeros((16, 16, 4), np.uint8)
    for k, ((chr16, a), cols) in enumerate(zip(frame, colours)):
        px = tile_px(chr16)
        if a & 0x40: px = px[:, ::-1]
        if a & 0x80: px = px[::-1]
        for y in range(8):
            for x in range(8):
                v = px[y, x]
                if v:
                    c = NES[cols[v - 1] & 0x3F]
                    img[(k // 2) * 8 + y, (k % 2) * 8 + x] = [(c >> 16) & 255, (c >> 8) & 255, c & 255, 255]
    im = Image.fromarray(img, 'RGBA')
    return im.resize((16 * scale, 16 * scale), Image.NEAREST) if scale != 1 else im

def collect(cap):
    chars, order = {}, []
    # tiles of the placeholder graphic held by hidden party slots (an '8')
    placeholder = set()
    for path in sorted(glob.glob(os.path.join(cap, '*.mem'))):
        m = load(path); w, ch = m['wram'], m['chr_ram']
        visible = {w[0xFE0 + i] & 0x0F for i in range(30) if w[0x1020 + i] != 0xFF and not w[0x1020 + i] & 0x02}
        for i in range(30):
            if w[0x1020 + i] != 0xFF and w[0x1020 + i] & 0x02 and (w[0xFE0 + i] & 0x0F) not in visible:
                for f in slot_frames(w, w[0xFE0 + i] & 0x0F):
                    for t, a in f:
                        c = bytes(ch[16 * t:16 * t + 16])
                        if any(c): placeholder.add(c)
    for path in sorted(glob.glob(os.path.join(cap, '*.mem'))):
        m = load(path); w, ch, pal, ram = m['wram'], m['chr_ram'], m['palette'], m['ram']
        if max(pal[:16]) == min(pal[:16]): continue
        used = {}
        for i in range(30):
            if w[0x1020 + i] == 0xFF: continue
            hidden = bool(w[0x1020 + i] & 0x02)
            used[w[0xFE0 + i] & 0x0F] = used.get(w[0xFE0 + i] & 0x0F, True) and hidden
        where = ('Overworld' if ram[0x28] == 0 else MAPS[ram[0x63]]) + (' (night)' if path.endswith('_n.mem') else '')
        for s, only_hidden in used.items():
            if only_hidden: continue                          # empty party slots: placeholder graphics
            fr = slot_frames(w, s)
            pieces = [[(bytes(ch[16 * t:16 * t + 16]), a) for t, a in f] for f in fr]
            if not any(any(c) for f in pieces for c, a in f): continue
            if sum(c in placeholder for f in pieces for c, a in f) >= 8: continue   # placeholder '8'
            shape = b''.join(c + bytes([a & 0xC0]) for f in pieces for c, a in f)
            cols = tuple(bytes(pal[0x11 + 4 * (a & 3): 0x14 + 4 * (a & 3)]) for f in fr for t, a in f)
            if all(c & 0x3F in BLACK for cc in cols for c in cc): continue   # unlit / faded
            # leftover tables over reused tiles draw as near-black silhouettes
            npx = nblack = 0
            for (chr16, att), cc in zip([p for f in pieces for p in f], cols):
                px = tile_px(chr16)
                for v in (1, 2, 3):
                    k = int((px == v).sum()); npx += k
                    if cc[v - 1] & 0x3F in BLACK: nblack += k
            if npx and nblack / npx > 0.8: continue
            if shape not in chars:
                chars[shape] = {'pieces': pieces, 'versions': {}, 'maps': set()}; order.append(shape)
            chars[shape]['versions'].setdefault(cols, set()).add(where)
            chars[shape]['maps'].add(where)
    return chars, order

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('capture'); ap.add_argument('out')
    ap.add_argument('--json-only', action='store_true'); a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    chars, order = collect(a.capture)
    rows = []
    for n, shape in enumerate(order, 1):
        c = chars[shape]
        vs = sorted(c['versions'].items(), key=lambda kv: -len(kv[1]))
        rows.append({'id': f'C{n:03d}', 'maps': sorted(c['maps']),
                     'frames': [[[chr16.hex(), att] for chr16, att in f] for f in c['pieces']],
                     'versions': [{'colours': [cc.hex() for cc in cols], 'used_in': sorted(wh)} for cols, wh in vs]})
    json.dump(rows, open(os.path.join(a.out, 'characters.json'), 'w'), indent=0)
    print(f'{len(rows)} characters -> {a.out}/characters.json')
    if a.json_only: return
    S, C = 3, 2
    cw = 8 * (16 * S + 6) + 70
    sheet = Image.new('RGBA', (C * cw + 20, 70 + ((len(rows) + C - 1) // C) * (16 * S + 10)), (30, 30, 34, 255))
    d = ImageDraw.Draw(sheet)
    try: font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14); big = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 24)
    except OSError: font = big = ImageFont.load_default()
    d.text((12, 10), f'Dragon Warrior IV — walking characters ({len(rows)})', font=big, fill=(240, 240, 240))
    d.text((12, 42), 'Each row: up, up, right, right, down, down, left, left (two walking steps per direction).', font=font, fill=(180, 180, 190))
    for i, r in enumerate(rows):
        x0, y0 = 12 + (i % C) * cw, 70 + (i // C) * (16 * S + 10)
        d.text((x0, y0 + 14), r['id'], font=font, fill=(220, 220, 150))
        cols = [bytes.fromhex(c) for c in r['versions'][0]['colours']]
        for f, fr in enumerate(r['frames']):
            img = frame_image([(bytes.fromhex(c), att) for c, att in fr], cols[f * 4:f * 4 + 4], S)
            sheet.alpha_composite(img, (x0 + 60 + f * (16 * S + 6), y0))
    sheet.save(os.path.join(a.out, 'characters.png'))

if __name__ == '__main__':
    main()
