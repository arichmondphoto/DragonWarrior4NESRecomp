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
from field_sheet import pixels

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
    a = np.asarray(img.convert('RGB')).astype(float)
    W = a.shape[1]
    if h:
        d = ndimage.gaussian_filter1d(a[:, 0] - a[:, -1], 6, axis=0, mode='wrap')
        a += d[:, None, :] * (np.arange(W)[None, :, None] / (W - 1) - 0.5)   # edges meet
    if v:
        d = ndimage.gaussian_filter1d(a[0] - a[-1], 6, axis=0, mode='wrap')
        a += d[None, :, :] * (np.arange(W)[:, None, None] / (W - 1) - 0.5)
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
    art_for = {}
    if os.path.exists(idmap):
        by_fp = {fp: aid for aid, fp in json.load(open(idmap))['ids'].items()}
        for iid, vs in items.items():
            fp = hashlib.sha1(bytes.fromhex(vs[0]['chr'])).hexdigest()[:16]
            if fp in by_fp: art_for[iid] = by_fp[fp]

    hires = os.path.join(a.outdir, 'hires.txt')
    lines = open(hires).read().splitlines() if os.path.exists(hires) else ['<ver>106', '<scale>10']
    img_index = sum(1 for l in lines if l.startswith('<img>'))
    os.makedirs(os.path.join(a.outdir, 'field'), exist_ok=True)

    # ---- art per (item, palette version) -> image index -----------------
    imgs, missing, seamless = [], [], 0
    version_img = {}                                 # row id -> image index
    for iid, vs in items.items():
        aid = art_for.get(iid, iid)
        base = os.path.join(a.art, aid + '.png')
        if not os.path.exists(base): missing.append(iid); continue
        px = pixels(bytes.fromhex(vs[0]['chr']))
        h, v = tileable(px)
        def load(path):
            im = Image.open(path).convert('RGB')
            if im.size != (160, 160): im = im.resize((160, 160), Image.LANCZOS)
            return make_seamless(im, h, v) if (h or v) else im
        if h or v: seamless += 1
        main_idx = None
        for r in vs:
            over = os.path.join(a.art, aid + r['id'][len(iid):] + '.png') if r['id'] != iid else None
            if over and os.path.exists(over):
                rel = f'field/{aid + r["id"][len(iid):]}.png'; load(over).save(os.path.join(a.outdir, rel))
                lines.append(f'<img>{rel}'); version_img[r['id']] = img_index; img_index += 1
            else:
                if main_idx is None:
                    rel = f'field/{aid}.png'; load(base).save(os.path.join(a.outdir, rel))
                    lines.append(f'<img>{rel}'); main_idx = img_index; img_index += 1
                version_img[r['id']] = main_idx

    # ---- quarter keys -> owners -----------------------------------------
    owners = collections.defaultdict(list)           # (chr, pal) -> [(row, q)]
    uses = {}
    for iid, vs in items.items():
        for r in vs:
            if r['id'] not in version_img: continue
            t = bytes.fromhex(r['chr']); pal = r['nes_colors'].upper()
            uses[r['id']] = len(r['used_in'])
            for q in range(4):
                owners[(t[16 * q:16 * q + 16].hex().upper(), pal)].append((r, q))

    conds, tiles, names = [], [], {}
    def cond(dx, dy, chr_hex, pal):
        k = (dx, dy, chr_hex, pal)
        if k not in names:
            names[k] = f'f{len(names)}'
            conds.append(f'<condition>{names[k]},tileNearby,{dx},{dy},{chr_hex},{pal}')
        return names[k]
    def sibs(r, q):
        t = bytes.fromhex(r['chr']); pal = r['nes_colors'].upper()
        return {s: (QOFF[s][0] - QOFF[q][0], QOFF[s][1] - QOFF[q][1], t[16 * s:16 * s + 16].hex().upper(), pal)
                for s in range(4) if s != q}
    gated_only = unresolved = 0
    for (chr_hex, pal), own in owners.items():
        # one entry per distinct (image, quarter); identical art needs no gate
        distinct = {}
        for r, q in own: distinct.setdefault((version_img[r['id']], q), (r, q))
        own = sorted(distinct.values(), key=lambda rq: -uses[rq[0]['id']])
        blank = not any(bytes.fromhex(chr_hex))
        entry = lambda r, q: f'<tile>{version_img[r["id"]]},{chr_hex},{pal},{QOFF[q][0] * 10},{QOFF[q][1] * 10},1,N'
        if len(own) == 1 and not blank:
            tiles.append(entry(*own[0])); continue
        if not blank: tiles.append(entry(*own[0]))        # most used owner = plain default
        else: gated_only += 1
        for r, q in own:
            mine = sibs(r, q)
            others = [sibs(r2, q2) for r2, q2 in own if (r2, q2) != (r, q)]
            # fewest neighbours (1, then 2, then 3) that tell this owner apart
            choice = None
            def matches(o, combo):      # another owner whose same neighbours look identical
                return all(any(o_s == mine[s] for o_s in o.values()) for s in combo)
            for n in (1, 2, 3):
                for combo in itertools.combinations(sorted(mine), n):
                    if not any(matches(o, combo) for o in others): choice = combo; break
                if choice: break
            if not choice: unresolved += 1; choice = tuple(sorted(mine))
            gate = '&'.join(cond(*mine[s]) for s in choice)
            tiles.append(f'[{gate}]{entry(r, q)}')

    head = [l for l in lines if l.startswith(('<ver>', '<scale>'))]
    imgl = [l for l in lines if l.startswith('<img>')]
    rest = [l for l in lines if not l.startswith(('<ver>', '<scale>', '<img>'))]
    out = head + imgl + rest + [f'# HD map tiles ({len(items) - len(missing)} tiles): owner art keyed per 8x8 quarter + exact palette'] + conds + tiles
    open(hires, 'w').write('\n'.join(out) + '\n')
    print(f'{len(items) - len(missing)} map tiles ({seamless} made seamless), {len(tiles)} tile entries, '
          f'{len(conds)} neighbour conditions, {unresolved} unresolved -> {hires}')
    if missing: print(f'  no art yet for {len(missing)}: {" ".join(missing[:20])}{" ..." if len(missing) > 20 else ""}')
    if a.report:
        json.dump({'missing': missing, 'seamless': seamless, 'entries': len(tiles), 'conditions': len(conds),
                   'unresolved': unresolved, 'gated_only_blank': gated_only}, open(a.report, 'w'), indent=1)

if __name__ == '__main__':
    main()
