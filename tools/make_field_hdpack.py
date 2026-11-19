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
entries for those three faded palettes: the art recoloured (rgbd:, while
drawing, nesrecomp patch 0022) to each
step's own NES colours, so the HD art fades with the screen the way the game
does (deep blues and greens, darker colours going black first) instead of
flashing back to 8-bit or dimming evenly. Real palettes win over a fade
step that happens to look the same.

Screen edges: the pack carries `<options>edgePaletteFallback` (nesrecomp patch
0018). While the map scrolls the game draws each new row of tiles at the
top/bottom edge one step before their colours, so those tiles match no entry;
the player then looks them up with the screen's other palettes and draws
their HD art instead of the 8-bit strip.

Seamless ground: art for tiles that repeat seamlessly in the original
(grass, water, floors...) gets a low-frequency colour correction so its
opposite edges meet without a visible seam.

usage: make_field_hdpack.py FIELD_TILES ART OUTDIR [--report FILE]
"""
import argparse, colorsys, collections, glob, hashlib, itertools, json, os, re, sys
import numpy as np
from PIL import Image
from scipy import ndimage
sys.path.insert(0, os.path.dirname(__file__))
from field_sheet import pixels, NES, overworld_on_screen

QOFF = [(0, 0), (8, 0), (0, 8), (8, 8)]            # quarter positions in a map tile (px)

def tileable(px):
    """(horizontal, vertical): the original repeats seamlessly along that axis."""
    g = np.array(px)
    def axis(a):
        inner = (a[:, 1:] != a[:, :-1]).mean()
        seam = (a[:, 0] != a[:, -1]).mean()
        return seam <= inner * 1.5 + 0.05
    return axis(g), axis(g.T)

FLASH = bytes([0x0F, 0x16, 0x16, 0x16])         # the damage-floor flash, every sub-palette
HUE_LUM = 45          # degrees: past this hue change, colour by brightness if it fits much better
LUM_RATIO = 0.64      # ... its error below this share of the per-channel map's (checked by eye: above it,
                      # tiles that mix two hues, such as gold trim or orange grass with blue dots, lose a hue)
LUM_LOG = open(os.environ['DW4_LUM_LOG'], 'w') if os.environ.get('DW4_LUM_LOG') else None
FLASH_XF = ',rgb:1.30/8/0.30/0/0.25/0'        # art tinted red: grey stone -> about $16
SEAM_MAX = 30   # mean edge-band colour difference (0-255) above which an axis is left alone

def half_periodic(px):
    """(h, v): the 8-bit tile repeats every half tile along that axis (grass
    dots, brick floors), so a copy shifted by half a tile lines up with it."""
    g = np.array(px)
    return bool((g[:, :8] == g[:, 8:]).mean() >= 0.95), bool((g[:8] == g[8:]).mean() >= 0.95)

def make_seamless(img, h, v, hh=False, hv=False):
    """Make a repeating tile meet itself across its edges (h: left/right,
    v: top/bottom).
    Axes where the 8-bit tile repeats every half tile (hh/hv): blend the art
    with itself shifted by half a tile; the shifted copy runs on across the
    tile's edges and lines up with the 8-bit pattern, the original keeps the
    middle, so painted strokes cross the edge instead of stopping at a line.
    Other repeating axes: (1) the edge colours are matched row by row, the
    correction fading over ~12 pixels from each edge, then (2) a wrap-around
    blur within a few pixels of the seam."""
    a = np.asarray(img.convert('RGB')).astype(float)
    W = a.shape[1]; x = np.arange(W)
    if hh or hv:
        dist = np.minimum(x, W - 1 - x).astype(float)                 # 0 at the edges, W/2 in the middle
        w = np.clip((dist - 0.10 * W) / (0.25 * W), 0, 1); w = w * w * (3 - 2 * w)   # 0 near edges -> 1 inside
        if hh:
            a = a * w[None, :, None] + np.roll(a, W // 2, axis=1) * (1 - w[None, :, None])
        if hv:
            a = a * w[:, None, None] + np.roll(a, W // 2, axis=0) * (1 - w[:, None, None])
        h, v = h and not hh, v and not hv
    # Edges whose colours differ a lot are not one repeating texture in the art
    # (a tower's foot standing on a red floor matches itself in the 8-bit tile
    # but not in the painting): correcting those would smear them, so they are
    # left as painted.
    fall = np.exp(-x / 12.0)                                            # weight from the left/top edge
    if h:
        coarse = ndimage.gaussian_filter1d(a[:, :8].mean(1) - a[:, -8:].mean(1), 10, axis=0, mode='wrap')
        d = ndimage.gaussian_filter1d(a[:, :4].mean(1) - a[:, -4:].mean(1), 3, axis=0, mode='wrap')
        if np.abs(coarse).mean() > SEAM_MAX: h = False
        else: a += d[:, None, :] * (0.5 * fall[::-1][None, :, None] - 0.5 * fall[None, :, None])
    if v:
        coarse = ndimage.gaussian_filter1d(a[:8].mean(0) - a[-8:].mean(0), 10, axis=0, mode='wrap')
        d = ndimage.gaussian_filter1d(a[:4].mean(0) - a[-4:].mean(0), 3, axis=0, mode='wrap')
        if np.abs(coarse).mean() > SEAM_MAX: v = False
        else: a += d[None, :, :] * (0.5 * fall[::-1][:, None, None] - 0.5 * fall[:, None, None])
    dist = np.minimum(x, W - 1 - x) + 0.5
    wgt = np.exp(-(dist / 5.0) ** 2)
    if h:
        a = a * (1 - wgt[None, :, None]) + ndimage.gaussian_filter1d(a, 3, axis=1, mode='wrap') * wgt[None, :, None]
    if v:
        a = a * (1 - wgt[:, None, None]) + ndimage.gaussian_filter1d(a, 3, axis=0, mode='wrap') * wgt[:, None, None]
    return Image.fromarray(np.clip(np.round(a), 0, 255).astype(np.uint8))

# ---- shared ground ----------------------------------------------------------
# The game builds one ground (grass, sand, a floor) from several tiles: a plain
# one and others that carry an object on the same ground (a castle on the
# overworld's grass, the Endor arena's sand edge strips). The owner's art
# paints each tile's ground its own way, so the HD map shows patches. For each
# tile version next to a plain ground tile of the same palette on a captured
# map, the pixels where the 8-bit tile *is* that ground (same colour index at
# the same place) take the plain tile's HD texture, drawn as the player draws
# it, with a soft edge; paint of the object that spills over the 8-bit outline
# is kept. The result is stored as that version's picture (its fades recolour
# it with rgbd:).
GROUND_MIN, GROUND_MAX = 0.04, 0.97     # share of the tile that is the ground
EXTRA_GROUND_FP = {json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hd', 'field', 'ids.json')))['ids'][i][0]
                   for i in ('W001',)}             # art IDs of multi-colour grounds (W001 = the open sea)
GROUND_MIN_SEEN = 2                     # times seen next to each other on the maps
GROUND_LOG = open(os.environ['DW4_GROUND_LOG'], 'w') if os.environ.get('DW4_GROUND_LOG') else None
OBJ_KEEP = 0.5                          # keep a ground pixel when this much nearer the tile's object paint

def plain_tile(px):
    """A plain ground: at most two colours, repeating seamlessly both ways."""
    g = np.array(px)
    if len(np.unique(g)) > 2: return False
    h, v = tileable(g)
    return h and v

def chan_fit(src, pal, W):
    """Per-channel affine map from palette `src`'s colours to `pal`'s (weights W)."""
    def rgb(c): v = NES[c & 0x3F]; return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], float)
    X = np.array([rgb(src[k]) for k in range(4)]); Y = np.array([rgb(pal[k]) for k in range(4)]); fit = []
    for ch in range(3):
        x, y = X[:, ch], Y[:, ch]; mx, my = (W * x).sum() / W.sum(), (W * y).sum() / W.sum()
        vx = (W * (x - mx) ** 2).sum()
        g = (W * (x - mx) * (y - my)).sum() / vx if vx > 50 else ((W @ Y.mean(1)) / max(W @ X.mean(1), 1))
        g = float(np.clip(g, 0, 3)); fit.append((g, my - g * mx))
    return fit

def render_look(lk):
    """A version's picture as the player draws it (160x160 RGB float)."""
    im = Image.open(lk['path']).convert('RGB')
    if im.size != (160, 160): im = im.resize((160, 160), Image.LANCZOS)
    if lk['h'] or lk['v'] or lk['hh'] or lk['hv']: im = make_seamless(im, lk['h'], lk['v'], lk['hh'], lk['hv'])
    a = np.asarray(im).astype(float)
    m = re.match(r',rgb(l?):(.*)', lk['xf'])
    if m:
        vals = [float(x) for x in m[2].split('/')]; g, o = np.array(vals[0::2]), np.array(vals[1::2])
        src = (a @ np.array([0.299, 0.587, 0.114]))[..., None] if m[1] else a
        a = np.clip(np.floor(src * g + o + 0.5), 0, 255)
    return a

