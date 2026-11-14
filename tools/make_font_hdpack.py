"""Build an HD pack for Dragon Warrior IV's text: the font, window borders,
cursors and arrows.

Tiles are identified by the 16 CHR bytes the game writes to CHR RAM, read
from a VRAM dump of the running game (tools/vramdump.py).

Styles:
  smooth (default)  each original 8x8 tile is upscaled into smooth outlines
                    (tools/smooth_pixels.py), keeping the game's own letter
                    shapes. The pack is generated from the player's ROM at
                    build time and is not stored in the repository.
  font              glyphs re-rendered from a TrueType/OpenType font (--font);
                    window pieces are still smoothed from the original tiles.

Other text screens (the copyright screen and "PRESENTED BY" at power-on use
their own lettering in the same tile numbers): --screen DUMP adds every
non-blank background tile shown in that dump, smoothed, keyed by its shapes;
--sprites DUMP does the same for the sprites shown (pattern table $1000, as
the ENIX logo on the "PRESENTED BY" screen uses: its letter "e" is drawn in
by a sprite animation, so pass one dump per animation step).

usage: make_font_hdpack.py DUMP OUTDIR [--style smooth|font] [--font PATH]
                           [--roundness 0.9] [--scale 10] [--preview PNG]
                           [--screen DUMP ...] [--sprites DUMP ...]
"""
import argparse, os, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load, tile_pixels
from field_sheet import NES
from smooth_pixels import smooth_mask, smooth_cell

# CHR-RAM tile ($1xxx pattern table) -> character, verified against the
# name-entry grid and enlarged tile sheets.
GLYPHS = {}
for i, ch in enumerate('0123456789'): GLYPHS[0x101 + i] = ch
for i, ch in enumerate('abcdefghijklmnopqrstuvwxyz'): GLYPHS[0x10B + i] = ch
for i, ch in enumerate('ABCDEFGHIJKLMNOPQRSTUVWXYZ'): GLYPHS[0x125 + i] = ch
GLYPHS.update({
    0x165: '—',  # long dash
    0x166: '“', 0x167: '”',            # double quotes
    0x168: '‘', 0x169: '‘',            # opening single quotes (two placements)
    0x16A: '’', 0x16B: '’',            # apostrophe / closing quote
    0x16C: '.’',                            # period + closing quote in one cell
    0x16D: '?', 0x16E: '!', 0x16F: '-',
    0x175: '(', 0x176: ')',            # name-entry screen
    0x170: '*', 0x171: ':', 0x172: '…',
    0x177: ',', 0x178: '.',
})
# Window and cursor tiles. 'edge' pieces are lines that continue into the
# neighbouring tile, so they are smoothed with edge-extended context.
UI_TILES = {
    0x180: ('continue arrow', 'zero'), 0x181: ('cursor', 'zero'),
    0x182: ('arrow', 'zero'),          0x183: ('left border + equipped E', 'edge'),
    0x184: ('left border', 'edge'),    0x185: ('top border', 'edge'),
    0x186: ('top-left corner', 'edge'), 0x187: ('bottom-left corner', 'edge'),
    0x188: ('right border', 'edge'),   0x189: ('top-right corner', 'edge'),
    0x18A: ('bottom border', 'edge'),  0x18B: ('bottom-right corner', 'edge'),
    0x18C: ('top border before a title', 'edge'),
}

# Where each glyph sat inside the original 8x8 cell (single quotes 168/169 and
# 16A/16B differ only by horizontal placement).
X_BIAS = {0x168: +0.18, 0x169: -0.12, 0x16A: -0.18, 0x16B: +0.10}

