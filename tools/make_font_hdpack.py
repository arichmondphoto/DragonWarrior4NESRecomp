"""Build an HD pack that replaces Dragon Warrior IV's dialog font.

Tile data (the 16 CHR bytes that identify each glyph) is read from a VRAM dump
of the running game, so the pack carries no ROM-derived artwork: every HD
glyph is rendered here from an open-licensed font.

usage: make_font_hdpack.py DUMP OUTDIR [--font PATH] [--scale 4] [--preview PNG]
"""
import argparse, os, sys
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load

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
    0x170: '*', 0x171: ':', 0x172: '…',
    0x177: ',', 0x178: '.',
})
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

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('dump'); ap.add_argument('outdir')
    ap.add_argument('--font', default='/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf')
    ap.add_argument('--scale', type=int, default=4)
    ap.add_argument('--preview')
    a = ap.parse_args()
    S = 8 * a.scale
    m = load(a.dump); chr_ram, pal = m['chr_ram'], m['palette']
    font = ImageFont.truetype(a.font, 32)
    sx = width_factor(font, S)
    tiles = sorted(GLYPHS)
    cols = 16; rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new('RGBA', (cols * S, rows * S), (0, 0, 0, 0))
    lines = ['<ver>106', f'<scale>{a.scale}', '<img>font.png',
             '# Dialog font: CHR-RAM glyphs keyed by tile content; default=Y matches any palette.']
    bg_pal = '%02X%02X%02X%02X' % (pal[0], pal[1], pal[2], pal[3])
    seen = set()
    for i, t in enumerate(tiles):
        data = bytes(chr_ram[16 * t:16 * t + 16])
        if data in seen or not any(data): continue
        seen.add(data)
        x, y = (i % cols) * S, (i // cols) * S
        sheet.alpha_composite(render_glyph(font, GLYPHS[t], S, t, sx), (x, y))
        lines.append(f'<tile>0,{data.hex().upper()},{bg_pal},{x},{y},1,Y')
    os.makedirs(a.outdir, exist_ok=True)
    sheet.save(os.path.join(a.outdir, 'font.png'))
    open(os.path.join(a.outdir, 'hires.txt'), 'w').write('\n'.join(lines) + '\n')
    print(f'{len(seen)} glyphs -> {a.outdir}/hires.txt, font.png ({sheet.size[0]}x{sheet.size[1]})')
    if a.preview:
        text = ['This is a story about', 'royal soldiers of a', "small country called", 'Burland.  “The King’s', 'orders!”  HP: 27 ...?']
        inv = {v: k for k, v in GLYPHS.items()}
        pv = Image.new('RGBA', (24 * S, len(text) * 2 * S), (0, 0, 0, 255))
        for r, ln in enumerate(text):
            for c, ch in enumerate(ln.replace('...', '…')):
                if ch == ' ' or ch not in inv: continue
                pv.alpha_composite(render_glyph(font, ch, S, inv[ch], sx), (c * S, r * 2 * S))
        pv.save(a.preview)

if __name__ == '__main__':
    main()
