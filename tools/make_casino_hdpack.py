"""Add the Endor casino's poker table to an HD pack directory.

From tools/capture_casino.py (CAPTURE/cards.json):

  cards   the owner's generated card sheets hd/casino/cards/C01-C09.png
          (tools/export_casino.py layout; sheets.json lists the cards). With
          hd/casino/cards/deck.json the whole deck is composed from one set of
          their parts (tools/compose_deck.py), so the cards match; without it
          each card is cut from its sheet (found by its white face).
          A card is 5 x 7 tiles; each of its 35 cells is keyed by CHR +
          colours and, where other cards share that tile, told apart by the
          fewest of its own card's other cells (tileNearby). Screen-fade
          steps get the same art at the matching brightness.
  screen  the poker screen's own tiles that the text pack does not cover
          (its digits and labels) and the pointing hand, smoothly upscaled
          from the game's tiles (tools/smooth_pixels.py), in their colours.

usage: make_casino_hdpack.py CAPTURE OUTDIR
"""
import collections, json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from field_sheet import NES
from smooth_pixels import smooth_mask
from export_casino import card_origin, CW, CH, SHEET_CARDS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ART = os.path.join(HERE, 'hd', 'casino', 'cards')
S = 10; C = 8 * S

def rgb(c): v = NES[c & 0x3F]; return np.array([(v >> 16) & 255, (v >> 8) & 255, v & 255], float)
def fade(pal, k): return bytes(0x0F if (c & 0x3F) < 0x10 * k or (c & 0x0F) >= 0x0D else c - 0x10 * k for c in pal)
def dark(p): return all((x & 0x0F) >= 0x0D or x == 0x0F for x in p[1:])
def lum(p): return sum(rgb(x) @ (0.299, 0.587, 0.114) for x in p[1:])

def pixels(d):
    return np.array([[((d[r] >> (7 - c)) & 1) | (((d[r + 8] >> (7 - c)) & 1) << 1) for c in range(8)] for r in range(8)])

def smooth_tile(chr_hex, pal_hex, sprite=False):
    """Each colour of the tile smoothed on its own, in its colour; colour 0 transparent."""
    px = pixels(bytes.fromhex(chr_hex)); pal = bytes.fromhex(pal_hex)
    out = Image.new('RGBA', (C, C), (0, 0, 0, 0))
    for v in (1, 2, 3):
        if not (px == v).any(): continue
        m = smooth_mask([[1 if x == v else 0 for x in row] for row in px], C, 0.9, mode='zero')
        col = rgb(pal[v]).astype(int)
        layer = Image.new('RGBA', (C, C), tuple(col) + (255,)); layer.putalpha(m)
        out.alpha_composite(layer)
    return out