def render_glyph(font, ch, S, tile, sx=1.0):
    """White glyph on transparent, S x S. Cap height and centring follow the
    original 7x7 glyph box; sx widens every glyph by the same factor so a
    monospaced font fills the game's fixed-width cells."""
    big = 4                                      # supersample for clean edges
    W = S * big
    canvas = Image.new('L', (W * 2, W), 0)
    d = ImageDraw.Draw(canvas)
    baseline = int(W * 6.85 / 8)                 # original glyphs end on row 6 of 8
    cap_target = W * 6.6 / 8
    f = font.font_variant(size=W)
    l, t, r, b = d.textbbox((0, 0), 'H', font=f, anchor='ls')
    f = font.font_variant(size=int(W * cap_target / (b - t)))
    l, t, r, b = d.textbbox((0, 0), ch, font=f, anchor='ls')
    d.text((W - (r - l) / 2 - l, baseline), ch, font=f, fill=255, anchor='ls')
    # Letters with descenders (g j p q y) would be clipped by the cell; like the
    # original 8x8 font, raise them so their tails end inside the cell.
    bb = canvas.getbbox()
    limit = int(W * 7.85 / 8)
    if bb and bb[3] > limit:
        shifted = Image.new('L', canvas.size, 0)
        shifted.paste(canvas, (0, limit - bb[3]))
        canvas = shifted
    gw = (r - l) * sx
    if gw > W * 0.9:                             # keep very wide glyphs inside the cell
        sx *= W * 0.9 / gw
    if sx != 1.0:
        canvas = canvas.resize((int(W * 2 * sx), W), Image.LANCZOS)
    im = Image.new('L', (W, W), 0)
    cx = W * 3.5 / 8 + X_BIAS.get(tile, 0) * W   # original glyphs are centred on column 3.5
    im.paste(canvas, (int(cx - canvas.width / 2), 0))
    a = im.resize((S, S), Image.LANCZOS)
    out = Image.new('RGBA', (S, S), (255, 255, 255, 0)); out.putalpha(a)
    return out

def width_factor(font, S):
    """Stretch so 'M' spans ~6.5/8 of the cell, like the original capitals."""
    W = S * 4
    d = ImageDraw.Draw(Image.new('L', (1, 1)))
    f = font.font_variant(size=W)
    l, t, r, b = d.textbbox((0, 0), 'H', font=f, anchor='ls')
    f = font.font_variant(size=int(W * (W * 6.6 / 8) / (b - t)))
    l, t, r, b = d.textbbox((0, 0), 'M', font=f, anchor='ls')
    return max(1.0, (W * 6.5 / 8) / (r - l))

def smooth_tile(chr_ram, t, S, roundness, mode):
    bits = [[1 if v == 1 else 0 for v in row] for row in tile_pixels(chr_ram, t)]
    m = smooth_mask(bits, S, roundness, mode=mode)
    out = Image.new('RGBA', (S, S), (255, 255, 255, 0)); out.putalpha(m)
    return out

