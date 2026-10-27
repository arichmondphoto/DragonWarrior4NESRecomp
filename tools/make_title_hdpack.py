"""Add the owner's HD title screen (hd/title/TITLE.png, 1280x1200, made from
tools/export_gaps.py) to an HD pack directory.

The title is one screen (nametable 0, pattern table $1000): the castle on a
sea of clouds under a blue sky, a stone plate on which "DRAGON WARRIOR" is
typed letter by letter, then "IV" and the sky turns to sunset
(tools/capture_extras.py: frame 1200 = blue, 2400 = red, finished). The cloud
rows scroll sideways at different speeds (they wrap within the one table).

Every 8x8 cell of the finished screen is keyed by its CHR bytes + palette and
gated on its nametable column (nametableColumn, patch 0010; it follows the
scrolling clouds) and screen row, so repeated tiles (sky, clouds, plate
speckle) each draw their own part of the picture. The use whose art is the
most typical of the tile is also its plain default, so a plate cell still
blank while the letters are typed draws blank plate.

The blue phase uses the same tiles in other colours: the picture is
recoloured per sub-palette by moving each pixel by the colour change of the
NES colours it is closest to (soft weights), so the plate (same colours)
stays and the sunset sky turns to day. Cells seen only during the intro
(title_seq.json) get their own entries: a half-typed letter shows the
finished letter's art where the NES letter is already drawn (blank plate
elsewhere), and the plate before it fades in shows sky (inpainted). The
finished screen also gets the screen-fade steps.

usage: make_title_hdpack.py EXTRA_CAPTURE OUTDIR
"""
import collections, json, os, sys
import numpy as np
from PIL import Image, ImageFilter
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from field_sheet import NES

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = 10
C = 8 * S

def rgb(c): v = NES[c & 0x3F]; return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], float)
def fade(pal, k): return bytes(0x0F if (c & 0x3F) < 0x10 * k or (c & 0x0F) >= 0x0D else c - 0x10 * k for c in pal)
def lum(pal): return sum(rgb(x) @ (0.299, 0.587, 0.114) for x in pal[1:])

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
    """Move each pixel by the colour change of the source colours it is near."""
    X = np.array([rgb(c) for c in src]); D = np.array([rgb(b) - rgb(a) for a, b in zip(src, dst)])
    d2 = ((img[..., None, :] - X[None, None]) ** 2).sum(-1)
    w = np.exp(-(d2 - d2.min(-1, keepdims=True)) / (2 * sigma * sigma)); w /= w.sum(-1, keepdims=True)
    return img + w @ D

def cell(a, tx, ty): return a[ty * C:(ty + 1) * C, tx * C:(tx + 1) * C]

