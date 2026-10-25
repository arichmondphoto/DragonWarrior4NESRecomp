"""Check (and fit) AI-redrawn character sheets against the 8-bit originals.

Reads RESULTS/<ID>.png made from tools/export_chatgpt_sprites.py inputs (any
3:2 size; scaled to 1536x1024). For each of the 8 frames it:
  * takes the art's shape (alpha if the image is transparent, otherwise
    everything that isn't the flat background colour);
  * compares it with the original sprite's silhouette (IoU = overlap /
    union) where it was drawn, then searches a small shift and scale
    (+-48 px, 0.8-1.25x) for the best fit;
  * keeps the fitted frame, clipped to the silhouette, as the game will
    show it.

Each frame's colours are also compared with all 8 originals, to catch a
frame drawn facing the wrong way (same outline, wrong view).

Verdict per character: ok (every frame fits as drawn), fitted (needed a
nudge; fine), redo (some frame doesn't match the outline even after fitting:
wrong pose, missing or moved frame).

Writes OUT/report.csv, OUT/fitted/<ID>.png (frames back in the
export_ai_sprites.py 4x2 layout, 160 px cells) and OUT/review/<ID>.png
(original | AI | as the game will show it).

usage: check_ai_sprites.py RESULTS CHARACTERS_JSON OUT
"""
import csv, json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from sprite_sheet import frame_image
from export_chatgpt_sprites import W, H, CELL, SCALE, cell_origin, BIG_ID, BIG_PARTS, big_origin

OK, FIT = 0.85, 0.80          # IoU as drawn / after fitting
PAD = 48

