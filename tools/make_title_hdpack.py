"""Add the owner's layered HD title screen (hd/title/layers/, see layout.json)
to an HD pack directory.

The title (nametable 0, pattern table $1000): a castle on a sea of clouds
under a blue sky; a stone plate appears, "DRAGON WARRIOR" is typed letter by
letter, then "IV" and the TM appear as the sky turns to sunset
(tools/capture_extras.py: frame 1200 = blue, 2400 = finished). Below
scanline 195 the game scrolls the clouds in two bands (1 px / 4 frames to
scanline 210, 1 px / 2 frames below), each wrapping at 256 px.

The owner painted it in layers, so the HD title is drawn from them instead
of being cut into 8x8 tiles:

  sky (+ castle)  <background>, still, behind everything
  plate           <background>, shown while the game draws the plate
  lettering       per 8x8 cell, revealed as the game draws each letter
  clouds          two <background>s over the background tiles, each scrolling
                  with one of the game's cloud bands (line:Y, patch 0013) and
                  repeating sideways (wrap)

The phase (day / sunset, and the screen-fade steps of each) is read from one
castle cell and one plate cell (tileAtPosition: CHR + colours). Every other
title cell gets an almost transparent HD tile (so the layers show through
instead of the 8-bit tile); letter cells get the painted letter where the
8-bit letter is already drawn, and the blank cells beside a letter show the
painted letter's edge once that letter is complete (tileNearby). Without
*_day files the day look is recoloured from the sunset art: each pixel moves
by the colour change of the NES colours it is closest to ($16 red sky -> $3C,
$06/$26 castle -> $2C, $37 cream -> $3C). The cloud strips are made to repeat
seamlessly by blending their ends into a half-turned copy.

usage: make_title_hdpack.py EXTRA_CAPTURE OUTDIR
"""
import collections, json, os, sys
import numpy as np
from PIL import Image, ImageFilter
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from field_sheet import NES

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LAYERS = os.path.join(HERE, 'hd', 'title', 'layers')
S = 10
C = 8 * S
W, H = 256 * S, 240 * S
DAY_OF = {0x16: 0x3C, 0x06: 0x2C, 0x26: 0x2C, 0x37: 0x3C, 0x20: 0x20, 0x30: 0x30, 0x10: 0x10, 0x00: 0x00}

def rgb(c): v = NES[c & 0x3F]; return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], float)
def fade(pal, k): return bytes(0x0F if (c & 0x3F) < 0x10 * k or (c & 0x0F) >= 0x0D else c - 0x10 * k for c in pal)
# the screen fades: every colour steps down by $10 per step; leaving the title
# (Start) the game also turns the backdrop black from the first step ('b')
STEPS = ('0', '1', '2', '3', '1b', '2b', '3b')
def step(pal, k):
    n = int(k[0]); p = fade(pal, n) if n else pal
    return bytes([0x0F]) + p[1:] if k.endswith('b') else p

def lum(cols): return sum(rgb(x) @ (0.299, 0.587, 0.114) for x in cols)

