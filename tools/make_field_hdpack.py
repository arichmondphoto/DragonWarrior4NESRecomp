"""Add the owner's HD map tiles (towns, castles, dungeons, overworld) to an HD
pack directory (Mesen hires.txt format).

Inputs
  FIELD_TILES  tools/field_sheet.py field_tiles.json: every map tile (16x16
               metatile) and each palette it is drawn with in the game
  ART          one 160x160 PNG per tile ID (tools/slice_field_atlases.py);
               an optional <ID><letter>.png overrides one palette version

The game draws a map tile as four 8x8 background tiles, so each piece of art
is cut into four 80x80 quarters, keyed by the quarter's 16 CHR bytes + the
exact 4-colour palette, once per palette version.

Shared quarters: the same 8x8 tile + palette can belong to several map tiles
(grass corners, wall edges). Each of those gets an entry gated on its
neighbouring quarter(s) inside its own map tile (tileNearby, 8 px away), using
the fewest neighbours that no other owner of that quarter shares; the most
used owner is also the plain default. Quarters that are pure backdrop
(all colour 0) are only ever drawn gated, so blank window or battle
backgrounds are never touched.

Palettes: the art is made for one palette per tile (hd/field/ids.json). Every
other palette the game draws the tile with (other towns and dungeons, and
night, captured by tools/capture_field.py --night) gets a recoloured copy:
a per-channel affine map fitted from the art's palette colours to that
palette's colours, weighted by how much of each colour the tile uses.

Fades: between screens the game steps every colour down by $10 three times
(e.g. $2A -> $1A -> $0A -> black). Every day and night version also gets
entries for those three faded palettes, using the same art at the matching
brightness (the pack's per-tile brightness), so the HD art fades with the
screen instead of flashing back to 8-bit. Real palettes win over a fade
step that happens to look the same.

Seamless ground: art for tiles that repeat seamlessly in the original
(grass, water, floors...) gets a low-frequency colour correction so its
opposite edges meet without a visible seam.

usage: make_field_hdpack.py FIELD_TILES ART OUTDIR [--report FILE]
"""
import argparse, collections, hashlib, itertools, json, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage
sys.path.insert(0, os.path.dirname(__file__))
from field_sheet import pixels, NES

QOFF = [(0, 0), (8, 0), (0, 8), (8, 8)]            # quarter positions in a map tile (px)

def tileable(px):
    """(horizontal, vertical): the original repeats seamlessly along that axis."""
    g = np.array(px)
    def axis(a):
        inner = (a[:, 1:] != a[:, :-1]).mean()
        seam = (a[:, 0] != a[:, -1]).mean()
        return seam <= inner * 1.5 + 0.05
    return axis(g), axis(g.T)