def shape_mask(img):
    a = np.asarray(img.convert('RGBA')).astype(np.int32)
    if (a[..., 3] < 128).mean() > 0.2: return a[..., 3] >= 128
    # opaque: background = the most common border colour
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])[:, :3]
    vals, cnt = np.unique(border // 8, axis=0, return_counts=True)
    bg = vals[cnt.argmax()] * 8 + 4
    return np.abs(a[..., :3] - bg).sum(-1) > 60

def iou(a, b):
    u = (a | b).sum()
    return (a & b).sum() / u if u else 1.0

def fit(art_rgba, art_mask, sil):
    """Best (iou, dx, dy, s) placing the cell's art over the silhouette."""
    ys, xs = np.nonzero(art_mask); ty, tx = np.nonzero(sil)
    if len(xs) == 0: return 0.0, 0, 0, 1.0
    best = (iou(art_mask[PAD:PAD + CELL, PAD:PAD + CELL], sil), 0, 0, 1.0)
    # start from matching bounding boxes, then refine
    s0 = np.sqrt(((tx.max() - tx.min() + 1) * (ty.max() - ty.min() + 1)) /
                 max(1, (xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)))
    m = Image.fromarray(art_mask.astype(np.uint8) * 255)
    for s in sorted({round(x, 3) for x in np.clip([s0 * k for k in (0.94, 0.97, 1, 1.03, 1.06)] + [1.0], 0.8, 1.25)}):
        sm = np.asarray(m.resize((round(m.width * s), round(m.height * s)), Image.BILINEAR)) >= 128
        yy, xx = np.nonzero(sm)
        cx0 = int(round((tx.min() + tx.max()) / 2 - (xx.min() + xx.max()) / 2))
        cy0 = int(round((ty.min() + ty.max()) / 2 - (yy.min() + yy.max()) / 2))
        for dy in range(cy0 - 6, cy0 + 7, 2):
            for dx in range(cx0 - 6, cx0 + 7, 2):
                canvas = np.zeros((CELL, CELL), bool)
                y0, x0 = max(0, dy), max(0, dx)
                y1, x1 = min(CELL, dy + sm.shape[0]), min(CELL, dx + sm.shape[1])
                if y1 <= y0 or x1 <= x0: continue
                canvas[y0:y1, x0:x1] = sm[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
                v = iou(canvas, sil)
                if v > best[0] + 1e-9: best = (v, dx, dy, s)
    return best

def sheet_fit(img, full):
    """Scale/shift the whole sheet so its art lines up with the silhouettes."""
    m = shape_mask(img)
    small = lambda a: np.asarray(Image.fromarray(a.astype(np.uint8) * 255).resize((W // 4, H // 4), Image.BILINEAR)) >= 128
    ref = small(full)
    def place(s, dx, dy):
        out = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        im = img.copy(); im.putalpha(Image.fromarray(m.astype(np.uint8) * 255))
        im = im.resize((round(W * s), round(H * s)), Image.LANCZOS)
        out.paste(im, (dx, dy), im); return out
    m4 = Image.fromarray(m.astype(np.uint8) * 255).resize((W // 4, H // 4), Image.BILINEAR)
    def shifted(s, dx, dy):                      # the placed mask at 1/4 size, quickly
        q = np.asarray(m4.resize((max(1, round(W * s / 4)), max(1, round(H * s / 4))), Image.BILINEAR)) >= 128
        out = np.zeros((H // 4, W // 4), bool); ox, oy = round(dx / 4), round(dy / 4)
        y0, x0 = max(0, oy), max(0, ox); y1, x1 = min(H // 4, oy + q.shape[0]), min(W // 4, ox + q.shape[1])
        if y1 > y0 and x1 > x0: out[y0:y1, x0:x1] = q[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
        return out
    base = iou(small(m), ref)
    ys, xs = np.nonzero(m); ty, tx = np.nonzero(full)
    if not len(xs): return img, ''
    s0 = ((tx.max() - tx.min()) / max(1, xs.max() - xs.min()) + (ty.max() - ty.min()) / max(1, ys.max() - ys.min())) / 2
    best = (base, 1.0, 0, 0)
    for s in (s0 * 0.98, s0 * 0.99, s0, s0 * 1.01, s0 * 1.02):
        if not 0.8 <= s <= 1.25: continue
        dx0 = round(tx.min() - xs.min() * s); dy0 = round(ty.min() - ys.min() * s)
        for dy in range(dy0 - 8, dy0 + 9, 4):
            for dx in range(dx0 - 8, dx0 + 9, 4):
                v = iou(shifted(s, dx, dy), ref)
                if v > best[0] + 0.005: best = (v, s, dx, dy)
    if best[1:] == (1.0, 0, 0): return img, ''
    return place(*best[1:]), f'whole sheet moved {best[2]:+d},{best[3]:+d} px, scaled {best[1]:.3f}'

def main():
    res, cj, out = sys.argv[1:4]
    rows = {r['id']: r for r in json.load(open(cj))}
    for d in ('fitted', 'review'): os.makedirs(os.path.join(out, d), exist_ok=True)
    report = []
    todo = []
    for fn in sorted(os.listdir(res)):
        if not fn.lower().endswith(('.png', '.webp', '.jpg', '.jpeg')): continue
        stem = os.path.splitext(fn)[0].upper()
        img = Image.open(os.path.join(res, fn)).convert('RGBA')
        note = ''
        if abs(img.width / img.height - 1.5) > 0.02: note = f'not 3:2 ({img.width}x{img.height}); '
        img = img.resize((W, H), Image.LANCZOS)
        if stem == BIG_ID:
            # cut the two poses into the four quarter characters' usual sheets
            for q, pid in enumerate(BIG_PARTS):
                sheet = Image.new('RGBA', (W, H), (0, 0, 0, 0))
                for fi in range(8):
                    x, y = big_origin(fi % 2, q)
                    sheet.alpha_composite(img.crop((x, y, x + CELL, y + CELL)), cell_origin(fi))
                todo.append((pid, sheet, note + f'from {BIG_ID}; '))
            continue
        cid = stem.split('_')[0]
        if cid in rows: todo.append((cid, img, note))
    big_done = {c for c, i, n in todo if 'from ' + BIG_ID in n}
    todo = [t for t in todo if t[0] not in big_done or 'from ' + BIG_ID in t[2]]   # the combined art wins
    for cid, img, note in todo:
        r = rows[cid]
        big = 'from ' + BIG_ID in note
        cols = [bytes.fromhex(c) for c in r['versions'][0]['colours']]
        # whole-sheet fit first: the model often redraws the canvas slightly
        # bigger/smaller or shifted, moving the outer frames by more than a cell gap
        full = np.zeros((H, W), bool)
        for fi, fr in enumerate(r['frames']):
            o = frame_image([(bytes.fromhex(c), a) for c, a in fr], cols[fi * 4:fi * 4 + 4], SCALE)
            x, y = cell_origin(fi); full[y:y + CELL, x:x + CELL] |= np.asarray(o.getchannel('A')) >= 128
        img, gs = sheet_fit(img, full) if not big else (img, '')
        if gs: note += gs + '; '
        mask = shape_mask(img)
        fitted = Image.new('RGBA', (4 * 160 + 5 * 12, 2 * 160 + 3 * 12), (0, 0, 0, 0))
        review = Image.new('RGBA', (3 * 4 * 170 + 40, 2 * 170 + 10), (60, 60, 64, 255))
        scores, sils, origs, smalls = [], [], [], []
        for fi, fr in enumerate(r['frames']):
            orig = frame_image([(bytes.fromhex(c), a) for c, a in fr], cols[fi * 4:fi * 4 + 4], SCALE)
            sil = np.asarray(orig.getchannel('A')) >= 128
            x, y = cell_origin(fi)
            box = (x - PAD, y - PAD, x + CELL + PAD, y + CELL + PAD)
            art = img.crop(box); am = np.zeros((CELL + 2 * PAD, CELL + 2 * PAD), bool)
            sub = mask[max(0, box[1]):box[3], max(0, box[0]):box[2]]
            am[max(0, -box[1]):max(0, -box[1]) + sub.shape[0], max(0, -box[0]):max(0, -box[0]) + sub.shape[1]] = sub
            drawn = iou(am[PAD:PAD + CELL, PAD:PAD + CELL], sil)
            best, dx, dy, s = fit(art, am, sil) if not big else (drawn, 0, 0, 1.0)
            # place the art: scale about the padded crop, offset so it lands where fitted
            if (dx, dy, s) == (0, 0, 1.0): placed = art.crop((PAD, PAD, PAD + CELL, PAD + CELL))
            else:
                a2 = art.copy(); a2.putalpha(Image.fromarray(am.astype(np.uint8) * 255))
                a2 = a2.resize((round(a2.width * s), round(a2.height * s)), Image.LANCZOS)
                placed = Image.new('RGBA', (CELL, CELL), (0, 0, 0, 0)); placed.paste(a2, (dx, dy), a2)
            placed = placed.copy(); pa = np.asarray(placed).copy()
            pa[..., 3] = np.where(sil, 255, 0)        # as the game shows it: inside the outline only
            game = Image.fromarray(pa, 'RGBA')
            scores.append((drawn, best))
            sm16 = lambda im: np.asarray(im.convert('RGB').resize((16, 16), Image.BOX)).astype(float)
            sils.append(np.asarray(orig.getchannel('A').resize((16, 16), Image.BOX)) >= 200)
            origs.append(sm16(orig)); smalls.append(sm16(game))
            d, step = fi // 2, fi % 2
            fitted.alpha_composite(game.resize((160, 160), Image.LANCZOS), (12 + d * 172, 12 + step * 172))
            for k, im in enumerate((orig, art.crop((PAD, PAD, PAD + CELL, PAD + CELL)), game)):
                review.alpha_composite(im.resize((160, 160), Image.LANCZOS), (10 + k * (4 * 170 + 15) + d * 170, 5 + step * 170))
        # a frame drawn facing the wrong way can still fit the outline: compare
        # each frame's colours (16x16, inside the outline) with every original
        err = np.zeros((8, 8))
        for i in range(8):
            for j in range(8):
                si = sils[j]; d = np.abs(smalls[i] - origs[j])[si].mean() if si.any() else 0
                err[i, j] = d
        def odiff(k, j): return np.abs(origs[k] - origs[j])[sils[k] | sils[j]].mean() if (sils[k] | sils[j]).any() else 0
        swapped = [k for k in range(8) if err[k].argmin() != k and err[k, k] > 1.5 * err[k].min() + 8
                   and odiff(k, int(err[k].argmin())) > 12]      # frames that really differ
        worst_drawn = min(a for a, b in scores); worst_fit = min(b for a, b in scores)
        name = lambda i: f'{["up","right","down","left"][i // 2]}{i % 2 + 1}'
        verdict = 'ok' if worst_drawn >= OK else 'fitted' if worst_fit >= FIT else 'redo'
        bad = [name(i) for i, (a, b) in enumerate(scores) if b < FIT]
        if swapped:
            verdict = 'redo'; bad += [f'{name(k)} looks like {name(int(err[k].argmin()))}' for k in swapped]
        fitted.save(os.path.join(out, 'fitted', cid + '.png')); review.save(os.path.join(out, 'review', cid + '.png'))
        report.append([cid, verdict, f'{worst_drawn:.2f}', f'{worst_fit:.2f}', ' '.join(bad), note.strip('; ')])
        print(f'{cid}: {verdict}  (worst frame as drawn {worst_drawn:.2f}, fitted {worst_fit:.2f}) {" ".join(bad)} {note}')
    with open(os.path.join(out, 'report.csv'), 'w', newline='') as f:
        w = csv.writer(f); w.writerow(['id', 'verdict', 'worst_iou_as_drawn', 'worst_iou_fitted', 'frames_to_fix', 'note'])
        w.writerows(report)

if __name__ == '__main__':
    main()