def screen_cells(screens, sprite_dumps, S, roundness):
    """[(CHR data, exact key, any-palette key, art RGBA, white RGBA)] for every
    non-blank BG cell of the `screens` dumps (both nametables) and every
    sprite of the `sprite_dumps` (pattern table $1000), smoothed in context."""
    out, done = [], set()
    def rgb(c): v = NES[c & 0x3F]; return ((v >> 16) & 255, (v >> 8) & 255, v & 255)
    def cell_art(grid, x0, y0, cols):
        alpha, ci = smooth_cell(grid, x0, y0, S, roundness)
        cip = ci.load(); ap = alpha.load()
        counts = [0] * 4
        for yy in range(8):
            for xx in range(8): counts[grid[y0 + yy][x0 + xx] if 0 <= y0 + yy < len(grid) and 0 <= x0 + xx < 256 else 0] += 1
        main = max(range(1, 4), key=lambda k: counts[k])
        art = Image.new('RGBA', (S, S)); px = art.load()
        for yy in range(S):
            for xx in range(S):
                k = cip[xx, yy] or main
                px[xx, yy] = cols[k] + (ap[xx, yy],)
        white = Image.new('RGBA', (S, S), (255, 255, 255, 0)); white.putalpha(alpha)
        return art, white
    for sd in screens:
        m = load(sd); ch, ci, pal = m['chr_ram'], m['ciram'], m['palette']
        for nt in (0, 0x400):
            grid = [[0] * 256 for _ in range(240)]
            for r in range(30):
                for c in range(32):
                    px = tile_pixels(ch, 0x100 + ci[nt + r * 32 + c])
                    for yy in range(8): grid[r * 8 + yy][c * 8:c * 8 + 8] = px[yy]
            for r in range(30):
                for c in range(32):
                    t = 0x100 + ci[nt + r * 32 + c]; data = bytes(ch[16 * t:16 * t + 16])
                    if not any(data) or data in done: continue
                    done.add(data)
                    at = ci[nt + 0x3C0 + (r // 4) * 8 + c // 4]
                    sub = (at >> (((r % 4) // 2) * 4 + ((c % 4) // 2) * 2)) & 3
                    p = [pal[0]] + [pal[sub * 4 + k] for k in (1, 2, 3)]
                    art, white = cell_art(grid, c * 8, r * 8, [rgb(x) for x in p])
                    out.append((data, bytes(p).hex().upper(), '0F303030', art, white))
    # each sprite tile once: from the dump where its colours are brightest (not
    # mid-fade), the latest such (the logo is complete there: best context)
    best = {}
    for order, sd in enumerate(sprite_dumps):
        m = load(sd); ch, oam, pal = m['chr_ram'], m['oam'], m['palette']
        for k in range(0, 256, 4):
            y, t, at, x = oam[k:k + 4]
            if y >= 0xEF: continue
            data = bytes(ch[16 * (0x100 + t):16 * (0x100 + t) + 16])
            if not any(data): continue
            so = 0x10 + (at & 3) * 4
            lit = sum(c & 0x30 for c in pal[so + 1:so + 4] if (c & 0x0F) < 0x0D)
            if data not in best or (lit, order) >= best[data][:2]: best[data] = (lit, order, sd)
    grids = {}
    for data, (_, _, sd) in best.items():
        m = load(sd); ch, oam, pal = m['chr_ram'], m['oam'], m['palette']
        if sd not in grids:
            grid = [[0] * 256 for _ in range(240)]
            for k in range(252, -4, -4):                 # OAM order: lower entries on top
                y, t, at, x = oam[k:k + 4]
                if y >= 0xEF: continue
                px = tile_pixels(ch, 0x100 + t); hf, vf = at & 0x40, at & 0x80
                for yy in range(8):
                    for xx in range(8):
                        v = px[7 - yy if vf else yy][7 - xx if hf else xx]
                        if v and y + 1 + yy < 240 and x + xx < 256: grid[y + 1 + yy][x + xx] = v
            grids[sd] = grid
        for k in range(0, 256, 4):
            y, t, at, x = oam[k:k + 4]
            if y >= 0xEF or bytes(ch[16 * (0x100 + t):16 * (0x100 + t) + 16]) != data: continue
            so = 0x10 + (at & 3) * 4; p = [0] + [pal[so + j] for j in (1, 2, 3)]
            art, white = cell_art(grids[sd], x, y + 1, [(0, 0, 0)] + [rgb(c) for c in p[1:]])
            if at & 0x40: art, white = art.transpose(Image.FLIP_LEFT_RIGHT), white.transpose(Image.FLIP_LEFT_RIGHT)
            if at & 0x80: art, white = art.transpose(Image.FLIP_TOP_BOTTOM), white.transpose(Image.FLIP_TOP_BOTTOM)
            out.append((data, 'FF' + bytes(p[1:]).hex().upper(), 'FF303030', art, white))
            break
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('outdir')
    ap.add_argument('--style', choices=('smooth', 'font'), default='smooth')
    ap.add_argument('--font', default='/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf')
    ap.add_argument('--roundness', type=float, default=0.9)
    ap.add_argument('--scale', type=int, default=10)  # project standard: 10x
    ap.add_argument('--preview')
    ap.add_argument('--screen', action='append', default=[], help='a dump of another text screen (repeatable)')
    ap.add_argument('--sprites', action='append', default=[], help='a dump whose sprites to add (pattern table $1000; repeatable)')
    a = ap.parse_args()
    S = 8 * a.scale
    m = load(a.dump); chr_ram, pal = m['chr_ram'], m['palette']
    if a.style == 'font':
        font = ImageFont.truetype(a.font, 32); sx = width_factor(font, S)
    def art(t):
        if t in UI_TILES:
            return smooth_tile(chr_ram, t, S, a.roundness, UI_TILES[t][1])
        if a.style == 'smooth':
            return smooth_tile(chr_ram, t, S, a.roundness, 'zero')
        return render_glyph(font, GLYPHS[t], S, t, sx)
    tiles = sorted(GLYPHS) + sorted(UI_TILES)
    # other text screens: each cell smoothed with the whole screen as context
    # (their letters and the logo span several tiles), in its own colours
    extra = screen_cells(a.screen, a.sprites, S, a.roundness)
    cols = 16; rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGBA', (cols * S, rows * S), (0, 0, 0, 0))
    lines = ['<ver>106', f'<scale>{a.scale}', '<img>text.png',
             f'# Text, window borders and cursors ({a.style} style). CHR-RAM tiles keyed',
             '# by content; default=Y matches any palette.']
    bg_pal = '%02X%02X%02X%02X' % (pal[0], pal[1], pal[2], pal[3])
    seen = set(); n = 0
    for t in tiles:
        data = bytes(chr_ram[16 * t:16 * t + 16])
        if data in seen or not any(data): continue
        seen.add(data)
        x, y = (n % cols) * S, (n // cols) * S; n += 1
        sheet.alpha_composite(art(t), (x, y))
        lines.append(f'<tile>0,{data.hex().upper()},{bg_pal},{x},{y},1,Y')
    # each with two entries: its exact palette (art in the screen's colours)
    # and any palette (white art, tinted while drawing: fades)
    for data, key, any_key, art_rgba, white in extra:
        if (data, key[:2] == 'FF') in seen or (key[:2] != 'FF' and data in seen): continue
        seen.add((data, key[:2] == 'FF'))
        for im, k, d in ((art_rgba, key, 'N'), (white, any_key, 'Y')):
            if n >= cols * rows:                          # grow the sheet
                rows += 4; big = Image.new('RGBA', (cols * S, rows * S), (0, 0, 0, 0)); big.alpha_composite(sheet); sheet = big
            x, y = (n % cols) * S, (n // cols) * S; n += 1
            sheet.alpha_composite(im, (x, y))
            lines.append(f'<tile>0,{data.hex().upper()},{k},{x},{y},1,{d}')
    sheet = sheet.crop((0, 0, cols * S, ((n + cols - 1) // cols) * S))
    os.makedirs(a.outdir, exist_ok=True)
    for old in ('font.png',):
        if os.path.exists(os.path.join(a.outdir, old)): os.remove(os.path.join(a.outdir, old))
    sheet.save(os.path.join(a.outdir, 'text.png'))
    open(os.path.join(a.outdir, 'hires.txt'), 'w').write('\n'.join(lines) + '\n')
    print(f'{n} tiles ({a.style}) -> {a.outdir}/hires.txt, text.png ({sheet.size[0]}x{sheet.size[1]})')
    if a.preview:
        # A dialog window as the game draws it, for a quick look.
        inv = {v: k for k, v in GLYPHS.items()}
        text = ['\u2018You must have heard', ' the rumor that', ' children have been', ' vanishing recently.\u2019']
        cw = 24; chh = len(text) + 2
        pv = Image.new('RGBA', (cw * S, chh * S), (0, 0, 0, 255))
        def put(t, cx, cy): pv.alpha_composite(art(t), (cx * S, cy * S))
        put(0x186, 0, 0); put(0x189, cw - 1, 0); put(0x187, 0, chh - 1); put(0x18B, cw - 1, chh - 1)
        for cx in range(1, cw - 1): put(0x185, cx, 0); put(0x18A, cx, chh - 1)
        for cy in range(1, chh - 1): put(0x184, 0, cy); put(0x188, cw - 1, cy)
        for r, ln in enumerate(text):
            for c, ch in enumerate(ln):
                if ch in inv: put(inv[ch], 2 + c, 1 + r)
        put(0x181, 1, 1); put(0x180, cw // 2, chh - 1)
        pv.save(a.preview)

if __name__ == '__main__':
    main()
