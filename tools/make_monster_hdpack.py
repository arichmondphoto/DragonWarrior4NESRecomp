"""Add HD battle monsters to an HD pack directory (Mesen hires.txt format).

Inputs:
  CAPTURE   tools/capture_monsters.py output (NNN.mem / NNN.png per monster ID),
            plus the special captures named in mapping.json "captures"
            (CAPTURE/necro/necro_F from tools/capture_necrosaro.py)
  hd/monsters/mapping.json + boxes.json + the source sheet (the owner's art)

For each mapped monster the sprite is cut from the sheet (transparency rebuilt
from the black background) and scaled to fit the original monster's visible
pixels at SCALE x (contain, centred horizontally, standing on the original's
bottom edge). The scaled art is then sliced along the original's own pieces:

  background tiles  one SCALE*8 slice per nametable cell, keyed by the cell's
                    16 CHR bytes + exact 4-colour BG palette;
  sprites           one slice per 8x8 OAM sprite at its exact pixel position,
                    stored un-flipped (the presenter applies the sprite's
                    flips), keyed by CHR bytes + $FF + the 3 sprite colours.

Repeated pieces inside one monster:
  * a BG tile used at several cells (solid fills) keeps the first cell's slice
    as its default; every other cell gets an entry gated on a neighbouring
    BG tile (tileNearby, searched up to 4 cells away) that is different at
    that offset from every other cell using the tile;
  * a sprite tile drawn mirrored as well as plain gets one entry per flip,
    gated on the built-in hmirror / vmirror conditions.

Monster images are appended after any existing <img> entries (e.g. the text
pack) in OUTDIR/hires.txt.

usage: make_monster_hdpack.py CAPTURE OUTDIR [--scale 10] [--report FILE]
"""
import argparse, json, os, sys
from PIL import Image, ImageOps
sys.path.insert(0, os.path.dirname(__file__))
from monster_tiles import monster
from sheet_sprites import cut

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MON = os.path.join(HERE, 'hd', 'monsters')
OFFSETS = sorted(((dr, dc) for dr in range(-4, 5) for dc in range(-4, 5) if (dr, dc) != (0, 0)),
                 key=lambda o: (abs(o[0]) + abs(o[1]), o))