def find_card(sheet, x0, y0):
    """The white card face near (x0, y0): the offset within +-24 px where the
    card's box is white inside and not white just outside it, on all sides."""
    a = np.asarray(sheet.convert('RGB')).astype(int)
    white = (a.min(-1) > 190).astype(float)
    ii = np.pad(white, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    def mean(y0_, x0_, y1, x1):
        y0_, x0_ = max(y0_, 0), max(x0_, 0); y1, x1 = min(y1, a.shape[0]), min(x1, a.shape[1])
        if y1 <= y0_ or x1 <= x0_: return 0.0
        return (ii[y1, x1] - ii[y0_, x1] - ii[y1, x0_] + ii[y0_, x0_]) / ((y1 - y0_) * (x1 - x0_))
    best = (0, 0, -9)
    for dy in range(-24, 25):
        for dx in range(-24, 25):
            y, x = y0 + dy, x0 + dx
            inside = mean(y + 12, x + 12, y + CH - 12, x + CW - 12)
            out = (mean(y - 6, x, y, x + CW) + mean(y + CH, x, y + CH + 6, x + CW)
                   + mean(y, x - 6, y + CH, x) + mean(y, x + CW, y + CH, x + CW + 6)) / 4
            sc = inside - out
            if sc > best[2]: best = (dx, dy, sc)
    return best[0], best[1]

def main():
    cap_dir, outdir = sys.argv[1], sys.argv[2]
    cap_p = os.path.join(cap_dir, 'cards.json')
    if not os.path.exists(cap_p): print('  casino: no capture'); return
    cap = json.load(open(cap_p))
    hires = os.path.join(outdir, 'hires.txt'); lines = open(hires).read().splitlines()
    n_img = sum(1 for l in lines if l.startswith('<img>'))
    have_chr = {l.split(',')[1].lower() for l in lines if l.startswith('<tile>') and l.rstrip().endswith(',Y')}
    os.makedirs(os.path.join(outdir, 'casino'), exist_ok=True)
    atlas, entries, conds, cnames = [], [], [], {}
    def add(img):
        atlas.append(img); i = len(atlas) - 1; return i, (i % 16) * C, (i // 16) * C

    # ---- cards ----------------------------------------------------------
    cards = dict(cap['cards']); cards['back'] = cap['back']
    art = {}
    if os.path.exists(os.path.join(ART, 'deck.json')):          # one consistent deck from the sheets' parts
        from compose_deck import compose
        art = {cid: im.resize((5 * C, 7 * C), Image.LANCZOS) for cid, im in compose(cap, ART).items()}
    for n, ids in enumerate(SHEET_CARDS if not art else [], 1):
        p = os.path.join(ART, f'C{n:02d}.png')
        if not os.path.exists(p): continue
        sheet = Image.open(p).convert('RGB')
        if sheet.size != (1536, 1024): sheet = sheet.resize((1536, 1024), Image.LANCZOS)
        for i, cid in enumerate(ids):
            x0, y0 = card_origin(i); dx, dy = find_card(sheet, x0, y0)
            art[cid] = sheet.crop((x0 + dx, y0 + dy, x0 + dx + CW, y0 + dy + CH)).resize((5 * C, 7 * C), Image.LANCZOS)
    owners = collections.defaultdict(list)                       # key -> [(card, cell)]
    for cid, cells in cards.items():
        for n, (ch, pal) in enumerate(cells): owners[(ch, pal)].append((cid, n))
    def key_at(cid, n, ox, oy):
        x, y = n % 5 + ox, n // 5 + oy
        if not (0 <= x < 5 and 0 <= y < 7): return None
        return tuple(cards[cid][y * 5 + x])
    def distinguish(cid, n):
        """Fewest other cells of this card that no other owner of the tile shares."""
        rivals = [(c, m) for c, m in owners[tuple(cards[cid][n])] if (c, m) != (cid, n)]
        chosen = []
        offs = [(x - n % 5, y - n // 5) for y in range(7) for x in range(5) if (x, y) != (n % 5, n // 5)]
        # most telling cells first: those whose tile is rarest among all cards
        rare = lambda o: len(owners[key_at(cid, n, *o)])
        offs.sort(key=rare)
        while rivals:
            best = min(offs, key=lambda o: sum(key_at(c, m, *o) == key_at(cid, n, *o) for c, m in rivals))
            left = [(c, m) for c, m in rivals if key_at(c, m, *best) == key_at(cid, n, *best)]
            if len(left) == len(rivals): return None
            chosen.append(best); rivals = left; offs.remove(best)
        return chosen
    made = 0
    for cid, pic in art.items():
        cells = cards[cid]
        for n, (ch, pal) in enumerate(cells):
            if not any(bytes.fromhex(ch)): continue
            how = distinguish(cid, n)
            if how is None: continue
            x, y = n % 5, n // 5
            i, ax, ay = add(pic.crop((x * C, y * C, (x + 1) * C, (y + 1) * C)))
            base = bytes.fromhex(pal)
            for k in (0, 1, 2, 3):
                pk = fade(base, k) if k else base
                if k and dark(pk): continue
                br = 1.0 if not k else round(min(1.0, lum(pk) / max(lum(base), 1)), 3)
                names = []
                for ox, oy in how:
                    nch, npal = key_at(cid, n, ox, oy)
                    npk = fade(bytes.fromhex(npal), k) if k else bytes.fromhex(npal)
                    ck = (ox, oy, nch, npk.hex())
                    if ck not in cnames:
                        cnames[ck] = f'cz{len(cnames)}'
                        conds.append(f'<condition>{cnames[ck]},tileNearby,{ox * 8},{oy * 8},{nch.upper()},{npk.hex().upper()}')
                    names.append(cnames[ck])
                gate = f'[{"&".join(names)}]' if names else ''
                entries.append(f'{gate}<tile>{n_img},{ch.upper()},{pk.hex().upper()},{ax},{ay},{br:g},N')
            made += 1

    # ---- the rest of the poker screen: smoothed from the game's tiles ------
    smoothed = 0
    for ch, pal in cap['screen_tiles']:
        if ch.lower() in have_chr: continue
        i, ax, ay = add(smooth_tile(ch, pal)); base = bytes.fromhex(pal)
        for k in (0, 1, 2, 3):
            pk = fade(base, k) if k else base
            if k and dark(pk): continue
            br = 1.0 if not k else round(min(1.0, lum(pk) / max(lum(base), 1)), 3)
            entries.insert(0, f'<tile>{n_img},{ch.upper()},{pk.hex().upper()},{ax},{ay},{br:g},N')
        smoothed += 1
    for ch, pal in cap['sprites']:
        i, ax, ay = add(smooth_tile(ch, '00' + pal[2:], sprite=True))
        entries.insert(0, f'<tile>{n_img},{ch.upper()},{pal.upper()},{ax},{ay},1,N')
        smoothed += 1

    rows = (len(atlas) + 15) // 16
    sheet = Image.new('RGBA', (16 * C, max(rows, 1) * C), (0, 0, 0, 0))
    for i, im in enumerate(atlas): sheet.alpha_composite(im.convert('RGBA'), ((i % 16) * C, (i // 16) * C))
    sheet.save(os.path.join(outdir, 'casino', 'poker.png'), optimize=True)
    head = [l for l in lines if l.startswith(('<ver>', '<scale>', '<options>'))]
    imgl = [l for l in lines if l.startswith('<img>')] + ['<img>casino/poker.png']
    rest = [l for l in lines if not l.startswith(('<ver>', '<scale>', '<options>', '<img>'))]
    open(hires, 'w').write('\n'.join(head + imgl + ['# Endor casino: poker'] + conds + entries + rest) + '\n')
    print(f'  casino: {len(art)} cards with art ({made} cells), {smoothed} screen tiles smoothed -> {hires}')

if __name__ == '__main__':
    main()
