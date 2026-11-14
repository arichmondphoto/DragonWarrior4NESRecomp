"""Find map-tile seams: borders between two map tiles that are continuous in
the 8-bit picture but jump in the HD pack (different texture or colour for
the same ground, e.g. the Endor arena's sand next to its sand edge strips, or
the grass painted around a castle next to the overworld's grass).

For every captured map screen (tools/capture_field.py dumps: MM_SS.mem, night
*_n.mem, view/ and anim/), every background cell is drawn the way the
player draws it: the pack's <tile> entry for its 16 CHR bytes + palette
(conditions evaluated: tileNearby; a passing conditional entry beats the
unconditional one), with its rgb:/rgbl:/rgbd:/rgbdl:/rot: transform. Then at
each 16x16 map-tile border (metatiles sit at even cells):

  8-bit continuous: the 2-pixel strips on both sides hold about the same
                    colours (colour histogram distance < CONT);
  HD jump:          6-pixel strips on both sides, in 4 segments along the
                    border: mean colour distance + half the texture (std)
                    distance, averaged.

Borders whose HD jump passes JUMP are counted per pair of map tiles
(field_tiles_all.json items) and palette. Writes OUT/seams.json (pairs,
worst first, with where they were seen) and OUT/seams.png (the worst pairs:
8-bit | HD, both tiles side by side or stacked as on the map).

usage: seam_check.py PACKDIR FIELD_CAPTURE OUT [--only MM_SS ...] [--top N]
"""
import argparse, collections, glob, json, os, re, sys
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from field_sheet import NES

CONT = 0.35          # 8-bit strips: histogram distance under this = continuous
JUMP = 24.0          # HD: the jump across the border minus the texture's own change over the same distance
S = 10

def nes_rgb(c): v = NES[c & 0x3F]; return ((v >> 16) & 255, (v >> 8) & 255, v & 255)

def parse_pack(packdir):
    lines = open(os.path.join(packdir, 'hires.txt')).read().splitlines()
    imgs, conds, tiles = [], {}, collections.defaultdict(list)
    for l in lines:
        if l.startswith('<img>'): imgs.append(l[5:]); continue
        if l.startswith('<condition>'):
            q = l[11:].split(','); conds[q[0]] = (q[1], q[2:]); continue
        m = re.match(r'^(?:\[([^\]]*)\])?<tile>(\d+),([0-9A-Fa-f]{32}),([0-9A-Fa-f]{8}),(\d+),(\d+),([\d.]+),([NYny])(.*)$', l)
        if not m or m[4].upper().startswith('FF'): continue
        cs = [c for c in (m[1] or '').split('&') if c]
        xf = [t for t in m[9].split(',') if t]
        tiles[(m[3].upper(), m[4].upper())].append((cs, int(m[2]), int(m[5]), int(m[6]), float(m[7]), xf))
    return imgs, conds, tiles

class Pack:
    def __init__(self, packdir):
        self.dir = packdir
        self.imgs, self.conds, self.tiles = parse_pack(packdir)
        self.sheets, self.cache = {}, {}
    def sheet(self, i):
        if i not in self.sheets:
            self.sheets[i] = np.asarray(Image.open(os.path.join(self.dir, self.imgs[i])).convert('RGBA')).astype(np.float32)
        return self.sheets[i]
    def art(self, e):
        key = (e[1], e[2], e[3], tuple(e[5]), e[4])
        if key in self.cache: return self.cache[key]
        a = self.sheet(e[1])[e[3]:e[3] + 8 * S, e[2]:e[2] + 8 * S].copy()
        rgb, al = a[..., :3], a[..., 3:] / 255.0
        for t in e[5]:
            if t.startswith('rot:'): a = np.rot90(a, int(t[4:]) & 3); rgb, al = a[..., :3], a[..., 3:] / 255.0
            m = re.match(r'rgbd?(l?):(.*)', t)
            if m:
                v = [float(x) for x in m[2].split('/')]; g, o = np.array(v[0::2]), np.array(v[1::2])
                src = (rgb @ np.array([0.299, 0.587, 0.114], np.float32))[..., None] if m[1] else rgb
                rgb = np.clip(src * g + o, 0, 255)
        rgb = rgb * min(e[4], 1.0)
        out = (rgb, al[..., 0])
        self.cache[key] = out
        return out

