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
import argparse, glob, hashlib, json, os, sys
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
            chars[shape].setdefault('pals', {}).setdefault(bytes(pal[0x10:0x20]), set()).add(where)
    return chars, order

def collect_types(tdir):
    """tools/capture_types.py runs -> [(type, pieces, sprite palette 16 bytes)] in type order."""
    out = []
    for r in json.load(open(os.path.join(tdir, 'types.json'))):
        m = load(os.path.join(tdir, r['mem'])); w, ch, pal = m['wram'], m['chr_ram'], m['palette']
        for s, t in r['slots'].items():
            pieces = [[(bytes(ch[16 * x:16 * x + 16]), a) for x, a in f] for f in slot_frames(w, int(s))]
            if any(any(c) for f in pieces for c, a in f): out.append((t, pieces, bytes(pal[0x10:0x20])))
    return sorted(out, key=lambda x: x[0])

def piece_cols(pieces, pal16):
    return tuple(bytes(pal16[4 * (a & 3) + 1:4 * (a & 3) + 4]) for f in pieces for c, a in f)

def merge(chars, order, types):
    """Every character type first (type order; identical types share an
    entry), then any captured character that isn't one of them. A captured
    character whose tiles are among a type's tiles (a still or
    single-direction variant, at least half its tiles) is folded into that
    type."""
    ents = []
    by_shape = {}
    for t, pieces, pal16 in types:
        shape = b''.join(c + bytes([a & 0xC0]) for f in pieces for c, a in f)
        if shape in by_shape: by_shape[shape]['types'].append(t); continue
        e = {'pieces': pieces, 'types': [t], 'versions': {}, 'maps': set(), 'fallback': pal16,
             'tiles': {c for f in pieces for c, a in f if any(c)}}
        by_shape[shape] = e; ents.append(e)
    turned = {}
    for e in ents:
        for x in e['tiles']:
            px = tile_px(x).astype(np.uint8)
            for k in range(4):
                for q in (np.rot90(px, k), np.rot90(px, k)[:, ::-1]): turned.setdefault(q.tobytes(), set()).add(id(e))
    for shape in order:
        c = chars[shape]; tiles = {x for f in c['pieces'] for x, a in f if any(x)}
        home = by_shape.get(shape); lying = False
        if home is None and tiles:
            # A type loaded with the $80 flag (bank 8 $82BE) only gets some
            # frames; the rest show whatever tiles were left in its CHR, so
            # match on most of the tiles rather than all of them.
            best = max((e for e in ents if e.get('tiles')), key=lambda e: len(tiles & e['tiles']))
            if len(tiles & best['tiles']) >= 0.5 * len(tiles): home = best
        if home is None and tiles:
            # Lying-down people (beds, at night): the loader's $80 mode builds
            # them by turning the type's own tiles 90 degrees (bank 8 $82D4).
            # No art of their own: the HD pack turns the type's art.
            votes = {}
            for x in tiles:
                for k in turned.get(tile_px(x).astype(np.uint8).tobytes(), ()): votes[k] = votes.get(k, 0) + 1
            if votes:
                k = max(votes, key=votes.get)
                if votes[k] >= 0.75 * len(tiles):
                    home = next(e for e in ents if id(e) == k); home['turned'] = home.get('turned', 0) + 1; lying = True
        if home is None:
            ents.append({'pieces': c['pieces'], 'types': [], 'versions': dict(c['versions']), 'maps': set(c['maps'])})
            continue
        home['maps'] |= c['maps']
        if not lying and shape not in by_shape:
            # the same character loaded another way (e.g. as the party leader,
            # or with the $80 flag) with some tiles of its own: same art
            v = [list(f) for f in c['pieces']]
            if v not in home.setdefault('variants', []): home['variants'].append(v)
        for pal16, wh in c['pals'].items():
            home['versions'].setdefault(piece_cols(home['pieces'], pal16), set()).update(wh)
    for e in ents:
        if not e['versions']: e['versions'][piece_cols(e['pieces'], e['fallback'])] = set()
    return ents

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('capture'); ap.add_argument('out')
    ap.add_argument('--types', help='tools/capture_types.py output: include every character type')
    ap.add_argument('--json-only', action='store_true'); a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    chars, order = collect(a.capture)
    if a.types:
        ents = merge(chars, order, collect_types(a.types))
    else:
        ents = [{'pieces': chars[s]['pieces'], 'types': [], 'versions': chars[s]['versions'], 'maps': chars[s]['maps']} for s in order]
    # A type drawn only with tiles of another (single-pose copies of the
    # heroes, pieces of a bigger object) needs no art of its own.
    tl = [{x for f in c['pieces'] for x, a in f if any(x)} for c in ents]
    for i, c in enumerate(ents):
        for j in range(len(ents)):
            if j != i and c['types'] and tl[i] and tl[i] <= tl[j] and (len(tl[i]) < len(tl[j]) or j < i):
                c['art_from'] = f'C{j + 1:03d}'; break
    rows = []
    for n, c in enumerate(ents, 1):
        vs = sorted(c['versions'].items(), key=lambda kv: -len(kv[1]))
        rows.append({'id': f'C{n:03d}', 'types': c['types'], 'lying_down_variants': c.get('turned', 0), 'art_from': c.get('art_from'), 'maps': sorted(c['maps']),
                     'variants': [[[[x.hex(), at] for x, at in f] for f in v] for v in c.get('variants', [])],
                     'frames': [[[chr16.hex(), att] for chr16, att in f] for f in c['pieces']],
                     'versions': [{'colours': [cc.hex() for cc in cols], 'used_in': sorted(wh)} for cols, wh in vs]})
    # Keep the IDs the owner's art is named by (hd/sprites/ids.json: ID ->
    # fingerprint of the frames); characters new to this build get new IDs.
    idp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hd', 'sprites', 'ids.json')
    fp = lambda r: hashlib.sha1(json.dumps(r['frames']).encode()).hexdigest()[:16]
    if os.path.exists(idp):
        known = {v: k for k, v in json.load(open(idp)).items()}
        nxt = max(int(k[1:]) for k in known.values()) + 1; ren = {}
        for r in rows:
            new = known.get(fp(r))
            if new is None: new = f'C{nxt:03d}'; nxt += 1
            ren[r['id']] = new
        for r in rows:
            r['id'] = ren[r['id']]
            if r.get('art_from'): r['art_from'] = ren[r['art_from']]
        rows.sort(key=lambda r: r['id'])
    elif a.types:
        json.dump({r['id']: fp(r) for r in rows}, open(os.path.join(a.out, 'ids.json'), 'w'), indent=0)
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
