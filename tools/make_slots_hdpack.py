"""Add the Endor casino's slot machine to an HD pack directory.

From tools/capture_slots.py (CAPTURE/slots.json, screen.mem):

  machine  the owner's painting hd/casino/slots/SLOT.png (1280 x 1200, the
           screen at 5x; tools/export_casino.py) is drawn as a still
           <background> while the slot screen shows (read from the JACKPOT
           sign's tile and colours, tileAtPosition, with the screen-fade
           steps). Every background tile of the machine then gets an almost
           transparent HD tile so the painting shows through; the text and
           its window keep the text pack's tiles.
           hd/casino/slots/layout.json maps the painting onto the game's
           layout (straight-line maps of x and y through the reel windows,
           lamps, coin box, pay table and text window), since a generated
           painting need not keep the screen's proportions exactly.
  symbols  each of the seven reel symbols is a 16 x 16 group of sprites; its
           four sprite tiles draw the four quarters of the painted symbol, cut
           out of the painting's own pay table (layout.json "symbols": a box
           per symbol name) so the reels match the pay table, and fitted to
           the 8-bit symbol's size. Without those boxes the sheet
           hd/casino/slots/SYMBOLS.png is used (found by outline).
  the rest the payline lamps, the coin counter's digits and other sprites,
           smoothly upscaled from the game's tiles (tools/smooth_pixels.py).

Without the art the machine stays as it is and only the smoothed sprites are
added.

usage: make_slots_hdpack.py CAPTURE OUTDIR
"""
import json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from field_sheet import NES
from make_casino_hdpack import smooth_tile, fade, dark, lum, rgb
from export_casino import sym_origin, SK, symbol_image, symbol_name

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(HERE, 'hd', 'casino', 'slots')
S = 10; C = 8 * S
STEPS = ('0', '1', '2', '3', '1b', '2b', '3b')

def step(pal, k):
    n = int(k[0]); p = fade(pal, n) if n else pal
    return bytes([0x0F]) + p[1:] if k.endswith('b') else p

def sprite_step(pal_ff, k):
    """'FF' + 3 colours, faded like the screen (the 'b' steps only change the backdrop)."""
    n = int(k[0]); cols = bytes.fromhex(pal_ff)[1:]
    return 'ff' + (fade(cols, n) if n else cols).hex()

def text_cells(cap):
    """The cells whose tile changes during play: the text window's inside."""
    return [tuple(map(int, k.split(','))) for k, v in cap['cells'].items() if len(v) > 1]

def blank_text_window(im, cap, backdrop, k):
    """Paint the text window's inside in the backdrop colour (k = scale): the
    game writes its text there and the text tiles are partly transparent, so
    any text in the painting would show through them."""
    cells = text_cells(cap)
    if not cells: return
    x0 = min(x for x, y in cells) - 1; x1 = max(x for x, y in cells) + 2          # the margin columns too
    y0 = min(y for x, y in cells); y1 = max(y for x, y in cells) + 1
    v = NES[backdrop & 0x3F]
    im.paste(((v >> 16) & 255, (v >> 8) & 255, v & 255), (x0 * 8 * k, y0 * 8 * k, x1 * 8 * k, y1 * 8 * k))

def warp_machine(im, lay):
    """The painting resampled onto the game's layout (layout.json "warp")."""
    from scipy import ndimage
    w = lay.get('warp')
    if not w: return im
    W, H = im.size
    mx = np.interp(np.arange(W), w['x_game'], w['x_paint']); my = np.interp(np.arange(H), w['y_game'], w['y_paint'])
    yy, xx = np.meshgrid(my, mx, indexing='ij'); a = np.asarray(im).astype(float)
    out = np.stack([ndimage.map_coordinates(a[..., c], [yy, xx], order=3, mode='nearest') for c in range(3)], -1)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))

def paytable_symbol(paint, box, parchment=(235, 215, 170)):
    """A pay-table symbol cut out of the painting: RGBA, the parchment made transparent."""
    from scipy import ndimage
    x0, y0, x1, y1 = box; pad = 4
    a = np.asarray(paint.convert('RGB').crop((x0 - pad, y0 - pad, x1 + pad, y1 + pad))).astype(float)
    d = np.sqrt(((a - np.array(parchment)) ** 2).sum(-1))
    hard = ndimage.binary_fill_holes(ndimage.binary_closing(d > 70, iterations=2))
    lab, n = ndimage.label(hard)
    if n > 1:                                        # keep the symbol, not bits of its neighbours
        sz = ndimage.sum(hard, lab, range(1, n + 1)); hard = lab == (np.argmax(sz) + 1)
    soft = np.clip((d - 40) / 50, 0, 1)
    alpha = np.where(ndimage.binary_erosion(hard, iterations=1), 1.0, soft * ndimage.binary_dilation(hard, iterations=1))
    rgba = np.dstack([a, alpha * 255]).astype(np.uint8)
    im = Image.fromarray(rgba, 'RGBA'); bb = im.getbbox()
    return im.crop(bb) if bb else im