def cell_key(ch, ci, pal, nt, r, c):
    t = ci[nt + r * 32 + c]
    data = bytes(ch[0x1000 + 16 * t:0x1010 + 16 * t]).hex().upper()
    a = ci[nt + 0x3C0 + (r // 4) * 8 + c // 4]
    sub = (a >> (((r % 4) // 2) * 4 + ((c % 4) // 2) * 2)) & 3
    p = bytes([pal[0], pal[sub * 4 + 1], pal[sub * 4 + 2], pal[sub * 4 + 3]]).hex().upper()
    return data, p, t, sub

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pack'); ap.add_argument('capture'); ap.add_argument('out')
    ap.add_argument('--only', nargs='*', default=[]); ap.add_argument('--top', type=int, default=40)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    P = Pack(a.pack)
    rows = json.load(open(os.path.join(a.capture, 'field_tiles_all.json')))
    item_of = {}
    for r in rows: item_of.setdefault(bytes.fromhex(r['chr']), r['item'])
    mems = sorted(glob.glob(os.path.join(a.capture, 'maps', '*.mem')) + glob.glob(os.path.join(a.capture, 'maps', 'view', '*.mem')))
    if a.only: mems = [m for m in mems if any(os.path.basename(m).startswith(o) for o in a.only)]
    pairs = {}
    nb = 0
    for path in mems:
        m = load(path); ch, ci, pal, ram = m['chr_ram'], m['ciram'], m['palette'], m['ram']
        if max(pal[:16]) == min(pal[:16]): continue
        name = os.path.basename(path)[:-4]
        for nt in (0, 0x400):
            keys = {(r, c): cell_key(ch, ci, pal, nt, r, c) for r in range(30) for c in range(32)}
            def pick(r, c):
                k = keys[(r, c)]; ents = P.tiles.get(k[:2])
                if not ents: return None
                best = None
                for e in ents:
                    if not e[0]: best = best or e; continue
                    ok = True
                    for cn in e[0]:
                        neg = cn.startswith('!'); d = P.conds.get(cn.lstrip('!'))
                        if not d or d[0] != 'tileNearby': ok = False; break
                        dx, dy, cchr, cpal = int(d[1][0]), int(d[1][1]), d[1][2].upper(), d[1][3].upper()
                        rr, cc = r + dy // 8, c + dx // 8
                        hit = (rr, cc) in keys and keys[(rr, cc)][0] == cchr and keys[(rr, cc)][1] == cpal
                        if hit == neg: ok = False; break
                    if ok: return e
                return best
            chosen = {rc: pick(*rc) for rc in keys}
            def native(r, c):
                k = keys[(r, c)]; t = 0x100 + ci[nt + r * 32 + c]
                d = ch[16 * t:16 * t + 16]
                idx = np.array([[((d[y] >> (7 - x)) & 1) | (((d[y + 8] >> (7 - x)) & 1) << 1) for x in range(8)] for y in range(8)])
                p = bytes.fromhex(k[1]); cols = np.array([nes_rgb(x) for x in p], np.float32)
                return cols[idx], idx
            # metatile of a cell: the 16x16 tile at even (r, c)
            def item(r, c):
                r0, c0 = r - r % 2, c - c % 2
                if r0 + 1 >= 30 or c0 + 1 >= 32: return None
                q = b''.join(bytes(ch[0x1000 + 16 * ci[nt + rr * 32 + cc]:0x1010 + 16 * ci[nt + rr * 32 + cc]])
                             for rr, cc in ((r0, c0), (r0, c0 + 1), (r0 + 1, c0), (r0 + 1, c0 + 1)))
                return item_of.get(q)
            for r in range(30):
                for c in range(32):
                    for dr, dc in ((0, 1), (1, 0)):
                        r2, c2 = r + dr, c + dc
                        if r2 >= 30 or c2 >= 32: continue
                        if dc and c2 % 2: continue                  # only borders between metatiles
                        if dr and r2 % 2: continue
                        e1, e2 = chosen[(r, c)], chosen[(r2, c2)]
                        if not e1 or not e2: continue
                        i1, i2 = item(r, c), item(r2, c2)
                        if not i1 or not i2 or i1 == i2 and dc == 0 and dr == 0: continue
                        (n1, x1), (n2, x2) = native(r, c), native(r2, c2)
                        if dc: s1, s2 = n1[:, 6:], n2[:, :2]
                        else:  s1, s2 = n1[6:, :], n2[:2, :]
                        def hist(s):
                            h = collections.Counter(map(tuple, s.reshape(-1, 3).astype(int))); n = sum(h.values())
                            return {k: v / n for k, v in h.items()}
                        h1, h2 = hist(s1), hist(s2)
                        hd = sum(abs(h1.get(k, 0) - h2.get(k, 0)) for k in set(h1) | set(h2)) / 2
                        if hd > CONT: continue
                        (a1, al1), (a2, al2) = P.art(e1), P.art(e2)
                        if min(al1.mean(), al2.mean()) < 0.9: continue    # transparent art: something shows through
                        W = 6
                        def strip(a_, side, off):
                            # W-pixel strip `off` strips in from the border side
                            if dc: return a_[:, 80 - (off + 1) * W:80 - off * W] if side == 0 else a_[:, off * W:(off + 1) * W]
                            return a_[80 - (off + 1) * W:80 - off * W, :] if side == 0 else a_[off * W:(off + 1) * W, :]
                        def dist(p1, p2):
                            d = 0.0
                            for k in range(4):
                                sl = slice(k * 20, k * 20 + 20)
                                q1 = (p1[sl] if dc else p1[:, sl]).reshape(-1, 3); q2 = (p2[sl] if dc else p2[:, sl]).reshape(-1, 3)
                                d += np.linalg.norm(q1.mean(0) - q2.mean(0)) + 0.5 * np.linalg.norm(q1.std(0) - q2.std(0))
                            return d / 4
                        across = dist(strip(a1, 0, 0), strip(a2, 1, 0))
                        # the texture's own change over the same distance inside each tile
                        inside = max(dist(strip(a1, 0, 1), strip(a1, 0, 0)), dist(strip(a2, 1, 0), strip(a2, 1, 1)))
                        score = across - inside
                        nb += 1
                        if score < JUMP: continue
                        k1, k2 = keys[(r, c)][1], keys[(r2, c2)][1]
                        pk = (i1, i2, 'h' if dc else 'v', k1, k2)
                        rec = pairs.setdefault(pk, {'a': i1, 'b': i2, 'dir': 'side' if dc else 'above', 'pal_a': k1, 'pal_b': k2,
                                                    'count': 0, 'score': 0.0, 'maps': [], 'where': None})
                        rec['count'] += 1; rec['score'] = max(rec['score'], round(float(score), 1))
                        if name not in rec['maps']: rec['maps'].append(name)
                        if not rec['where']: rec['where'] = [path, nt, r - r % 2 if dr == 0 else r - 1, (c - 1) if dc else c - c % 2]
    out = sorted(pairs.values(), key=lambda p: -p['score'] * min(p['count'], 20))
    json.dump({'borders_checked': nb, 'seams': out}, open(os.path.join(a.out, 'seams.json'), 'w'), indent=0)
    print(f'{nb} continuous 8-bit borders checked, {len(out)} tile pairs with a seam in HD, '
          f'{sum(p["count"] for p in out)} seam borders')
    # contact sheet of the worst pairs: 8-bit 2x2 metatiles | HD
    top = out[:a.top]
    if not top: return
    CW, CH = 2 * 160 + 10 + 2 * 160, 160 + 18
    cols = 3
    sheet = Image.new('RGB', (cols * (CW + 20), ((len(top) + cols - 1) // cols) * (CH + 10)), (40, 40, 44)); dr_ = ImageDraw.Draw(sheet)
    for i, p in enumerate(top):
        path, nt, r0, c0 = p['where']
        m = load(path); ch, ci, pal = m['chr_ram'], m['ciram'], m['palette']
        keys = {(r, c): cell_key(ch, ci, pal, nt, r, c) for r in range(30) for c in range(32)}
        side = p['dir'] == 'side'
        w8, h8 = (4, 2) if side else (2, 4)
        nat = Image.new('RGB', (w8 * 8, h8 * 8)); hd = Image.new('RGB', (w8 * 80, h8 * 80))
        for rr in range(h8):
            for cc in range(w8):
                r, c = r0 + rr, c0 + cc
                if (r, c) not in keys: continue
                k = keys[(r, c)]; t = 0x100 + ci[nt + r * 32 + c]; d = ch[16 * t:16 * t + 16]
                idx = np.array([[((d[y] >> (7 - x)) & 1) | (((d[y + 8] >> (7 - x)) & 1) << 1) for x in range(8)] for y in range(8)])
                cols_ = np.array([nes_rgb(x) for x in bytes.fromhex(k[1])], np.uint8)
                nat.paste(Image.fromarray(cols_[idx]), (cc * 8, rr * 8))
                ents = P.tiles.get(k[:2])
                if ents:
                    e = next((e for e in ents if not e[0]), ents[0])
                    rgb, al = P.art(e)
                    hd.paste(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)), (cc * 80, rr * 80))
        f = 160 / max(nat.width, nat.height)
        sz = (round(nat.width * f), round(nat.height * f))
        x, y = (i % cols) * (CW + 20), (i // cols) * (CH + 10)
        dr_.text((x, y), f"{p['a']}|{p['b']} {p['dir']} x{p['count']} s{p['score']} {p['maps'][0]}", fill=(255, 255, 255))
        sheet.paste(nat.resize(sz, Image.NEAREST), (x, y + 16)); sheet.paste(hd.resize(sz, Image.LANCZOS), (x + 170, y + 16))
    sheet.save(os.path.join(a.out, 'seams.png'))

if __name__ == '__main__':
    main()