def main():
    cap, outdir = sys.argv[1], sys.argv[2]
    src = os.path.join(HERE, 'hd', 'title', 'TITLE.png')
    if not os.path.exists(src): print('  title: no art'); return
    red, blue = cells(os.path.join(cap, 'title_2400.mem')), cells(os.path.join(cap, 'title_1200.mem'))
    art = Image.open(src).convert('RGB').resize((256 * S, 240 * S), Image.LANCZOS)
    a0 = np.asarray(art).astype(float)
    # the cloud rows below y=196 scroll and wrap round: blend the picture's left and
    # right edges there into a half-turned copy so the wrap has no seam
    y0s, W = 196 * S, 48 * S
    band = a0[y0s:]; turned = np.roll(band, 128 * S, axis=1)
    x = np.arange(256 * S); m = np.clip(np.minimum(x, 256 * S - 1 - x) / W, 0, 1)[None, :, None]
    a0[y0s:] = band * m + turned * (1 - m)
    art = Image.fromarray(np.clip(np.round(a0), 0, 255).astype(np.uint8))

    # blue phase: recolour each sub-palette's cells from its red to its blue colours
    pals = {}
    for k, (c, pr, p) in red.items(): pals.setdefault(p, (pr, blue[k][1]))
    # the painted plate spills a little past the NES plate (into sky / castle-palette
    # cells): its grey stone there keeps its colour
    pc = [(tx, ty) for (tx, ty), (c, pr, p) in red.items() if p == 3 and pixels(c).any()]
    x0, x1 = min(t[0] for t in pc) - 1, max(t[0] for t in pc) + 1
    y0, y1 = min(t[1] for t in pc) - 1, max(t[1] for t in pc) + 1
    blue_img = a0.copy()
    for (tx, ty), (c, pr, p) in red.items():
        pr, pb = pals[p]
        src = cell(a0, tx, ty); new = recolour(src, pr, pb)
        if x0 <= tx <= x1 and y0 <= ty <= y1 and p != 3:
            sky_px = np.kron(pixels(c) == 0, np.ones((S, S), bool))
            grey = ((src.max(-1) - src.min(-1) < 40) & sky_px)[..., None]
            new = np.where(grey, src, new)
        cell(blue_img, tx, ty)[:] = new
    blue_img = np.clip(np.round(blue_img), 0, 255).astype(np.uint8)

    # cells the finished screen doesn't have (typing, plate fade-in)
    seq = json.load(open(os.path.join(cap, 'title_seq.json'))) if os.path.exists(os.path.join(cap, 'title_seq.json')) else {'blank': {}, 'states': []}
    red_pals = {v[1] for v in red.values()}
    extra = []
    for tx, ty, ch, pal in seq['states']:
        ch, pal = bytes.fromhex(ch), bytes.fromhex(pal)
        if ch == red[(tx, ty)][0] and pal in (red[(tx, ty)][1], blue[(tx, ty)][1]) and blue[(tx, ty)][0] == ch: continue   # phase entries
        extra.append((tx, ty, ch, pal))

    # plain default per key: the use whose art is closest to the median of all its uses
    def plain_pos(img, pos):
        if len(pos) == 1: return pos[0]
        stack = np.stack([cell(img, tx, ty)[::4, ::4] for tx, ty in pos]); med = np.median(stack, 0)
        return pos[int(np.argmin(((stack - med) ** 2).mean((1, 2, 3))))]

    # sky behind the plate (the plate is drawn in the backdrop colour before it
    # fades in): the sky rows above it, mirrored down over its rows
    sky = blue_img.astype(float).copy()
    above = list(range(y0 * C)) or [0]
    for y in range(y0 * C, (y1 + 1) * C):
        k = y - y0 * C; n = len(above); m = k % (2 * n)
        sky[y] = blue_img[above[n - 1 - m] if m < n else above[m - n]]
    os.makedirs(os.path.join(outdir, 'title'), exist_ok=True)
    art.save(os.path.join(outdir, 'title', 'title_red.png'), optimize=True)
    Image.fromarray(blue_img).save(os.path.join(outdir, 'title', 'title_blue.png'), optimize=True)

    hires = os.path.join(outdir, 'hires.txt'); lines = open(hires).read().splitlines()
    n_img = sum(1 for l in lines if l.startswith('<img>'))
    imgs = ['title/title_red.png', 'title/title_blue.png']
    img_of = {'red': n_img, 'blue': n_img + 1}
    conds = []
    for c in range(32):
        conds += [f'<condition>nx{c},nametableColumn,==,{c}']
    for r in range(30):
        conds += [f'<condition>ty{r}a,positionCheckY,>=,{r * 8}', f'<condition>ty{r}b,positionCheckY,<,{r * 8 + 8}']
    gate = lambda tx, ty: f'[nx{tx}&ty{ty}a&ty{ty}b]'
    plain, gated = [], []
    defaults = {}
    # under the blue sky the letters are typed one by one: a blank plate cell next
    # to a letter would show the painted letter's edge before the letter is there,
    # so its own art is gated on the neighbouring letters being drawn (tileNearby);
    # until then it draws the tile's plain (typical) art
    blank_of = {tuple(map(int, k.split(','))): bytes.fromhex(v) for k, v in seq['blank'].items()}
    letters = {k for k in red if k in blank_of and red[k][0] != blank_of[k]}
    def waits_for(tx, ty, c):
        if blank_of.get((tx, ty)) != c: return []
        return [(tx + dx, ty + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx or dy) and (tx + dx, ty + dy) in letters]
    nb_conds = {}
    for phase, cl, img in (('red', red, a0), ('blue', blue, blue_img)):
        uses = collections.OrderedDict()
        for (tx, ty), (c, pal, p) in sorted(cl.items(), key=lambda kv: (kv[0][1], kv[0][0])):
            if phase == 'blue' and red[(tx, ty)][0] != c: continue     # only cells drawn like the final screen
            uses.setdefault((c, pal), []).append((tx, ty))
        for (c, pal), pos in uses.items():
            dflt = plain_pos(img, pos); defaults[(c, pal)] = (phase, dflt)
            for k in (0, 1, 2, 3) if phase == 'red' else (0,):
                pk = fade(pal, k) if k else pal
                if k and all((x & 0x0F) >= 0x0D or x == 0x0F for x in pk): continue
                br = 1.0 if not k else round(min(1.0, lum(pk) / (lum(pal) or 1)), 3)
                for tx, ty in pos:
                    entry = f'<tile>{img_of[phase]},{c.hex().upper()},{pk.hex().upper()},{tx * C},{ty * C},{br:g},N'
                    if (tx, ty) == dflt: plain.append(entry)
                    w = waits_for(tx, ty, c) if phase == 'blue' else []
                    if w:
                        names = []
                        for (lx, ly) in w:
                            name = f'lt{lx}_{ly}_{lx - tx}_{ly - ty}'
                            nb_conds[name] = (f'<condition>{name},tileNearby,{(lx - tx) * 8},{(ly - ty) * 8},'
                                              f'{red[(lx, ly)][0].hex().upper()},{blue[(lx, ly)][1].hex().upper()}')
                            names.append(name)
                        gated.append(gate(tx, ty)[:-1] + '&' + '&'.join(names) + ']' + entry)
                    elif len(pos) > 1: gated.append(gate(tx, ty) + entry)

    # intro-only cells: one atlas of composed 80x80 cells
    atlas_cells, seen = [], {}
    for tx, ty, ch, pal in extra:
        phase_img = a0 if pal in red_pals else blue_img
        if len(set(pal)) == 1:                       # plate not shown yet: sky
            pic = cell(sky, tx, ty)
        else:
            blank = bytes.fromhex(seq['blank'].get(f'{tx},{ty}', ''))
            final = red[(tx, ty)][0]
            dk = defaults.get((blank, pal)) or defaults.get((blank, red[(tx, ty)][1]))
            base = cell(a0 if dk is None or dk[0] == 'red' else blue_img, *(dk[1] if dk else (tx, ty)))
            if dk and dk[0] == 'red' and phase_img is blue_img: base = recolour(base, *pals[3])
            if ch == blank or not blank:
                pic = base
            else:
                drawn = (pixels(ch) != pixels(blank)).astype(np.uint8) * 255
                done = (pixels(final) != pixels(blank)).astype(np.uint8) * 255
                m = Image.fromarray(drawn).resize((C, C), Image.NEAREST).filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.GaussianBlur(4))
                m = np.asarray(m).astype(float)[..., None] / 255
                if not done.any(): m = m * 0                 # nothing of the final letter here
                pic = cell(phase_img, tx, ty) * m + base * (1 - m)
        key = (ch, pal, tx, ty)
        if key in seen: continue
        seen[key] = len(atlas_cells); atlas_cells.append(np.clip(np.round(pic), 0, 255).astype(np.uint8))
        entry_at = seen[key]
        ax, ay = (entry_at % 32) * C, (entry_at // 32) * C
        gated.append(gate(tx, ty) + f'<tile>{n_img + 2},{ch.hex().upper()},{pal.hex().upper()},{ax},{ay},1,N')
    if atlas_cells:
        rows = (len(atlas_cells) + 31) // 32
        at = np.zeros((rows * C, 32 * C, 3), np.uint8)
        for i, a in enumerate(atlas_cells): at[(i // 32) * C:(i // 32 + 1) * C, (i % 32) * C:(i % 32 + 1) * C] = a
        Image.fromarray(at).save(os.path.join(outdir, 'title', 'title_intro.png'), optimize=True)
        imgs.append('title/title_intro.png')
    lines += ['<img>' + i for i in imgs]

    head = [l for l in lines if l.startswith(('<ver>', '<scale>', '<options>'))]
    imgl = [l for l in lines if l.startswith('<img>')]
    rest = [l for l in lines if not l.startswith(('<ver>', '<scale>', '<options>', '<img>'))]
    # title entries go first among the tiles: they only match the title's own tiles + colours
    out = head + imgl + ['# HD title screen (the owner\'s art, per screen cell)'] + conds + list(nb_conds.values()) + plain + gated + rest
    open(hires, 'w').write('\n'.join(out) + '\n')
    print(f'  title: {len(plain)} tiles, {len(gated)} gated entries ({len(atlas_cells)} intro cells) -> {hires}')

if __name__ == '__main__':
    main()
