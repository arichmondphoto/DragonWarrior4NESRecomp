"""Add the owner's HD walking characters (party, townspeople, animals,
vehicles, monsters on the map) to an HD pack directory (Mesen hires.txt).

Inputs
  CHARACTERS  tools/sprite_sheet.py characters.json (--types): every
              character's 8 frames as 4 sprites each (CHR + attribute)
  FITTED      tools/check_ai_sprites.py OUT/fitted_full: the art per
              character, 4x2 frames of 160x160 (10x), fitted to the 8-bit
              outlines, with the art's own alpha
  CAPTURE     tools/capture_field.py maps (for the sprite palettes in use)

Each sprite is 8x8, so each frame's art is cut into four 80x80 slices, stored
the way the tile is stored in CHR (un-flipped: the presenter mirrors the art
with the sprite), keyed by the tile's 16 CHR bytes + its 3 colours.

Variants: a character loaded another way (the party leader, the $80 flag)
can have a few tiles of its own (tools/sprite_sheet.py 'variants'); those get
the same frame's art.

Shared tiles: the same tile can appear in several frames or characters (a head
shared by both walking steps, the two halves of a symmetric front view, a
tile reused by another character). Each use gets an entry gated on what
tells it apart: the sprite's mirroring ([hmirror]/[vmirror]) and/or the
neighbouring sprites of its own frame (spriteNearby, 8 px away), using the
fewest that no other use shares; the first use (facing down, step 1, first
character) is the plain default. Blank tiles are only ever drawn gated.

Palettes: the game uses a handful of sprite palette sets (day, a few special
ones; night and the fade steps between screens subtract $10 from each colour,
up to three times). Every character gets entries for every set (a sprite's
colours are its palette slot in that set), so it keeps its art anywhere: the
art's own palette as drawn, other real palettes as per-channel affine
recolours, and night/fade steps of those as the same image at the matching
brightness.

People lying down (beds): the game turns a character's tiles by 90, 180 or
270 degrees (bank 8 $82D4) for the types a map loads with the $80 flag (taken
from the captures) and the party. Each turned tile gets the art turned the
same way (plain entries, below every real tile).

The pack must have `<options>spriteCells` (nesrecomp patch 0009) so the art
is drawn over the whole 8x8 sprite, not just its 8-bit pixels.

usage: make_sprite_hdpack.py CHARACTERS FITTED CAPTURE OUTDIR [--report FILE]
"""
import argparse, collections, glob, itertools, json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from field_sheet import NES
from sprite_sheet import tile_px
from capture_types import fold

S = 10                                     # 10x pack
SL = 8 * S                                 # slice size (80)
CELL, GUT = 160, 12                        # fitted_full layout
ORDER = [4, 5, 2, 3, 6, 7, 0, 1]            # frame preference for the default owner (down first)
POS = [(0, 0), (8, 0), (0, 8), (8, 8)]

def encode(px):
    lo = bytes(int(''.join(str(int(v) & 1) for v in row), 2) for row in px)
    hi = bytes(int(''.join(str((int(v) >> 1) & 1) for v in row), 2) for row in px)
    return lo + hi