def cells(mem):
    m = load(mem); ci, ch, pal = m['ciram'], m['chr_ram'], m['palette']
    out = {}
    for ty in range(30):
        for tx in range(32):
            t = ci[ty * 32 + tx]; at = ci[0x3C0 + (ty // 4) * 8 + tx // 4]
            p = (at >> (((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2)) & 3
            out[(tx, ty)] = (bytes(ch[0x1000 + 16 * t:0x1000 + 16 * t + 16]), bytes([pal[0], pal[4 * p + 1], pal[4 * p + 2], pal[4 * p + 3]]), p)
    return out

def pixels(chr16):
    return np.array([[((chr16[r] >> (7 - c)) & 1) | (((chr16[r + 8] >> (7 - c)) & 1) << 1) for c in range(8)] for r in range(8)])

def recolour(img, src, dst, sigma=40.0):
    """Move each pixel (RGB float) by the colour change of the source colours it is near."""
    X = np.array([rgb(c) for c in src]); D = np.array([rgb(b) - rgb(a) for a, b in zip(src, dst)])
    out = np.empty_like(img)
    for y0 in range(0, img.shape[0], 256):                 # in strips (memory)
        part = img[y0:y0 + 256]
        d2 = ((part[..., None, :] - X[None, None]) ** 2).sum(-1)
        w = np.exp(-(d2 - d2.min(-1, keepdims=True)) / (2 * sigma * sigma)); w /= w.sum(-1, keepdims=True)
        out[y0:y0 + 256] = part + w @ D
    return out

def seamless_x(a, width):
    """Blend the strip's two ends into a copy turned by half its width, so it repeats sideways."""
    turned = np.roll(a, a.shape[1] // 2, axis=1)
    x = np.arange(a.shape[1]); m = np.clip(np.minimum(x, a.shape[1] - 1 - x) / width, 0, 1)[None, :, None]
    return a * m + turned * (1 - m)

def drop_red_fringe(a):
    """Layers cut from the composite keep a sliver of red sky at their edges: make it transparent."""
    red = (a[..., 0] > a[..., 1] + 60) & (a[..., 0] > a[..., 2] + 60)
    a[..., 3] = np.where(red, 0, a[..., 3]); return a

def letters_only(letters, red, blank):
    """The lettering layer carries a feathered block of its own stone around the
    letters; keep just the letters (bright carved faces near the 8-bit letters,
    holes filled, grown by their dark outline and shadow) so they sit on the
    blank plate like the 8-bit letters do."""
    from scipy import ndimage
    nes = np.zeros((240, 256), bool)
    for k, (c, pal, p) in red.items():
        if k in blank and blank[k] != c: nes[k[1] * 8:k[1] * 8 + 8, k[0] * 8:k[0] * 8 + 8] = pixels(c) != pixels(blank[k])
    small = np.asarray(Image.fromarray(np.clip(letters, 0, 255).astype(np.uint8), 'RGBA').resize((W // 2, H // 2), Image.LANCZOS)).astype(float)
    near = ndimage.binary_dilation(np.kron(nes, np.ones((S // 2, S // 2), bool)), iterations=14)
    lum = small[..., :3] @ np.array([0.299, 0.587, 0.114])
    core = ndimage.binary_fill_holes(ndimage.binary_closing((lum > 140) & (small[..., 3] > 128) & near, iterations=3))
    lab, n = ndimage.label(core)
    if n:
        sizes = ndimage.sum(core, lab, range(1, n + 1)); core = np.isin(lab, 1 + np.flatnonzero(sizes > 60))
    matte = Image.fromarray((ndimage.binary_dilation(core, iterations=4) * 255).astype(np.uint8))
    matte = np.asarray(matte.filter(ImageFilter.GaussianBlur(1.5)).resize((W, H), Image.BILINEAR)).astype(float) / 255
    out = letters.copy(); out[..., 3] *= matte; return out

def main():
    cap, outdir = sys.argv[1], sys.argv[2]
    lay_p = os.path.join(LAYERS, 'layout.json')
    if not os.path.exists(lay_p): print('  title: no layers'); return
    lay = json.load(open(lay_p)); f = W / lay['canvas'][0]
    red, blue = cells(os.path.join(cap, 'title_2400.mem')), cells(os.path.join(cap, 'title_1200.mem'))
    seq = json.load(open(os.path.join(cap, 'title_seq.json')))
    blank = {tuple(map(int, k.split(','))): bytes.fromhex(v) for k, v in seq['blank'].items()}

    def layer(spec, look):
        name = spec['files'].get(look) or spec['files'].get('all')
        if not name and look == 'day': return None
        im = Image.open(os.path.join(LAYERS, name)).convert('RGBA')
        im = im.resize((round(im.width * f), round(im.height * f)), Image.LANCZOS)
        return np.asarray(im).astype(float)
    specs = {s['name']: s for s in lay['layers']}

    # sunset -> day without a painted day version: keep the painting's light and
    # shade (luminance) and give it daytime colours along a ramp
    SKY_RAMP = [(0, (25, 70, 150)), (30, (40, 120, 205)), (70, (110, 180, 240)), (140, (175, 220, 252)), (220, (230, 246, 255))]
    CLOUD_RAMP = [(60, (110, 140, 190)), (120, (165, 190, 225)), (180, (215, 232, 250)), (235, (255, 255, 255))]
    def day_of(a, ramp):
        if a is None: return None
        L = a[..., :3] @ np.array([0.299, 0.587, 0.114])
        xs = [p[0] for p in ramp]
        out = a.copy()
        for ch in range(3): out[..., ch] = np.interp(L, xs, [p[1][ch] for p in ramp])
        return out

    os.makedirs(os.path.join(outdir, 'title'), exist_ok=True)
    save = lambda a, n: Image.fromarray(np.clip(np.round(a), 0, 255).astype(np.uint8), 'RGBA' if a.shape[2] == 4 else 'RGB').save(
        os.path.join(outdir, 'title', n), optimize=True)
    files = {}
    # sky (opaque, full screen)
    sky = layer(specs['sky'], 'sunset')[..., :3]; x0, y0 = [round(v * f) for v in specs['sky']['at']]
    full = np.zeros((H, W, 3)); full[y0:y0 + sky.shape[0], x0:x0 + sky.shape[1]] = sky[:H - y0, :W - x0]
    day = layer(specs['sky'], 'day'); day = day[..., :3] if day is not None else day_of(np.dstack([full, np.full(full.shape[:2], 255.0)]), SKY_RAMP)[..., :3]
    save(full, 'sky_sunset.png'); save(day, 'sky_day.png'); files['sky'] = {'sunset': 'sky_sunset.png', 'day': 'sky_day.png'}
    # plate and lettering on full canvases
    def canvas(name):
        a = drop_red_fringe(layer(specs[name], 'all')); x0, y0 = [round(v * f) for v in specs[name]['at']]
        c = np.zeros((H, W, 4)); h, w = min(a.shape[0], H - y0), min(a.shape[1], W - x0)
        c[y0:y0 + h, x0:x0 + w] = a[:h, :w]; return c
    plate, letters = canvas('plate'), canvas('lettering')
    save(plate, 'plate.png')
    letters = letters_only(letters, red, blank)
    # which 8-bit letter cell each painted letter pixel belongs to. The painted
    # letters are told apart by their solid faces (connected pieces); each piece
    # goes with the 8-bit letter cells it covers, and each of its pixels with the
    # nearest 8-bit pixel of those cells. Outline and shadow pixels go with the
    # nearest piece.
    from scipy import ndimage
    letter_cells = sorted(k for k in red if k in blank and red[k][0] != blank[k])
    cell_id = {k: n + 1 for n, k in enumerate(letter_cells)}
    final_at = {tuple(map(int, k.split(','))): v for k, v in seq.get('final_at', {}).items()}
    nes_id = np.zeros((240, 256), np.int32)
    for k in letter_cells:
        tx, ty = k
        nes_id[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8][pixels(red[k][0]) != pixels(blank[k])] = cell_id[k]
    # Each painted pixel goes with the nearest 8-bit letter pixel's cell, measured
    # at 10x. The letters that only come with the sunset ("IV", the TM) win ties
    # within 1.5 px: the TM's stems touch the R below it, and a stem must not
    # show up with the R before the TM is there.
    last = max(final_at.values()) if final_at else 0
    late = np.array([False] + [final_at.get(k, 0) >= last for k in letter_cells])
    big = np.kron(nes_id, np.ones((S, S), np.int32))
    def nearest(ids):
        if not ids.any(): return np.full(ids.shape, 1e9), np.zeros(ids.shape, np.int32)
        d, (iy, ix) = ndimage.distance_transform_edt(ids == 0, return_indices=True)
        return d, ids[iy, ix]
    d_e, o_e = nearest(np.where(~late[big] & (big > 0), big, 0))
    d_l, o_l = nearest(np.where(late[big], big, 0))
    owner = np.where(d_l <= d_e + 1.5 * S, o_l, o_e)
    def part(cells_, tx, ty):
        """The painted letters' pixels inside cell (tx, ty) that belong to cells_."""
        a = letters[ty * C:(ty + 1) * C, tx * C:(tx + 1) * C].copy()
        own = np.isin(owner[ty * C:(ty + 1) * C, tx * C:(tx + 1) * C], [cell_id[c] for c in cells_])
        a[..., 3] *= own; return a
    # clouds: strips placed at a whole native row, seamless sideways
    strips = []
    for name in ('clouds_back', 'clouds_front'):
        sp = specs[name]; y_at = round(sp['at'][1] * f); top = (y_at // S) * S
        out = {}
        for look in ('sunset', 'day'):
            a = layer(sp, look)
            if a is None: a = day_of(layer(sp, 'sunset'), CLOUD_RAMP)
            a = np.concatenate([np.zeros((y_at - top, a.shape[1], 4)), a], 0)
            if a.shape[1] != W: a = np.asarray(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), 'RGBA').resize((W, a.shape[0]), Image.LANCZOS)).astype(float)
            a = seamless_x(a, 48 * S)
            save(a, f'{name}_{look}.png'); out[look] = f'{name}_{look}.png'
        strips.append((name, top // S, sp.get('scroll_line', 200), out))

    # ---- conditions: title phase from a castle cell and a plate cell ---------
    def pick(p, rows):
        best = None
        for (tx, ty), (c, pal, pp) in red.items():
            if pp == p and ty in rows and blue[(tx, ty)][0] == c:
                n = (pixels(c) != 0).sum()
                if n > 8 and (best is None or n > best[0]): best = (n, tx, ty)
        return best[1], best[2]
    ctx, cty = pick(1, range(14, 22)); ptx, pty = pick(3, range(4, 6))
    conds, phases = [], []
    for look, cl in (('day', blue), ('sunset', red)):
        cc, cp = cl[(ctx, cty)][0], cl[(ctx, cty)][1]; pc, pp = cl[(ptx, pty)][0], cl[(ptx, pty)][1]
        for k in STEPS:
            cpk, ppk = step(cp, k), step(pp, k)
            dark = lambda q: all((x & 0x0F) >= 0x0D or x == 0x0F for x in q[1:])
            if k != '0' and dark(cpk) and dark(ppk): continue
            # once the castle has faded to black, the plate tells the phase as well
            ref, refk = (pp, ppk) if dark(cpk) else (cp, cpk)
            br = 1.0 if k == '0' else round(min(1.0, lum(refk[1:]) / lum(ref[1:])), 3)
            cn, pn = f'tc_{look}{k}', f'tp_{look}{k}'
            conds.append(f'<condition>{cn},tileAtPosition,{ctx * 8},{cty * 8},{cc.hex().upper()},{cpk.hex().upper()}')
            conds.append(f'<condition>{pn},tileAtPosition,{ptx * 8},{pty * 8},{pc.hex().upper()},{ppk.hex().upper()}')
            phases.append((look, k, br, f'{cn}&{pn}' if dark(cpk) else cn, pn))
    bgs = []
    for look, k, br, cn, pn in phases:
        bgs.append(f'[{cn}]<background>title/{files["sky"][look]},{br:g},0,0,1,0,0')
        bgs.append(f'[{cn}&{pn}]<background>title/plate.png,{br:g},0,0,2,0,0')
        for i, (name, top, line, out) in enumerate(strips):
            bgs.append(f'[{cn}]<background>title/{out[look]},{br:g},1,0,{22 + i},0,{-top},line:{line},wrap')

    # ---- 8x8 cells: almost transparent, except the lettering --------------------
    hires = os.path.join(outdir, 'hires.txt'); lines = open(hires).read().splitlines()
    n_img = sum(1 for l in lines if l.startswith('<img>'))
    atlas = [np.dstack([np.zeros((C, C, 3)), np.ones((C, C))])]            # cell 0: alpha 1/255
    def add_cell(a):
        atlas.append(a); return len(atlas) - 1
    def cell_of(a, tx, ty): return a[ty * C:(ty + 1) * C, tx * C:(tx + 1) * C]
    keys = collections.defaultdict(set)                                      # (chr, pal) -> positions
    for cl in (red, blue):
        for (tx, ty), (c, pal, p) in cl.items(): keys[(c, pal)].add((tx, ty))
    for tx, ty, c, pal in seq['states']: keys[(bytes.fromhex(c), bytes.fromhex(pal))].add((tx, ty))
    look_of = lambda pal: 'sunset' if pal[0] == red[(0, 0)][1][0] else 'day'
    plain, gated, nbc = [], [], {}
    cols = [f'<condition>nx{c},nametableColumn,==,{c}' for c in range(32)]
    rows = [x for r in range(30) for x in (f'<condition>ty{r}a,positionCheckY,>=,{r * 8}', f'<condition>ty{r}b,positionCheckY,<,{r * 8 + 8}')]
    at = lambda tx, ty: f'nx{tx}&ty{ty}a&ty{ty}b'
    letter_art = {}
    def art_index(key, make):
        if key not in letter_art:
            a = make()
            letter_art[key] = add_cell(a) if a[..., 3].max() >= 8 else None
        return letter_art[key]
    def drawn_mask(c, tx, ty):
        if c == red[(tx, ty)][0]: return np.ones((C, C))
        drawn = ((pixels(c) != pixels(blank[(tx, ty)])) * 255).astype(np.uint8)
        mm = Image.fromarray(drawn).resize((C, C), Image.NEAREST).filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.GaussianBlur(4))
        return np.asarray(mm).astype(float) / 255
    for (c, pal), pos in keys.items():
        look = look_of(pal)
        for lk, k, br, cn, pn in phases:
            if lk != look: continue
            pk = step(pal, k)
            plain.append(f'[{cn}]<tile>{n_img},{c.hex().upper()},{pk.hex().upper()},0,0,1,N')
            tile = lambda i: f'<tile>{n_img},{c.hex().upper()},{pk.hex().upper()},{(i % 32) * C},{(i // 32) * C},{br:g},N'
            for (tx, ty) in sorted(pos):
                if (tx, ty) not in blank: continue
                mine = (tx, ty) in cell_id and c != blank[(tx, ty)]
                def own():
                    if not mine: return np.zeros((C, C, 4))
                    a = part([(tx, ty)], tx, ty); a[..., 3] *= drawn_mask(c, tx, ty); return a
                i = art_index(('own', c, tx, ty), own) if mine else None
                if i is not None: gated.append(f'[{cn}&{at(tx, ty)}]' + tile(i))
                # neighbouring letters reaching into this cell: the game completes them
                # one after another, so one entry per prefix of that order, each gated
                # on those neighbours being complete (later lines are checked first)
                nb = [(tx + dx, ty + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                      if (dx or dy) and (tx + dx, ty + dy) in cell_id]
                nb = sorted((q for q in nb if part([q], tx, ty)[..., 3].max() >= 8), key=lambda q: final_at.get(q, 1 << 30))
                for n_ in range(1, len(nb) + 1):
                    pre = tuple(nb[:n_])
                    def both(pre=pre):
                        a, b = own(), part(list(pre), tx, ty)
                        al = a[..., 3:] / 255; bl = b[..., 3:] / 255
                        out = np.zeros_like(a); out[..., 3:] = 255 * (al + bl * (1 - al))
                        out[..., :3] = (a[..., :3] * al + b[..., :3] * bl * (1 - al)) / np.maximum(al + bl * (1 - al), 1e-6)
                        return out
                    j = art_index(('nb', c, tx, ty, pre), both)
                    if j is None: continue
                    names = []
                    for (lx, ly) in pre:
                        lc = red[(lx, ly)][0]; lpal = (red if look == 'sunset' else blue)[(lx, ly)][1]
                        lpk = step(lpal, k)
                        nm = f'lt{lx}_{ly}_{lx - tx}_{ly - ty}_{look}{k}'
                        nbc[nm] = f'<condition>{nm},tileNearby,{(lx - tx) * 8},{(ly - ty) * 8},{lc.hex().upper()},{lpk.hex().upper()}'
                        names.append(nm)
                    gated.append(f'[{cn}&{at(tx, ty)}&{"&".join(names)}]' + tile(j))
    nrow = (len(atlas) + 31) // 32
    A = np.zeros((nrow * C, 32 * C, 4))
    for i, a in enumerate(atlas): A[(i // 32) * C:(i // 32 + 1) * C, (i % 32) * C:(i % 32 + 1) * C] = a
    A[0:C, 0:C, 3] = 1
    save(A, 'cells.png')

    head = [l for l in lines if l.startswith(('<ver>', '<scale>', '<options>'))]
    imgl = [l for l in lines if l.startswith('<img>')] + ['<img>title/cells.png']
    rest = [l for l in lines if not l.startswith(('<ver>', '<scale>', '<options>', '<img>'))]
    # title entries first among the tiles: they only match the title's own tiles + colours;
    # gated (letters) after plain so they are checked first (later lines win)
    out = (head + imgl + ['# HD title screen (the owner\'s layers)'] + conds + cols + rows + list(nbc.values())
           + bgs + plain + gated + rest)
    open(hires, 'w').write('\n'.join(out) + '\n')
    print(f'  title: {len(bgs)} layer entries, {len(plain)} cell keys, {len(gated)} letter entries, '
          f'{len(atlas)} letter cells -> {hires}')

if __name__ == '__main__':
    main()
