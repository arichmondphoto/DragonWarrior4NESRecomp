"""Compose the Endor casino's 53 poker cards and the card back from one set of
painted parts, so every card matches the others.

The parts come from the owner's generated card sheets hd/casino/cards/C01-C09.png
(tools/export_casino.py layout) as chosen in hd/casino/cards/deck.json:

  blank   one card whose face (pips and ranks painted out) is the paper of
          every card
  pips    for each suit, one painted pip cut out of a chosen card (the pip
          nearest a point)
  aces    for each suit, the big picture of that suit's ace
  whole   cards used as painted (the joker and the card back)

and are laid out as the game lays out its own cards (from the capture,
tools/capture_casino.py): each 8-bit pip becomes a painted pip at the same
place, the ace's picture fills the ace's picture area, jacks, queens and kings
get their big letter in the suit's colour with a gold rim, and every card gets
its rank in green in the top-left corner and turned in the bottom-right one.
The letters are masks rendered once from a font (hd/casino/cards/glyphs.png,
tools/make_card_glyphs.py).

compose(cap, art_dir) -> {card id: 400 x 560 RGB image}  ('00'-'34', 'back')

usage (preview): compose_deck.py CAPTURE OUT.png
"""
import json, os, sys
import numpy as np
from PIL import Image
from scipy import ndimage
sys.path.insert(0, os.path.dirname(__file__))
from export_casino import card_image, card_origin, CW, CH, SHEET_CARDS

W, H = 400, 560                                   # a card at 10x (5 x 7 tiles)
RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
PAPER = np.array([250, 250, 248.])
GREEN = (22, 92, 40); GOLD = (205, 160, 60); DARK = (40, 25, 10)
SUIT_COL = [((70, 120, 215), (20, 45, 140)), ((215, 50, 55), (120, 10, 25))] * 2   # swords, shields, slimes, crowns

def ink(a): return np.sqrt(((a - PAPER) ** 2).sum(-1))

def cut_cards(art_dir):
    from make_casino_hdpack import find_card
    cards = {}
    for n, ids in enumerate(SHEET_CARDS, 1):
        p = os.path.join(art_dir, f'C{n:02d}.png')
        if not os.path.exists(p): continue
        sh = Image.open(p).convert('RGB')
        if sh.size != (1536, 1024): sh = sh.resize((1536, 1024), Image.LANCZOS)
        for i, cid in enumerate(ids):
            x0, y0 = card_origin(i); dx, dy = find_card(sh, x0, y0)
            cards[cid] = sh.crop((x0 + dx, y0 + dy, x0 + dx + CW, y0 + dy + CH)).resize((W, H), Image.LANCZOS)
    return cards

def cutout(a, region, near=None):
    """The painted figure in region (the largest, or the one nearest `near`), RGBA, paper removed."""
    x0, y0, x1, y1 = region; sub = a[y0:y1, x0:x1]; d = ink(sub)
    hard = ndimage.binary_fill_holes(ndimage.binary_closing(d > 45, iterations=2))
    lab, n = ndimage.label(hard)
    sz = ndimage.sum(hard, lab, range(1, n + 1))
    if near is None: k = int(np.argmax(sz)) + 1
    else:
        cs = ndimage.center_of_mass(hard, lab, range(1, n + 1))
        k = min(range(n), key=lambda i: (cs[i][0] - near[1] + y0) ** 2 + (cs[i][1] - near[0] + x0) ** 2 if sz[i] > 200 else 1e18) + 1
    m = lab == k
    soft = np.clip((d - 15) / 40, 0, 1)
    alpha = np.where(ndimage.binary_erosion(m, iterations=1), 1.0, soft * ndimage.binary_dilation(m, iterations=2))
    al = alpha[..., None]
    rgb = np.where(al > 0.05, (sub - PAPER * (1 - al)) / np.maximum(al, 0.05), sub)   # un-mix the paper at the edges
    im = Image.fromarray(np.dstack([np.clip(rgb, 0, 255), alpha * 255]).astype(np.uint8), 'RGBA')
    return im.crop(im.getbbox())

def blank_from(img):
    """The card with everything on its face painted out (smooth fill from the paper around it)."""
    a = np.asarray(img).astype(float); d = ink(a)
    inside = np.zeros(d.shape, bool); inside[14:-14, 10:-10] = True
    hole = ndimage.binary_dilation((d > 12) & inside, iterations=6)
    w = (~hole).astype(float)
    num = np.stack([ndimage.gaussian_filter(a[..., c] * w, 25) for c in range(3)], -1)
    fill = num / np.maximum(ndimage.gaussian_filter(w, 25)[..., None], 1e-6)
    a[hole] = fill[hole]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert('RGBA')