def make_seamless(img, h, v):
    """Make a repeating ground tile meet itself across its edges (h: left/right,
    v: top/bottom): (1) a gentle ramp so the edge bands' average colours match,
    then (2) a wrap-around blur that fades in only within a few pixels of the
    seam, so texture flows across it instead of stopping at a line."""
    a = np.asarray(img.convert('RGB')).astype(float)
    W = a.shape[1]; ramp = np.arange(W) / (W - 1) - 0.5
    if h:
        d = ndimage.gaussian_filter1d(a[:, :8].mean(1) - a[:, -8:].mean(1), 10, axis=0, mode='wrap')
        a += d[:, None, :] * ramp[None, :, None]
    if v:
        d = ndimage.gaussian_filter1d(a[:8].mean(0) - a[-8:].mean(0), 10, axis=0, mode='wrap')
        a += d[None, :, :] * ramp[:, None, None]
    dist = np.minimum(np.arange(W), W - 1 - np.arange(W)) + 0.5
    wgt = np.exp(-(dist / 5.0) ** 2)
    if h:
        a = a * (1 - wgt[None, :, None]) + ndimage.gaussian_filter1d(a, 3, axis=1, mode='wrap') * wgt[None, :, None]
    if v:
        a = a * (1 - wgt[:, None, None]) + ndimage.gaussian_filter1d(a, 3, axis=0, mode='wrap') * wgt[:, None, None]
    return Image.fromarray(np.clip(np.round(a), 0, 255).astype(np.uint8))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('field_tiles'); ap.add_argument('art'); ap.add_argument('outdir')
    ap.add_argument('--report')
    a = ap.parse_args()
    rows = json.load(open(a.field_tiles))
    items = collections.OrderedDict()
    for r in rows: items.setdefault(r['item'], []).append(r)
    # Art is named by the ID it had when exported; hd/field/ids.json holds each
    # ID's tile fingerprint, so match art to this build's tiles by fingerprint.
    idmap = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hd', 'field', 'ids.json')
    art_for, ref_pal = {}, {}
    if os.path.exists(idmap):
        by_fp = {v[0]: (aid, v[1]) for aid, v in json.load(open(idmap))['ids'].items()}
        for iid, vs in items.items():
            fp = hashlib.sha1(bytes.fromhex(vs[0]['chr'])).hexdigest()[:16]
            if fp in by_fp: art_for[iid], ref_pal[iid] = by_fp[fp]

    hires = os.path.join(a.outdir, 'hires.txt')
    lines = open(hires).read().splitlines() if os.path.exists(hires) else ['<ver>106', '<scale>10']
    img_index = sum(1 for l in lines if l.startswith('<img>'))
    os.makedirs(os.path.join(a.outdir, 'field'), exist_ok=True)

    # ---- versions: (item, palette, image, brightness) ---------------------
    def rgb(c): v = NES[c & 0x3F]; return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], float)
    def counts(t):
        px = np.array(pixels(t)); return np.array([(px == k).sum() for k in range(4)], float)
    def lum(pal, cnt): return sum(cnt[k] * rgb(pal[k]) @ (0.299, 0.587, 0.114) for k in range(4))
    def fade(pal, k): return bytes(0x0F if (c & 0x3F) < 0x10 * k or (c & 0x0F) >= 0x0D else c - 0x10 * k for c in pal)
    night = lambda r: all(u.endswith('(night)') for u in r['used_in'])
    versions = []        # dicts: id, item, chr, pal, img, bright, uses, real
    missing, seamless, nights = [], 0, 0
    for iid, vs in items.items():
        # with ids.json the fingerprint is the only match: a tile that is new
        # in this build must never pick up art that belongs to another tile
        aid = art_for.get(iid) if os.path.exists(idmap) else iid
        base = os.path.join(a.art, (aid or '-') + '.png')
        if not aid or not os.path.exists(base): missing.append(iid); continue
        t = bytes.fromhex(vs[0]['chr']); cnt = counts(t)
        h, v = tileable(pixels(t))
        def load(path):
            im = Image.open(path).convert('RGB')
            if im.size != (160, 160): im = im.resize((160, 160), Image.LANCZOS)
            return make_seamless(im, h, v) if (h or v) else im
        if h or v: seamless += 1
        def add_img(img, name):
            nonlocal img_index
            rel = f'field/{name}.png'; img.save(os.path.join(a.outdir, rel))
            lines.append(f'<img>{rel}'); img_index += 1; return img_index - 1
        base_img = load(base); main_idx = None; tinted = {}
        ref = bytes.fromhex(ref_pal.get(iid) or vs[0]['nes_colors'])   # palette the art was made for
        X = np.array([rgb(ref[k]) for k in range(4)]); W = cnt + 0.5
        for r in vs:
            pal = bytes.fromhex(r['nes_colors'])
            over = os.path.join(a.art, aid + r['id'][len(iid):] + '.png') if r['id'] != iid else None
            Y = np.array([rgb(pal[k]) for k in range(4)])
            # per-channel affine fit (weighted by how much of each colour the tile
            # uses) from the art's palette to this one: how the game recolours it
            fit = []
            for ch in range(3):
                x, y = X[:, ch], Y[:, ch]; mx, my = (W * x).sum() / W.sum(), (W * y).sum() / W.sum()
                vx = (W * (x - mx) ** 2).sum()
                g = (W * (x - mx) * (y - my)).sum() / vx if vx > 50 else ((W @ Y.mean(1)) / max(W @ X.mean(1), 1))
                g = float(np.clip(g, 0, 3)); fit.append((g, my - g * mx))
            if over and os.path.exists(over):
                idx = add_img(load(over), aid + r['id'][len(iid):])
            elif any(abs(g - 1) > 0.06 or abs(o) > 8 for g, o in fit):
                gkey = tuple((round(g / 0.05) * 0.05, round(o / 4) * 4) for g, o in fit)
                if gkey not in tinted:
                    arr = np.asarray(base_img).astype(float)
                    arr = np.dstack([arr[..., ch] * gkey[ch][0] + gkey[ch][1] for ch in range(3)])
                    tinted[gkey] = add_img(Image.fromarray(np.clip(np.round(arr), 0, 255).astype(np.uint8)),
                                           f'{aid}_p{len(tinted) + 1}')
                    nights += 1
                idx = tinted[gkey]
            else:
                if main_idx is None: main_idx = add_img(base_img, aid)
                idx = main_idx
            uses = len(r['used_in'])
            versions.append(dict(id=r['id'], item=iid, chr=t, pal=pal, img=idx, bright=1.0, uses=uses, real=True))
            L0 = lum(pal, cnt)
            for k in (1, 2, 3):
                fp = fade(pal, k)
                if all((c & 0x0F) >= 0x0D or c == 0x0F for c in fp[1:]) and fp[0] == 0x0F and k == 3:
                    continue                                   # black: nothing to draw
                br = 0.0 if L0 <= 0 else min(1.0, lum(fp, cnt) / L0)
                versions.append(dict(id=f'{r["id"]}~{k}', item=iid, chr=t, pal=fp, img=idx, bright=round(br, 3),
                                     uses=uses / (10 * k), real=False))

    # a fade step that equals a real palette of the same tile is that palette
    real_keys = {(v['chr'], v['pal']) for v in versions if v['real']}
    seen = set(); kept = []
    for v in versions:
        k = (v['chr'], v['pal'])
        if (not v['real'] and k in real_keys) or (k, v['real']) in seen and not v['real']: continue
        seen.add((k, v['real'])); kept.append(v)
    versions = kept

    # ---- quarter keys -> owners -----------------------------------------
    owners = collections.defaultdict(list)           # (chr, pal) -> [(version, q)]
    for v in versions:
        for q in range(4):
            owners[(v['chr'][16 * q:16 * q + 16].hex().upper(), v['pal'].hex().upper())].append((v, q))

    conds, names = [], {}
    fade_tiles, real_tiles = [], []
    def cond(dx, dy, chr_hex, pal):
        k = (dx, dy, chr_hex, pal)
        if k not in names:
            names[k] = f'f{len(names)}'
            conds.append(f'<condition>{names[k]},tileNearby,{dx},{dy},{chr_hex},{pal}')
        return names[k]
    def sibs(v, q):
        t, pal = v['chr'], v['pal'].hex().upper()
        return {s: (QOFF[s][0] - QOFF[q][0], QOFF[s][1] - QOFF[q][1], t[16 * s:16 * s + 16].hex().upper(), pal)
                for s in range(4) if s != q}
    gated_only = unresolved = 0
    for (chr_hex, pal), own in owners.items():
        distinct = {}
        for v, q in own: distinct.setdefault((v['img'], q, v['bright']), (v, q))
        own = sorted(distinct.values(), key=lambda vq: (-vq[0]['real'], -vq[0]['uses']))
        blank = not any(bytes.fromhex(chr_hex))
        out_list = real_tiles if own[0][0]['real'] else fade_tiles
        entry = lambda v, q: (f'<tile>{v["img"]},{chr_hex},{pal},{QOFF[q][0] * 10},{QOFF[q][1] * 10},'
                              f'{v["bright"]:g},N')
        if len(own) == 1 and not blank:
            out_list.append(entry(*own[0])); continue
        if not blank: out_list.append(entry(*own[0]))     # most used owner = plain default
        else: gated_only += 1
        for v, q in own:
            mine = sibs(v, q)
            others = [sibs(v2, q2) for v2, q2 in own if (v2, q2) != (v, q)]
            choice = None
            def matches(o, combo):
                return all(any(o_s == mine[s] for o_s in o.values()) for s in combo)
            for n in (1, 2, 3):
                for combo in itertools.combinations(sorted(mine), n):
                    if not any(matches(o, combo) for o in others): choice = combo; break
                if choice: break
            if not choice: unresolved += 1; choice = tuple(sorted(mine))
            out_list.append(f'[{"&".join(cond(*mine[s]) for s in choice)}]{entry(v, q)}')
    # later lines win in the presenter: fade-step entries first, real palettes last
    tiles = fade_tiles + real_tiles

    head = [l for l in lines if l.startswith(('<ver>', '<scale>'))]
    imgl = [l for l in lines if l.startswith('<img>')]
    rest = [l for l in lines if not l.startswith(('<ver>', '<scale>', '<img>'))]
    out = head + imgl + rest + [f'# HD map tiles ({len(items) - len(missing)} tiles): owner art keyed per 8x8 quarter + exact palette'] + conds + tiles
    open(hires, 'w').write('\n'.join(out) + '\n')
    print(f'{len(items) - len(missing)} map tiles ({seamless} made seamless, {nights} palette recolours), '
          f'{sum(v["real"] for v in versions)} palette versions + {sum(not v["real"] for v in versions)} fade steps, '
          f'{len(tiles)} tile entries, '
          f'{len(conds)} neighbour conditions, {unresolved} unresolved -> {hires}')
    if missing: print(f'  no art yet for {len(missing)}: {" ".join(missing[:20])}{" ..." if len(missing) > 20 else ""}')
    if a.report:
        json.dump({'missing': missing, 'seamless': seamless, 'palette_recolours': nights, 'entries': len(tiles), 'conditions': len(conds),
                   'unresolved': unresolved, 'gated_only_blank': gated_only}, open(a.report, 'w'), indent=1)

if __name__ == '__main__':
    main()