def fit_symbol(cut, chs, pal):
    """The cut-out symbol scaled into a 160 x 160 cell over the 8-bit symbol's own extent."""
    ref = np.asarray(symbol_image(chs, pal, k=1))[..., 3] > 0
    ry, rx = np.nonzero(ref)
    if not ry.size: ry, rx = np.array([0, 15]), np.array([0, 15])
    bx0, by0, bx1, by1 = rx.min() * S, ry.min() * S, (rx.max() + 1) * S, (ry.max() + 1) * S
    f = min((bx1 - bx0) / cut.width, (by1 - by0) / cut.height)
    w, h = max(1, round(cut.width * f)), max(1, round(cut.height * f))
    big = cut.resize((w * 2, h * 2), Image.LANCZOS).resize((w, h), Image.LANCZOS)
    from PIL import ImageFilter
    big = big.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
    cell = Image.new('RGBA', (2 * C, 2 * C), (0, 0, 0, 0))
    cell.alpha_composite(big, (round((bx0 + bx1 - w) / 2), round((by0 + by1 - h) / 2)))
    return cell

def symbol_art(sheet, i, chs, pal):
    """The painted symbol i as 160 x 160, registered on the 8-bit symbol's outline."""
    x0, y0 = sym_origin(i); box = 16 * SK
    ref = np.asarray(symbol_image(chs, pal))[..., 3] > 0
    ry, rx = np.nonzero(ref)
    a = np.asarray(sheet)[..., 3]
    pad = 40
    sub = a[max(y0 - pad, 0):y0 + box + pad, max(x0 - pad, 0):x0 + box + pad] > 64
    sy, sx = np.nonzero(sub)
    dx = dy = 0
    if sy.size and ry.size:
        dx = int(round((sx.min() + sx.max()) / 2 - pad - (rx.min() + rx.max()) / 2))
        dy = int(round((sy.min() + sy.max()) / 2 - pad - (ry.min() + ry.max()) / 2))
    return sheet.crop((x0 + dx, y0 + dy, x0 + dx + box, y0 + dy + box)).resize((2 * C, 2 * C), Image.LANCZOS)