class Glyphs:
    def __init__(self, art_dir):
        meta = json.load(open(os.path.join(art_dir, 'glyphs.json')))
        sheet = Image.open(os.path.join(art_dir, 'glyphs.png')).convert('L')
        self.masks = {t: sheet.crop(tuple(b)) for t, b in meta['glyphs'].items()}

    def render(self, text, h, fill=None, grad=None, rim=0, condense=1.0):
        """text h px tall: flat `fill`, or a top-to-bottom gradient `grad` with a gold rim of `rim` px."""
        m = self.masks[text]; k = 4                         # work at 4x, then shrink
        mw = max(1, round(m.width * h * k / m.height * condense))
        pad = (rim + 2) * k
        ma = np.zeros((h * k + 2 * pad, mw + 2 * pad))
        ma[pad:pad + h * k, pad:pad + mw] = np.asarray(m.resize((mw, h * k), Image.LANCZOS)).astype(float) / 255
        hh, ww = ma.shape; out = np.zeros((hh, ww, 4))
        yy = np.linspace(0, 1, hh)[:, None, None]
        if rim:
            g = ndimage.grey_dilation(ma, size=(2 * rim * k + 1,) * 2)
            edge = ndimage.grey_dilation(g, size=(2 * k + 1,) * 2)
            out[..., :3] = DARK; out[..., 3] = edge
            gcol = np.array(GOLD) * (1.25 - 0.5 * yy)
            out[..., :3] = out[..., :3] * (1 - g[..., None]) + gcol * g[..., None]
            out[..., 3] = np.maximum(out[..., 3], g)
        col = (np.array(grad[0]) * (1 - yy) + np.array(grad[1]) * yy) if grad else np.array(fill)[None, None, :] * np.ones((hh, ww, 1))
        out[..., :3] = out[..., :3] * (1 - ma[..., None]) + col * ma[..., None]
        out[..., 3] = np.maximum(out[..., 3], ma)
        im = Image.fromarray(np.clip(np.dstack([out[..., :3], out[..., 3:] * 255]), 0, 255).astype(np.uint8), 'RGBA')
        im = im.crop(im.getbbox())
        return im.resize((max(1, round(im.width / k)), max(1, round(im.height / k))), Image.LANCZOS)

def fit(img, box):
    x0, y0, x1, y1 = box
    f = min((x1 - x0) / img.width, (y1 - y0) / img.height)
    w, h = max(1, round(img.width * f)), max(1, round(img.height * f))
    return img.resize((w, h), Image.LANCZOS), (round((x0 + x1 - w) / 2), round((y0 + y1 - h) / 2))

def layout8(cells):
    """The 8-bit card's pips (7 x 7 boxes) and the box of everything else between the corners."""
    im = np.asarray(card_image(cells, k=1)).astype(int)
    inner = im.min(-1) <= 200; inner[:8] = False; inner[48:] = False
    lab, n = ndimage.label(inner)
    pips, rest = [], []
    for i, (y, x) in enumerate(ndimage.find_objects(lab)):
        col = np.median(im[lab == i + 1], 0)
        green = col[1] > col[0] and col[1] > col[2]
        box = (x.start, y.start, x.stop, y.stop)
        if x.stop - x.start <= 8 and y.stop - y.start <= 8 and not green and (lab == i + 1).sum() > 15: pips.append(box)
        else: rest.append(box)
    return pips, rest

def compose(cap, art_dir):
    spec = json.load(open(os.path.join(art_dir, 'deck.json')))
    painted = cut_cards(art_dir)
    need = [spec['blank']] + [p['card'] for p in spec['pips']] + spec['aces'] + spec['whole']
    if any(c not in painted for c in need): return {}
    arr = {c: np.asarray(painted[c]).astype(float) for c in set(need)}
    blank = blank_from(painted[spec['blank']])
    pips = [cutout(arr[p['card']], (0, 30, W, H - 30), near=p['near']) for p in spec['pips']]
    aces = [cutout(arr[c], (40, 90, W - 40, H - 80)) for c in spec['aces']]
    gl = Glyphs(art_dir)
    out = {c: painted[c].convert('RGB') for c in spec['whole']}
    for c in range(0x34):
        cid = f'{c:02x}'; r, s = c // 4, c % 4
        card = blank.copy()
        corner = gl.render(RANKS[r], spec.get('corner_height', 52), fill=GREEN, condense=0.82 if r == 9 else 1.0)
        card.alpha_composite(corner, (22, 16))
        card.alpha_composite(corner.rotate(180), (W - 22 - corner.width, H - 16 - corner.height))
        p8, rest = layout8(cap['cards'][cid])
        half = spec['pip_size'] / 2 * spec['pips'][s].get('scale', 1.0) * (spec.get('face_pip_scale', 1.0) if r >= 10 else 1.0)
        for x0, y0, x1, y1 in p8:
            cx, cy = (x0 + x1) * 5, (y0 + y1) * 5
            im, pos = fit(pips[s], (cx - half, cy - half, cx + half, cy + half)); card.alpha_composite(im, pos)
        if rest:
            bx = [min(b[0] for b in rest) * 10, min(b[1] for b in rest) * 10, max(b[2] for b in rest) * 10, max(b[3] for b in rest) * 10]
            if r == 0:
                cx, cy = (bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2; aw, ah = spec['ace_size']
                im, pos = fit(aces[s], (cx - aw / 2, cy - ah / 2, cx + aw / 2, cy + ah / 2))
            else:
                L = gl.render(RANKS[r], bx[3] - bx[1], grad=SUIT_COL[s], rim=3)
                im, pos = fit(L, (bx[0] - 20, bx[1], bx[2] + 20, bx[3] + 10))
            card.alpha_composite(im, pos)
        out[cid] = card.convert('RGB')
    return out

def main():
    cap = json.load(open(os.path.join(sys.argv[1], 'cards.json')))
    art = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hd', 'casino', 'cards')
    cards = compose(cap, art)
    if not cards: sys.exit('compose_deck: card sheets missing')
    w, h = 200, 280
    sheet = Image.new('RGB', (13 * w, 5 * h), (0, 82, 0))
    for c in range(0x34): sheet.paste(cards[f'{c:02x}'].resize((w - 8, h - 8), Image.LANCZOS), ((c // 4) * w + 4, (c % 4) * h + 4))
    for i, cid in enumerate(('34', 'back')): sheet.paste(cards[cid].resize((w - 8, h - 8), Image.LANCZOS), (i * w + 4, 4 * h + 4))
    sheet.save(sys.argv[2]); print(f'{len(cards)} cards -> {sys.argv[2]}')

if __name__ == '__main__':
    main()