def fit(sprite, nes_img, S):
    """Canvas over the monster's pixel box at S px per native px."""
    W, H = nes_img.size
    canvas = Image.new('RGBA', (W * S, H * S), (0, 0, 0, 0))
    bb = nes_img.getchannel('A').getbbox()
    if not bb: return canvas
    tx0, ty0, tx1, ty1 = (v * S for v in bb)
    tw, th = tx1 - tx0, ty1 - ty0
    k = min(tw / sprite.width, th / sprite.height)
    sw, sh = max(1, round(sprite.width * k)), max(1, round(sprite.height * k))
    canvas.alpha_composite(sprite.resize((sw, sh), Image.LANCZOS), (tx0 + (tw - sw) // 2, ty1 - sh))
    return canvas

def alpha_sum(im):
    return sum(im.getchannel('A').tobytes())

def drawn(sl):
    """The presenter treats a fully transparent HD tile as 'no replacement'
    and shows the original 8-bit pixels. Where the owner's art doesn't reach
    a piece of the original monster, keep one black pixel at alpha 1/255 so
    the piece is replaced by (effectively) nothing."""
    if sl.getchannel('A').getbbox() is None:
        sl = sl.copy(); sl.putpixel((0, 0), (0, 0, 0, 1))
    return sl

class Sheet:
    """Packs equally sized slices into one image per monster."""
    def __init__(self, n, T):
        self.T, self.cols = T, max(1, min(16, n))
        self.img = Image.new('RGBA', (self.cols * T, ((n + self.cols - 1) // self.cols) * T), (0, 0, 0, 0))
        self.k = 0
    def add(self, tile):
        x, y = (self.k % self.cols) * self.T, (self.k // self.cols) * self.T
        self.img.alpha_composite(tile, (x, y)); self.k += 1
        return x, y

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('capture'); ap.add_argument('outdir')
    ap.add_argument('--scale', type=int, default=10)
    ap.add_argument('--report')
    a = ap.parse_args()
    S = a.scale; T = 8 * S
    mapping = json.load(open(os.path.join(MON, 'mapping.json')))
    boxes = json.load(open(os.path.join(MON, 'boxes.json')))
    Image.MAX_IMAGE_PIXELS = None
    sheet = Image.open(os.path.join(MON, mapping['sheet'])).convert('RGB')

    hires = os.path.join(a.outdir, 'hires.txt')
    lines = open(hires).read().splitlines() if os.path.exists(hires) else ['<ver>106', f'<scale>{S}']
    img_index = sum(1 for l in lines if l.startswith('<img>'))
    os.makedirs(os.path.join(a.outdir, 'monsters'), exist_ok=True)
    conds, tiles, report = [], [], {}
    jobs = [(int(k), v, f'{v:03d}') for k, v in sorted(mapping['map'].items(), key=lambda kv: kv[1])]
    jobs += [(int(k), os.path.basename(v), v) for k, v in mapping.get('captures', {}).items() if not k.startswith('_')]
    # Sprites that share tiles with another sheet sprite (Necrosaro's forms reuse
    # most of the previous form's tiles) are gated on game memory: "when" maps
    # a sheet index to ADDR==VALUE, e.g. the form counter $6E7E.
    gates = {}
    for k, w in mapping.get('when', {}).items():
        if k.startswith('_'): continue
        addr, val = w.split('==')
        name = f'mem{addr}_{int(val, 0)}'
        if name not in gates.values():
            conds.append(f'<condition>{name},memoryCheckConstant,{addr},==,{int(val, 0):X}')
        gates[int(k)] = name
    for s, mid, stem in jobs:
        first_tile = len(tiles)
        m = monster(os.path.join(a.capture, stem + '.mem'), os.path.join(a.capture, stem + '.png'))
        if not m: report[mid] = 'no monster pieces in capture'; continue
        canvas = fit(cut(sheet, boxes[s]), m['image'], S)
        ox, oy = m['box'][:2]
        bg, spr = m['bg'], m['spr']
        packer = Sheet(len(bg) + len(spr), T)
        total = alpha_sum(canvas); kept = 0; unresolved = 0
        # ---- background cells ----
        occ = {}
        for (r, c) in sorted(bg):
            occ.setdefault(bg[(r, c)][1:], []).append((r, c))
        for key, cells in occ.items():
            for i, (r, c) in enumerate(cells):
                sl = canvas.crop(((c * 8 - ox) * S, (r * 8 - oy) * S, (c * 8 - ox) * S + T, (r * 8 - oy) * S + T))
                if i == 0: kept += alpha_sum(sl)
                x, y = packer.add(drawn(sl))
                entry = f'<tile>{img_index},{key[0].hex().upper()},{key[1].hex().upper()},{x},{y},1,N'
                if i == 0: tiles.append(entry); continue
                for dr, dc in OFFSETS:
                    nb = bg.get((r + dr, c + dc))
                    if nb and all(bg.get((r2 + dr, c2 + dc), (None,))[1:] != nb[1:] for (r2, c2) in cells if (r2, c2) != (r, c)):
                        name = f'm{mid}_{r}_{c}'
                        conds.append(f'<condition>{name},tileNearby,{dc * 8},{dr * 8},{nb[1].hex().upper()},{nb[2].hex().upper()}')
                        tiles.append(f'[{name}]{entry}'); kept += alpha_sum(sl)
                        break
                else:
                    unresolved += 1
        # ---- sprites ----
        socc = {}
        for sp in spr:
            socc.setdefault((sp['data'], sp['pal']), []).append(sp)
        for (data, pal), group in socc.items():
            seen_flips = set()
            for i, sp in enumerate(group):
                flips = (sp['hflip'], sp['vflip'])
                if flips in seen_flips: unresolved += 1; continue
                seen_flips.add(flips)
                sx, sy = (sp['x'] - ox) * S, (sp['y'] - oy) * S
                sl = canvas.crop((sx, sy, sx + T, sy + T))
                kept += alpha_sum(sl)
                if sp['hflip']: sl = ImageOps.mirror(sl)          # store un-flipped
                if sp['vflip']: sl = ImageOps.flip(sl)
                x, y = packer.add(drawn(sl))
                entry = f'<tile>{img_index},{data.hex().upper()},{pal.hex().upper()},{x},{y},1,N'
                if i == 0 and flips == (False, False) or len(group) == 1:
                    tiles.append(entry)
                else:
                    gate = ('' if sp['hflip'] else '!') + 'hmirror&' + ('' if sp['vflip'] else '!') + 'vmirror'
                    tiles.append(f'[{gate}]{entry}')
        if s in gates:
            g = gates[s]
            for i in range(first_tile, len(tiles)):
                t = tiles[i]
                tiles[i] = f'[{g}&{t[1:]}' if t.startswith('[') else f'[{g}]{t}'
        rel = f'monsters/{os.path.basename(stem)}.png'
        packer.img.save(os.path.join(a.outdir, rel), optimize=True)
        lines.append(f'<img>{rel}')
        img_index += 1
        report[mid] = {'sheet': s, 'bg_cells': len(bg), 'sprites': len(spr), 'unresolved_repeats': unresolved,
                       'art_kept': round(min(1.0, kept / max(1, total)), 3)}
    head = [l for l in lines if l.startswith(('<ver>', '<scale>'))]
    imgs = [l for l in lines if l.startswith('<img>')]
    rest = [l for l in lines if not l.startswith(('<ver>', '<scale>', '<img>'))]
    out = head + imgs + rest + [f'# HD battle monsters ({len(report)}): owner art keyed by CHR bytes + exact palette'] + conds + tiles
    open(hires, 'w').write('\n'.join(out) + '\n')
    print(f'{len(report)} monsters, {len(tiles)} tile entries ({len(conds)} neighbour conditions) -> {hires}')
    if a.report: json.dump({str(k): v for k, v in sorted(report.items(), key=lambda kv: str(kv[0]))}, open(a.report, 'w'), indent=1)

if __name__ == '__main__':
    main()