def ground_pairs(maps, items):
    """(tile, palette) -> the plain ground tile seen next to it most, same palette."""
    from vramdump import load
    by_chr = {bytes.fromhex(vs[0]['chr']): iid for iid, vs in items.items()}
    plain = {iid for iid, vs in items.items() if plain_tile(pixels(bytes.fromhex(vs[0]['chr'])))}
    # grounds with more than two colours: the open sea (its shores must carry the same water)
    plain |= {iid for iid, vs in items.items() if hashlib.sha1(bytes.fromhex(vs[0]['chr'])).hexdigest()[:16] in EXTRA_GROUND_FP}
    adj = collections.Counter()
    mems = sorted(glob.glob(os.path.join(maps, '*.mem')) + glob.glob(os.path.join(maps, 'view', '*.mem')))
    for path in mems:
        m = load(path); ch, ci, pal = m['chr_ram'], m['ciram'], m['palette']
        for nt in (0, 0x400):
            grid = {}
            for r in range(0, 28, 2):
                for c in range(0, 32, 2):
                    q = b''.join(bytes(ch[0x1000 + 16 * ci[nt + rr * 32 + cc]:0x1010 + 16 * ci[nt + rr * 32 + cc]])
                                 for rr, cc in ((r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)))
                    at = ci[nt + 0x3C0 + (r // 4) * 8 + c // 4]; sub = (at >> (((r % 4) // 2) * 4 + ((c % 4) // 2) * 2)) & 3
                    it = by_chr.get(q)
                    if it: grid[(r, c)] = (it, bytes([pal[0], pal[sub * 4 + 1], pal[sub * 4 + 2], pal[sub * 4 + 3]]))
            for (r, c), (t, p) in grid.items():
                if t in plain: continue
                for dr, dc in ((-2, 0), (2, 0), (0, -2), (0, 2)):
                    g = grid.get((r + dr, c + dc))
                    if g and g[0] in plain and g[0] != t: adj[(t, p, g[0], g[1])] += 1
    # grounds also seen where the captures don't reach (the overworld coast):
    # a tile drawn in the same palette whose 8-bit pixels are partly that ground
    for g in {iid for iid, vs in items.items() if hashlib.sha1(bytes.fromhex(vs[0]['chr'])).hexdigest()[:16] in EXTRA_GROUND_FP}:
        gp_ = np.array(pixels(bytes.fromhex(items[g][0]['chr'])))
        gpals = {bytes.fromhex(r['nes_colors']) for r in items[g]}
        for t, vs in items.items():
            if t == g or t[0] != g[0]: continue
            share = (np.array(pixels(bytes.fromhex(vs[0]['chr']))) == gp_).mean()
            if not 0.25 <= share <= 0.97: continue
            for r in vs:
                p = bytes.fromhex(r['nes_colors'])
                if p in gpals: adj[(t, p, g, p)] += GROUND_MIN_SEEN
    best = {}
    for (t, p, g, gp), n in adj.items():
        if n >= GROUND_MIN_SEEN and ((t, p) not in best or n > best[(t, p)][1]): best[(t, p)] = ((g, gp), n)
    return {k: v[0] for k, v in best.items()}

def ground_mask(tpx, tpal, gpx, gpal):
    """Pixels where the tile shows the ground: the same NES colour at the same
    place (the palettes may differ: a castle drawn in its own sub-palette
    shares the grass's green through another colour index)."""
    col = lambda c: c & 0x3F if c & 0x0F < 0x0D else 0x0F
    tc = np.vectorize(lambda k: col(tpal[k]))(tpx); gc = np.vectorize(lambda k: col(gpal[k]))(gpx)
    m8 = (tc == gc) & (tc != 0x0F)          # black: outlines, mortar, the void - never ground
    lab, nl = ndimage.label(m8)
    for j in range(1, nl + 1):
        if (lab == j).sum() < 3: m8[lab == j] = False          # stray matching pixels, not ground
    return m8

def centres(X, k=4, it=8):
    """k colour centres of the pixels X (n x 3), a few rounds of k-means."""
    X = X[:: max(1, len(X) // 4000)]
    c = X[np.linspace(0, len(X) - 1, k).astype(int)].copy()
    for _ in range(it):
        lab = ((X[:, None] - c[None]) ** 2).sum(2).argmin(1)
        for j in range(k):
            if (lab == j).any(): c[j] = X[lab == j].mean(0)
    return c

def nearest(img, c):
    """Distance from each pixel of img (h x w x 3) to its nearest centre."""
    return np.sqrt(((img[..., None, :] - c[None, None]) ** 2).sum(3)).min(2)

def border_score(A, B, side):
    """How much the HD picture jumps from A to B at their border (B right of A,
    or below it), minus the texture's own change over the same distance
    (tools/seam_check.py's measure)."""
    W = 6
    def strip(a_, first, off):
        if side: return a_[:, 160 - (off + 1) * W:160 - off * W] if first else a_[:, off * W:(off + 1) * W]
        return a_[160 - (off + 1) * W:160 - off * W, :] if first else a_[off * W:(off + 1) * W, :]
    def dist(p1, p2):
        d = 0.0
        for k in range(8):
            sl = slice(k * 20, k * 20 + 20)
            q1 = (p1[sl] if side else p1[:, sl]).reshape(-1, 3); q2 = (p2[sl] if side else p2[:, sl]).reshape(-1, 3)
            d += np.linalg.norm(q1.mean(0) - q2.mean(0)) + 0.5 * np.linalg.norm(q1.std(0) - q2.std(0))
        return d / 8
    across = dist(strip(A, True, 0), strip(B, False, 0))
    inside = max(dist(strip(A, True, 1), strip(A, True, 0)), dist(strip(B, False, 0), strip(B, False, 1)))
    return max(0.0, across - inside)

def continuous8(ca, cb, side):
    """The 8-bit tiles (16x16 NES colours) run on across this border."""
    a = ca[:, -2:] if side else ca[-2:, :]; b = cb[:, :2] if side else cb[:2, :]
    ha = collections.Counter(a.ravel()); hb = collections.Counter(b.ravel()); n = a.size
    return sum(abs(ha[k] - hb[k]) for k in set(ha) | set(hb)) / (2 * n) < 0.35

def seam_total(T, G, ct, cg):
    """Seams of picture T (8-bit colours ct) with the ground G and with itself,
    over the borders that are continuous in 8-bit: (total, per border)."""
    out = []
    for A, B, ca, cb, side in ((T, G, ct, cg, True), (G, T, cg, ct, True), (T, G, ct, cg, False), (G, T, cg, ct, False),
                               (T, T, ct, ct, True), (T, T, ct, ct, False)):
        if continuous8(ca, cb, side): out.append(border_score(A, B, side))
    return sum(out), out

def shared_ground(a, items, looks, versions, add_img):
    pairs = ground_pairs(a.maps, items)
    px = {iid: np.array(pixels(bytes.fromhex(vs[0]['chr']))) for iid, vs in items.items()}
    stats = collections.Counter()
    done, n = {}, 0
    by_id = {v['id']: v for v in versions}
    ids = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hd', 'field', 'ids.json')))['ids']
    ref = {fp: bytes.fromhex(pal) for fp, pal in ids.values()}
    extra = {iid: ref[hashlib.sha1(bytes.fromhex(vs[0]['chr'])).hexdigest()[:16]] for iid, vs in items.items()
             if hashlib.sha1(bytes.fromhex(vs[0]['chr'])).hexdigest()[:16] in EXTRA_GROUND_FP}
    for v in versions:
        if not v['real']: continue
        key = (v['item'], v['pal']); gk = pairs.get(key)
        if not gk or key not in looks or gk not in looks: continue
        g, gp = gk
        # a multi-colour ground (the open sea): the same pixels are water in
        # every palette, so the mask comes from the art's own (day) palette -
        # at night one of the sea's colours is black, which the colour test
        # reads as outline, and most shore tiles kept their own water
        sea = extra.get(g)
        m8 = ground_mask(px[v['item']], sea, px[g], sea) if sea and v['pal'] == gp else ground_mask(px[v['item']], v['pal'], px[g], gp)
        share = m8.mean()
        if not GROUND_MIN <= share <= GROUND_MAX: continue
        if key not in done:
            T, G = render_look(looks[key]), render_look(looks[gk])
            big = np.kron(m8, np.ones((10, 10))).astype(bool)
            # the ring just outside the ground: replace only what looks like the
            # tile's own painted ground (keep object paint spilling over the outline)
            ring = np.kron(ndimage.binary_dilation(m8), np.ones((10, 10))).astype(bool) & ~big
            # per pixel: nearer the ground tile's colours (swap) or the tile's
            # own object paint (keep: bushes or towers the art paints over 8-bit ground)
            obj = np.kron(ndimage.binary_erosion(~m8), np.ones((10, 10))).astype(bool)
            Tb = ndimage.gaussian_filter(T, (1.5, 1.5, 0))
            dg = nearest(Tb, centres(ndimage.gaussian_filter(G, (1.5, 1.5, 0)).reshape(-1, 3)))
            do = nearest(Tb, centres(Tb[obj])) if obj.sum() > 200 else np.full(dg.shape, np.inf)
            # inside the 8-bit ground: swap unless clearly object paint;
            # on the rim outside it: swap only what looks like ground
            mask = ((big & ~(do < OBJ_KEEP * dg)) | (ring & (dg < do))).astype(float)
            if sea: mask = (big | (ring & (dg < do))).astype(float)   # (water is never object paint)
            mask = ndimage.gaussian_filter(mask, 2.0, mode='nearest')
            out = T * (1 - mask[..., None]) + G * mask[..., None]
            # keep it only where it helps: the seams with the ground tile and
            # with its own copies must drop, none may get clearly worse
            col = lambda pal, px_: np.vectorize(lambda k: pal[k] & 0x3F)(px_)
            ct, cg = col(v['pal'], px[v['item']]), col(gp, px[g])
            before, bl = seam_total(T, G, ct, cg); after, al_ = seam_total(out, G, ct, cg)
            ok = bl and (after < 0.8 * before or after <= 10) and all(y <= x + 12 for x, y in zip(bl, al_))
            ok = bool(ok or sea)                 # the sea's shores always carry the sea's water, in every palette alike
            stats['helps' if ok else 'no gain'] += 1
            if GROUND_LOG: GROUND_LOG.write(f"{v['item']}\t{v['pal'].hex()}\t{g}\t{gp.hex()}\t{share:.2f}\t{before:.0f}\t{after:.0f}\t{ok}\n")
            if not ok: done[key] = None; continue
            name = f"{looks[key]['aid']}_g{v['pal'].hex()}"
            done[key] = add_img(Image.fromarray(np.clip(np.round(out), 0, 255).astype(np.uint8)), name)
        if done[key] is None: continue
        v['img'], v['xf'] = done[key], ''
        W = looks[key]['W']
        for k in (1, 2, 3):
            f = by_id.get(f"{v['id']}~{k}")
            if not f: continue
            fit = chan_fit(v['pal'], f['pal'], W)
            gkey = tuple((round(gg / 0.05) * 0.05, round(o / 4) * 4) for gg, o in fit)
            f['img'], f['xf'] = done[key], ',rgbd:' + '/'.join(f'{gg:.2f}/{int(o)}' for gg, o in gkey)
        n += 1
    print(f'  shared ground: {dict(stats)} (tile versions tried)')
    return n

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('field_tiles'); ap.add_argument('art'); ap.add_argument('outdir')
    ap.add_argument('--report')
    ap.add_argument('--maps', help='the map capture (MM_SS.mem dumps): tiles next to a plain ground take its texture')
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
    def add_img_top(img, name):
        nonlocal img_index
        rel = f'field/{name}.png'; img.save(os.path.join(a.outdir, rel))
        lines.append(f'<img>{rel}'); img_index += 1; return img_index - 1
    os.makedirs(os.path.join(a.outdir, 'field'), exist_ok=True)

    # ---- versions: (item, palette, image, brightness) ---------------------
    def rgb(c): v = NES[c & 0x3F]; return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], float)
    def counts(t):
        px = np.array(pixels(t)); return np.array([(px == k).sum() for k in range(4)], float)
    def lum(pal, cnt): return sum(cnt[k] * rgb(pal[k]) @ (0.299, 0.587, 0.114) for k in range(4))
    def fade(pal, k): return bytes(0x0F if (c & 0x3F) < 0x10 * k or (c & 0x0F) >= 0x0D else c - 0x10 * k for c in pal)
    night = lambda r: all(u.endswith('(night)') for u in r['used_in'])
    versions = []        # dicts: id, item, chr, pal, img, bright, uses, real
    looks = {}           # (item, palette) -> how the player draws that version (for the ground pass)
    missing, seamless, nights, lums = [], 0, 0, 0
    for iid, vs in items.items():
        # with ids.json the fingerprint is the only match: a tile that is new
        # in this build must never pick up art that belongs to another tile
        aid = art_for.get(iid) if os.path.exists(idmap) else iid
        base = os.path.join(a.art, (aid or '-') + '.png')
        if not aid or not os.path.exists(base): missing.append(iid); continue
        t = bytes.fromhex(vs[0]['chr']); cnt = counts(t)
        h, v = tileable(pixels(t)); hh, hv = half_periodic(pixels(t))
        def load(path):
            im = Image.open(path).convert('RGB')
            if im.size != (160, 160): im = im.resize((160, 160), Image.LANCZOS)
            return make_seamless(im, h, v, hh, hv) if (h or v or hh or hv) else im
        if h or v: seamless += 1
        def add_img(img, name):
            nonlocal img_index
            rel = f'field/{name}.png'; img.save(os.path.join(a.outdir, rel))
            lines.append(f'<img>{rel}'); img_index += 1; return img_index - 1
        base_img = load(base); main_idx = None; tinted = {}
        ref = bytes.fromhex(ref_pal.get(iid) or vs[0]['nes_colors'])   # palette the art was made for
        W = cnt + 0.5
        def fit_of(pal, src=None):
            # per channel affine map from the art's colours (drawn for `src`,
            # default the art's own palette) to the colours of `pal`
            X = np.array([rgb((src or ref)[k]) for k in range(4)])
            Y = np.array([rgb(pal[k]) for k in range(4)]); fit, err = [], 0.0
            for ch in range(3):
                x, y = X[:, ch], Y[:, ch]; mx, my = (W * x).sum() / W.sum(), (W * y).sum() / W.sum()
                vx = (W * (x - mx) ** 2).sum()
                g = (W * (x - mx) * (y - my)).sum() / vx if vx > 50 else ((W @ Y.mean(1)) / max(W @ X.mean(1), 1))
                g = float(np.clip(g, 0, 3)); fit.append((g, my - g * mx))
                err += float((W * (g * x + my - g * mx - y) ** 2).sum())
            return fit, err
        LW = np.array([0.299, 0.587, 0.114])
        def lum_fit(pal, src=None):
            # colour by brightness: each channel = a*L + b of the art's
            # brightness L, fitted from the art's colours to `pal`'s
            X = np.array([rgb((src or ref)[k]) for k in range(4)]) @ LW
            Y = np.array([rgb(pal[k]) for k in range(4)]); fit, err = [], 0.0
            mx = (W * X).sum() / W.sum(); vx = (W * (X - mx) ** 2).sum()
            for ch in range(3):
                y = Y[:, ch]; my = (W * y).sum() / W.sum()
                g = (W * (X - mx) * (y - my)).sum() / vx if vx > 50 else 0.0
                g = float(np.clip(g, 0, 3)); fit.append((g, my - g * mx))
                err += float((W * (g * X + my - g * mx - y) ** 2).sum())
            return fit, err
        def hue_shift(pal, src=None):
            # how far the tile's colours turn round the colour wheel (degrees,
            # weighted by use; greys and black don't count)
            tot = wsum = 0.0
            for k in range(1, 4):
                a, b = rgb((src or ref)[k]) / 255, rgb(pal[k]) / 255
                ha, sa, _ = colorsys.rgb_to_hsv(*a); hb, sb, _ = colorsys.rgb_to_hsv(*b)
                if sa < 0.2 or sb < 0.2: continue
                d = abs(ha - hb) * 360; d = min(d, 360 - d)
                tot += cnt[k] * d; wsum += cnt[k]
            return tot / wsum if wsum else 0.0
        def use_lum(pal, src=None):
            # a big hue change that a per-channel map gets wrong (green grass
            # in a pale-yellow sand palette came out coral-pink)
            h, el, ec = hue_shift(pal, src), lum_fit(pal, src)[1], fit_of(pal, src)[1]
            if LUM_LOG: LUM_LOG.write(f'{iid}\t{pal.hex()}\t{(src or ref).hex()}\t{h:.0f}\t{el:.0f}\t{ec:.0f}\n')
            return h > HUE_LUM and el < LUM_RATIO * ec
        # The game animates some tiles by swapping colours (the overworld sea
        # cycles 0F 30 21 12 <-> 0F 30 12 21). A palette that is only a
        # reordering of another is the same picture: the whole group uses the
        # recolour of the member whose order fits the art best (the art's own
        # palette when it is in the group), so the HD tile holds still instead
        # of flashing between a good and a garbled tint.
        fits = {r['nes_colors']: fit_of(bytes.fromhex(r['nes_colors'])) for r in vs}
        group = lambda h: (h[:2], tuple(sorted(h[i:i + 2] for i in range(2, 8, 2))))
        rep = {}
        for h in sorted(fits, key=lambda h: (bytes.fromhex(h) != ref, fits[h][1])):
            rep.setdefault(group(h), h)
        for r in vs:
            pal = bytes.fromhex(r['nes_colors'])
            over = os.path.join(a.art, aid + r['id'][len(iid):] + '.png') if r['id'] != iid else None
            rp = bytes.fromhex(rep[group(r['nes_colors'])])
            lum = use_lum(rp)
            fit = lum_fit(rp)[0] if lum else fits[rep[group(r['nes_colors'])]][0]
            xf = ''
            if over and os.path.exists(over):
                idx = add_img(load(over), aid + r['id'][len(iid):])
            else:
                if main_idx is None: main_idx = add_img(base_img, aid)
                idx = main_idx
                if lum or any(abs(g - 1) > 0.06 or abs(o) > 8 for g, o in fit):
                    # recoloured by the player at load time (patch 0011; by
                    # brightness with rgbl:, patch 0024), not stored
                    gkey = tuple((round(g / 0.05) * 0.05, round(o / 4) * 4) for g, o in fit)
                    xf = (',rgbl:' if lum else ',rgb:') + '/'.join(f'{g:.2f}/{int(o)}' for g, o in gkey)
                    if lum: lums += 1
                    if gkey not in tinted: tinted[gkey] = True; nights += 1
            uses = len(r['used_in'])
            versions.append(dict(id=r['id'], item=iid, chr=t, pal=pal, img=idx, xf=xf, bright=1.0, uses=uses, real=True))
            looks.setdefault((iid, pal), dict(path=over if (over and os.path.exists(over)) else base, h=h, v=v, hh=hh, hv=hv, xf=xf, aid=aid, W=W.copy()))
            # The screen-fade steps (each colour -$10, black below $10): the art
            # recoloured to the step's own NES colours, as the game shows them
            # (deep blues and greens, parts going black first), not dimmed.
            src = pal if (over and os.path.exists(over)) else ref
            for k in (1, 2, 3):
                fp = fade(pal, k)
                if all((c & 0x0F) >= 0x0D or c == 0x0F for c in fp[1:]) and fp[0] == 0x0F and k == 3:
                    continue                                   # black: nothing to draw
                ffit = (lum_fit if lum else fit_of)(fp, src)[0]
                gkey = tuple((round(g / 0.05) * 0.05, round(o / 4) * 4) for g, o in ffit)
                # applied while drawing (rgbd:, patch 0022): fade frames are few,
                # and a decoded copy per step would cost ~650 MB
                fxf = (',rgbdl:' if lum else ',rgbd:') + '/'.join(f'{g:.2f}/{int(o)}' for g, o in gkey)
                versions.append(dict(id=f'{r["id"]}~{k}', item=iid, chr=t, pal=fp, img=idx, xf=fxf, bright=1.0,
                                     uses=uses / (10 * k), real=False))

        # Damage-floor flash: each step on a damage floor turns every background
        # colour red ($16 in all four sub-palettes) for 3 frames. The art is
        # shown tinted red (rgb: at load time, nothing stored) instead of 8-bit.
        if main_idx is None: main_idx = add_img(base_img, aid)
        versions.append(dict(id=f'{iid}~flash', item=iid, chr=t, pal=FLASH, img=main_idx, xf=FLASH_XF, bright=1.0,
                             uses=0.01, real=False))

    # ---- shared ground: tiles next to a plain ground take its texture ------
    grounded = 0
    if a.maps:
        grounded = shared_ground(a, items, looks, versions, add_img_top)
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
            if v['pal'] == FLASH and not any(v['chr'][16 * q:16 * q + 16]): continue   # blank: every map's void shares this key
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
        for v, q in own: distinct.setdefault((v['img'], v['xf'], q, v['bright']), (v, q))
        own = sorted(distinct.values(), key=lambda vq: (-vq[0]['real'], -vq[0]['uses']))
        blank = not any(bytes.fromhex(chr_hex))
        out_list = real_tiles if own[0][0]['real'] else fade_tiles
        entry = lambda v, q: (f'<tile>{v["img"]},{chr_hex},{pal},{QOFF[q][0] * 10},{QOFF[q][1] * 10},'
                              f'{v["bright"]:g},N{v["xf"]}')
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
    # the map scrolls: let the player fix the tile rows drawn one step before
    # their colours at the top/bottom edge (nesrecomp patch 0018)
    if not any(l.startswith('<options>') and 'edgePaletteFallback' in l for l in rest):
        rest = ['<options>edgePaletteFallback'] + rest
    out = head + imgl + rest + [f'# HD map tiles ({len(items) - len(missing)} tiles): owner art keyed per 8x8 quarter + exact palette'] + conds + tiles
    open(hires, 'w').write('\n'.join(out) + '\n')
    print(f'{len(items) - len(missing)} map tiles ({seamless} made seamless, {nights} palette recolours), '
          f'{sum(v["real"] for v in versions)} palette versions + {sum(not v["real"] for v in versions)} fade steps, '
          f'{len(tiles)} tile entries, '
          f'{len(conds)} neighbour conditions, {unresolved} unresolved, {lums} coloured by brightness, '
          f'{grounded} versions on shared ground -> {hires}')
    # overworld definitions the map never draws (WRAM $1680 slots past the
    # 32 the map data uses): not missing art, nothing to paint
    never = []
    if missing and a.maps:
        shown = overworld_on_screen(a.maps)
        never = [m for m in missing if m[0] == 'W' and bytes.fromhex(items[m][0]['chr']) not in shown]
        missing = [m for m in missing if m not in never]
    if missing: print(f'  no art yet for {len(missing)}: {" ".join(missing[:20])}{" ..." if len(missing) > 20 else ""}')
    if never: print(f'  {len(never)} overworld definitions never drawn (no art needed): {" ".join(never)}')
    if a.report:
        json.dump({'missing': missing, 'never_drawn': never, 'seamless': seamless, 'palette_recolours': nights, 'entries': len(tiles), 'conditions': len(conds),
                   'unresolved': unresolved, 'gated_only_blank': gated_only}, open(a.report, 'w'), indent=1)

if __name__ == '__main__':
    main()