def main():
    cap_dir, outdir = sys.argv[1], sys.argv[2]
    cap_p = os.path.join(cap_dir, 'slots.json')
    if not os.path.exists(cap_p): print('  slots: no capture'); return
    cap = json.load(open(cap_p)); scr = load(os.path.join(cap_dir, 'screen.mem'))
    hires = os.path.join(outdir, 'hires.txt'); lines = open(hires).read().splitlines()
    n_img = sum(1 for l in lines if l.startswith('<img>'))
    have_chr = {l.split(',')[1].lower() for l in lines if l.startswith('<tile>') and l.rstrip().endswith(',Y')}
    os.makedirs(os.path.join(outdir, 'casino'), exist_ok=True)
    atlas, entries, conds, bgs, imgs = [], [], [], [], []
    def add(img):
        atlas.append(img); i = len(atlas) - 1; return (i % 16) * C, (i // 16) * C

    # the slot screen, from the JACKPOT sign's tile (8, 2)
    ci, ch, pal = scr['ciram'], scr['chr_ram'], scr['palette']
    tx, ty = 8, 2; t = ci[ty * 32 + tx]; at = ci[0x3C0 + (ty // 4) * 8 + tx // 4]
    p = (at >> (((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2)) & 3
    jc = bytes(ch[0x1000 + 16 * t:0x1000 + 16 * t + 16]); jp = bytes([pal[0], pal[4 * p + 1], pal[4 * p + 2], pal[4 * p + 3]])
    phases = []
    for k in STEPS:
        pk = step(jp, k)
        if k != '0' and dark(pk): continue
        br = 1.0 if k == '0' else round(min(1.0, lum(pk) / max(lum(jp), 1)), 3)
        conds.append(f'<condition>slot{k},tileAtPosition,{tx * 8},{ty * 8},{jc.hex().upper()},{pk.hex().upper()}')
        phases.append((k, br, f'slot{k}'))

    lay_p = os.path.join(ART, 'layout.json')
    lay = json.load(open(lay_p)) if os.path.exists(lay_p) else {}
    machine = os.path.join(ART, 'SLOT.png')
    if os.path.exists(machine):
        im = warp_machine(Image.open(machine).convert('RGB').resize((1280, 1200), Image.LANCZOS), lay)
        im = im.resize((256 * S, 240 * S), Image.LANCZOS)
        blank_text_window(im, cap, scr['palette'][0], S)
        im.save(os.path.join(outdir, 'casino', 'slot_machine.png'), optimize=True)
        for k, br, cn in phases:
            bgs.append(f'[{cn}]<background>casino/slot_machine.png,{br:g},0,0,1,0,0')
        clear = add(Image.new('RGBA', (C, C), (0, 0, 0, 1)))
        keys = {tuple(v) for vs in cap['cells'].values() for v in vs}
        for chx, palx in sorted(keys):
            if chx in have_chr or not any(bytes.fromhex(chx)): continue      # text/window tiles stay; blank = backdrop
            base = bytes.fromhex(palx)
            for k, br, cn in phases:
                entries.append(f'[{cn}]<tile>{n_img},{chx.upper()},{step(base, k).hex().upper()},{clear[0]},{clear[1]},1,N')

    # sprites: reel symbols from the owner's sheet, the rest smoothed
    sym_tiles = {}
    sheet_p = os.path.join(ART, 'SYMBOLS.png')
    if lay.get('symbols') and os.path.exists(machine):
        paint = Image.open(machine).convert('RGB').resize((1280, 1200), Image.LANCZOS)
        for i, (chs, spal) in enumerate(cap['symbols']):
            box = lay['symbols'].get(symbol_name(chs, i))
            if not box: print(f'  slots: no pay-table box for {symbol_name(chs, i)}'); continue
            art = fit_symbol(paytable_symbol(paint, box), chs, spal)
            for q, c in enumerate(chs):
                if any(bytes.fromhex(c)): sym_tiles[(c, spal)] = art.crop(((q % 2) * C, (q // 2) * C, (q % 2 + 1) * C, (q // 2 + 1) * C))
    elif os.path.exists(sheet_p):
        sheet = Image.open(sheet_p).convert('RGBA')
        if sheet.size != (1536, 1024): sheet = sheet.resize((1536, 1024), Image.LANCZOS)
        for i, (chs, spal) in enumerate(cap['symbols']):
            art = symbol_art(sheet, i, chs, spal)
            for q, c in enumerate(chs):
                if any(bytes.fromhex(c)): sym_tiles[(c, spal)] = art.crop(((q % 2) * C, (q // 2) * C, (q % 2 + 1) * C, (q // 2 + 1) * C))
    n_sym = n_smooth = 0
    for c, spal in cap['sprites']:
        if (c, spal) in sym_tiles: x, y = add(sym_tiles[(c, spal)]); n_sym += 1
        else: x, y = add(smooth_tile(c, '00' + spal[2:])); n_smooth += 1
        done = set()
        for k, br, cn in phases:
            pk = sprite_step(spal, k)
            if pk in done or (k != '0' and all((v & 0x0F) >= 0x0D or v == 0x0F for v in bytes.fromhex(pk)[1:])): continue
            done.add(pk)
            sbr = 1.0 if k[0] == '0' else round(min(1.0, lum(bytes.fromhex(pk)) / max(lum(bytes.fromhex(spal)), 1)), 3)
            entries.append(f'<tile>{n_img},{c.upper()},{pk.upper()},{x},{y},{sbr:g},N')

    rows = (len(atlas) + 15) // 16
    sheet_img = Image.new('RGBA', (16 * C, max(rows, 1) * C), (0, 0, 0, 0))
    for i, im in enumerate(atlas): sheet_img.alpha_composite(im.convert('RGBA'), ((i % 16) * C, (i // 16) * C))
    sheet_img.save(os.path.join(outdir, 'casino', 'slots.png'), optimize=True)
    head = [l for l in lines if l.startswith(('<ver>', '<scale>', '<options>'))]
    imgl = [l for l in lines if l.startswith('<img>')] + ['<img>casino/slots.png']
    rest = [l for l in lines if not l.startswith(('<ver>', '<scale>', '<options>', '<img>'))]
    open(hires, 'w').write('\n'.join(head + imgl + ['# Endor casino: slot machine'] + conds + bgs + entries + rest) + '\n')
    print(f'  slots: machine {"painted" if bgs else "as is"}, {n_sym} symbol tiles from art, {n_smooth} sprite tiles smoothed -> {hires}')

if __name__ == '__main__':
    main()