def rgb(c): v = NES[c & 0x3F]; return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], float)
def fade(pal, k): return bytes(0x0F if (c & 0x3F) < 0x10 * k or (c & 0x0F) >= 0x0D else c - 0x10 * k for c in pal)
def black(pal): return all((c & 0x0F) >= 0x0D or (c & 0x3F) == 0x0F for c in pal)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('characters'); ap.add_argument('fitted'); ap.add_argument('capture'); ap.add_argument('outdir')
    ap.add_argument('--report'); a = ap.parse_args()
    rows = json.load(open(a.characters))

    # ---- palette sets (4 sprite sub-palettes of 3 colours) in the game -----
    real_sets = set(); lying = set(range(9))       # the party can sleep at inns
    for p in glob.glob(os.path.join(a.capture, '*.mem')):
        m = load(p); pal = m['palette']
        for i in range(16):                         # types a map loads lying down ($80 flag)
            raw = m['wram'][0xE5E + i]
            if raw == 0xFF: break
            if raw & 0x80: lying.add(fold(raw))
        if max(pal[:16]) == min(pal[:16]): continue
        real_sets.add(tuple(bytes(pal[0x11 + 4 * i:0x14 + 4 * i]) for i in range(4)))
    # sets that are a fade step of another are not separate looks (night = day - $10)
    def is_fade_of(s, t): return any(tuple(fade(x, k) for x in t) == s for k in (1, 2, 3))
    looks = [s for s in real_sets if not any(t != s and is_fade_of(s, t) for t in real_sets)]
    looks = [s for s in looks if not all(black(x) for x in s)]
    versions = []                              # (set of 4 subpals, look it is drawn from, fade k)
    seen = set()
    for L in sorted(looks):
        for k in (0, 1, 2, 3):
            v = tuple(fade(x, k) for x in L)
            if v in seen or all(black(x) for x in v): continue
            seen.add(v); versions.append((v, L, k))
    print(f'  sprite palettes: {len(looks)} looks, {len(versions)} versions with night/fade steps')

    hires = os.path.join(a.outdir, 'hires.txt')
    lines = open(hires).read().splitlines()
    img_index = sum(1 for l in lines if l.startswith('<img>'))
    os.makedirs(os.path.join(a.outdir, 'sprites'), exist_ok=True)
    img_path = {}
    def add_img(img, name):
        nonlocal img_index
        rel = f'sprites/{name}.png'; img.save(os.path.join(a.outdir, rel))
        lines.append(f'<img>{rel}'); img_path[img_index] = rel; img_index += 1; return img_index - 1

    # ---- per character: slices, images per look ---------------------------
    uses = []          # dict: chr, p (palette slot), hm, vm, sibs [(sx, sy, chr, p)], cid, frame, k, imgs {look: (idx, bright-ref)}, slot
    turned = {}        # turned chr -> (cid, p, imgs, slot, transform)
    missing, recolours = [], 0
    for r in rows:
        if r.get('art_from'): continue
        path = os.path.join(a.fitted, r['id'] + '.png')
        if not os.path.exists(path): missing.append(r['id']); continue
        sheet = Image.open(path).convert('RGBA')
        frames = [[(bytes.fromhex(c), at) for c, at in f] for f in r['frames']]
        ref_cols = [bytes.fromhex(c) for c in r['versions'][0]['colours']]
        ref = {}
        for fi, f in enumerate(frames):
            for kk, (c, at) in enumerate(f): ref.setdefault(at & 3, ref_cols[fi * 4 + kk])
        # pixel counts per palette slot and colour (for fits and brightness)
        cnt = collections.defaultdict(lambda: np.zeros(4))
        for f in frames:
            for c, at in f:
                px = tile_px(c); cnt[at & 3] += [(px == v).sum() for v in range(4)]
        sources = [(r['id'], frames, None)]
        for n, vf in enumerate(r.get('variants', []), 1):
            vframes = [[(bytes.fromhex(c), at) for c, at in f] for f in vf]
            only = {fi * 4 + kk for fi in range(8) for kk in range(4) if vframes[fi][kk] != frames[fi][kk]}
            if only: sources.append((f"{r['id']}_v{n}", vframes, only))
        for label, frames, only in sources:
            # slices in CHR orientation, 8 per row
            canvas = Image.new('RGBA', (8 * SL, 4 * SL), (0, 0, 0, 0))
            for fi, f in enumerate(frames):
                d, st = fi // 2, fi % 2
                for kk, (c, at) in enumerate(f):
                    x0, y0 = GUT + d * (CELL + GUT) + POS[kk][0] * S, GUT + st * (CELL + GUT) + POS[kk][1] * S
                    sl = sheet.crop((x0, y0, x0 + SL, y0 + SL))
                    if at & 0x40: sl = sl.transpose(Image.FLIP_LEFT_RIGHT)
                    if at & 0x80: sl = sl.transpose(Image.FLIP_TOP_BOTTOM)
                    slot = fi * 4 + kk
                    canvas.paste(sl, ((slot % 8) * SL, (slot // 8) * SL))
            # one image per look the character needs (affine recolour per palette slot)
            imgs = {}                                  # (slot p, look subpal) -> image index
            if only is None: main_imgs = imgs
            base = None
            cache = {}
            for (v, L, k) in versions:
                for p in ref:
                    T = L[p]
                    if (p, T) in imgs: continue
                    if base is None: base = add_img(canvas, label)
                    if T == ref[p]:
                        imgs[(p, T)] = (base, ''); continue
                    X = np.array([rgb(ref[p][i]) for i in range(3)]); Y = np.array([rgb(T[i]) for i in range(3)])
                    Wt = cnt[p][1:] + 0.5
                    fit = []
                    for ch in range(3):
                        x, y = X[:, ch], Y[:, ch]; mx, my = (Wt * x).sum() / Wt.sum(), (Wt * y).sum() / Wt.sum()
                        vx = (Wt * (x - mx) ** 2).sum()
                        g = (Wt * (x - mx) * (y - my)).sum() / vx if vx > 50 else ((Wt @ Y.mean(1)) / max(Wt @ X.mean(1), 1))
                        g = float(np.clip(g, 0, 3)); fit.append((round(g / 0.05) * 0.05, round((my - g * mx) / 4) * 4))
                    key = tuple(fit)
                    if key not in cache:
                        # recoloured by the player at load time (patch 0011), not stored
                        cache[key] = (base, ',rgb:' + '/'.join(f'{g:.2f}/{int(o)}' for g, o in fit))
                        recolours += 1
                    imgs[(p, T)] = cache[key]
            # uses
            for fi in ORDER:
                f = frames[fi]
                for kk, (c, at) in enumerate(f):
                    if only is not None and (fi * 4 + kk not in only or (at & 3) not in ref): continue
                    hm, vm = bool(at & 0x40), bool(at & 0x80)
                    sibs = []
                    for s2, (c2, at2) in enumerate(f):
                        if s2 == kk or not any(c2): continue
                        dx, dy = POS[s2][0] - POS[kk][0], POS[s2][1] - POS[kk][1]
                        sibs.append((-dx if hm else dx, -dy if vm else dy, c2, at2 & 3))
                    uses.append(dict(chr=c, p=at & 3, hm=hm, vm=vm, sibs=sibs, cid=label, frame=fi, k=kk,
                                     imgs=imgs, slot=fi * 4 + kk, cnt=cnt[at & 3], ref=ref))
        frames, imgs = sources[0][1], main_imgs
        # turned forms of each tile (beds)
        if set(r.get('types', [])) & lying:
            done = set()
            for fi, f in enumerate(frames):
                for kk, (c, at) in enumerate(f):
                    if c in done or not any(c): continue
                    done.add(c)
                    px = tile_px(c)
                    for t in (1, 2, 3):                 # the game turns tiles, never transposes them
                        q = np.rot90(px, t)
                        c2 = encode(q)
                        if c2 != c and c2 not in turned: turned[c2] = (r['id'], at & 3, imgs, fi * 4 + kk, t)
    print(f'  {len({u["cid"] for u in uses})} characters with art, {recolours} recoloured images'
          + (f', no art: {" ".join(missing)}' if missing else ''))

    # ---- entries -------------------------------------------------------------
    conds, names = [], {}
    def cond(dx, dy, chr_, pal):
        k = (dx, dy, chr_.hex().upper(), pal)
        if k not in names:
            names[k] = f's{len(names)}'
            conds.append(f'<condition>{names[k]},spriteNearby,{dx},{dy},{k[2]},{pal}')
        return names[k]
    def palkey(cols): return 'FF' + cols.hex().upper()
    def bright(u, v, L, k):
        if k == 0: return 1.0
        lum = lambda pal: sum(u['cnt'][i + 1] * rgb(pal[i]) @ (0.299, 0.587, 0.114) for i in range(3))
        l0 = lum(L[u['p']]); return 0.0 if l0 <= 0 else round(min(1.0, lum(v[u['p']]) / l0), 3)

    by_key = collections.defaultdict(list)       # (chr, p) -> uses (palette slot decides colours per version)
    for u in uses: by_key[(u['chr'], u['p'])].append(u)
    real_lines, fade_lines, turn_lines = [], [], []
    unresolved = gated_only = 0
    def preds(u):
        return [('hm', u['hm']), ('vm', u['vm'])] + [('sib',) + s for s in u['sibs']]
    def holds(o, pr):
        if pr[0] == 'hm': return o['hm'] == pr[1]
        if pr[0] == 'vm': return o['vm'] == pr[1]
        return any(s == pr[1:] for s in o['sibs'])
    for (c, p), own in by_key.items():
        blank = not any(c)
        # one use per distinct art (same character + same slice look-alike is still distinct art)
        own_d = list({(u['cid'], u['slot']): u for u in own}.values())
        choices = []
        for i, u in enumerate(own_d):
            if len(own_d) == 1: choices.append(()); break
            others = [o for j, o in enumerate(own_d) if j != i]
            mine = preds(u); choice = None
            for n in (1, 2, 3):
                for combo in itertools.combinations(mine, n):
                    if not any(all(holds(o, pr) for pr in combo) for o in others): choice = combo; break
                if choice: break
            if choice is None: unresolved += 1; choice = None
            choices.append(choice)
        for (v, L, k) in versions:
            cols = v[p]
            if black(cols): continue
            pal = palkey(cols)
            out = real_lines if k == 0 else fade_lines
            def entry(u):
                idx, xf = u['imgs'][(p, L[p])]; sl = u['slot']
                return f'<tile>{idx},{c.hex().upper()},{pal},{(sl % 8) * SL},{(sl // 8) * SL},{bright(u, v, L, k):g},N{xf}'
            if not blank: out.append(entry(own_d[0]))           # default: first use
            elif k == 0: gated_only += 1
            if len(own_d) == 1 and not blank: continue
            for u, ch in zip(own_d, choices):
                if ch is None or (not ch and blank): continue
                parts = []
                for pr in ch:
                    if pr[0] in ('hm', 'vm'): parts.append(('' if pr[1] else '!') + ('hmirror' if pr[0] == 'hm' else 'vmirror'))
                    else: parts.append(cond(pr[1], pr[2], pr[3], palkey(v[pr[4]])))
                if parts: out.append(f'[{"&".join(parts)}]{entry(u)}')
    # turned tiles (beds): the source slice turned the same way; plain entries,
    # written first so every real tile wins
    real_keys = {c for (c, p) in by_key}
    groups = collections.defaultdict(list)
    for c2, it in turned.items():
        if c2 not in real_keys: groups[it[0]].append((c2,) + it[1:])
    cnt_of = {(u['cid'], u['p']): u['cnt'] for u in uses}
    for cid, items in groups.items():
        # the source slice turned by the player at load time (rot:, patch 0011),
        # in every look and its night/fade steps
        for (c2, p, imgs, slot, t) in items:
            u = dict(p=p, cnt=cnt_of[(cid, p)])
            for (v, L, k) in versions:
                cols = v[p]
                if black(cols) or (p, L[p]) not in imgs: continue
                idx, xf = imgs[(p, L[p])]
                turn_lines.append(f'<tile>{idx},{c2.hex().upper()},{palkey(cols)},{(slot % 8) * SL},{(slot // 8) * SL},'
                                  f'{bright(u, v, L, k):g},N,rot:{t % 4}{xf}')

    head = [l for l in lines if l.startswith(('<ver>', '<scale>'))]
    imgl = [l for l in lines if l.startswith('<img>')]
    rest = [l for l in lines if not l.startswith(('<ver>', '<scale>', '<img>'))]
    opts = [] if any(l.startswith('<options>') and 'spriteCells' in l for l in rest) else ['<options>spriteCells']
    tiles = turn_lines + fade_lines + real_lines
    out = head + opts + imgl + rest + [f'# HD characters ({len({u["cid"] for u in uses})}): owner art per 8x8 sprite + exact colours'] + conds + tiles
    open(hires, 'w').write('\n'.join(out) + '\n')
    print(f'  {len(real_lines)} sprite entries + {len(fade_lines)} night/fade + {len(turn_lines)} turned (beds), '
          f'{len(conds)} neighbour conditions, {unresolved} unresolved, {gated_only} blank tiles gated only -> {hires}')
    if a.report:
        json.dump({'missing': missing, 'entries': len(tiles), 'conditions': len(conds), 'unresolved': unresolved,
                   'recolours': recolours, 'versions': len(versions)}, open(a.report, 'w'), indent=1)

if __name__ == '__main__':
    main()
