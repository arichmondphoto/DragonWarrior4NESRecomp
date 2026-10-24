"""Split a monster sprite sheet (black background) into one box per monster.

Foreground = any channel above a threshold; connected shapes inside each row
band are found, small detached bits (weapons, flames, sparks) are attached to
the nearest shape, and shapes whose horizontal extents overlap are merged.
Writes a JSON list of [x0, y0, x1, y1] boxes in reading order.

usage: split_sheet.py SHEET OUT.json [--preview PNG]
"""
import argparse, json
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

def boxes_for(sheet, thr=40):
    im = np.asarray(Image.open(sheet).convert('RGB')).astype(np.int16)
    fg = im.max(axis=2) > thr
    rows = ndimage.binary_closing(fg.sum(axis=1) > 3, iterations=15)
    lab, _ = ndimage.label(rows)
    out = []
    for (sl,) in ndimage.find_objects(lab):
        y0, y1 = sl.start, sl.stop
        band = ndimage.binary_closing(fg[y0:y1], iterations=4)
        cl, n = ndimage.label(band)
        objs = [s for s in ndimage.find_objects(cl)]
        bx = [[s[1].start, s[0].start, s[1].stop, s[0].stop, int((cl[s] > 0).sum())] for s in objs]
        big = [b for b in bx if b[4] > 4000]
        small = [b for b in bx if b[4] <= 4000]
        for b in small:                      # attach bits to the nearest big shape
            if not big: break
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            def dist(t):
                dx = max(t[0] - cx, 0, cx - t[2]); dy = max(t[1] - cy, 0, cy - t[3]); return dx * dx + dy * dy
            t = min(big, key=dist)
            if dist(t) < 120 ** 2:
                t[0], t[1], t[2], t[3] = min(t[0], b[0]), min(t[1], b[1]), max(t[2], b[2]), max(t[3], b[3])
        big.sort(key=lambda b: b[0])
        merged = []
        for b in big:                        # merge shapes stacked in one column
            if merged:
                m = merged[-1]
                ov = min(m[2], b[2]) - max(m[0], b[0])
                if ov > 0.5 * min(m[2] - m[0], b[2] - b[0]):
                    m[0], m[1], m[2], m[3] = min(m[0], b[0]), min(m[1], b[1]), max(m[2], b[2]), max(m[3], b[3]); continue
            merged.append(b[:4])
        out += [[x0, y0 + a, x1, y0 + c] for x0, a, x1, c in merged]
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('sheet'); ap.add_argument('out'); ap.add_argument('--preview')
    a = ap.parse_args()
    boxes = boxes_for(a.sheet)
    json.dump(boxes, open(a.out, 'w'))
    print(len(boxes), 'monsters')
    if a.preview:
        im = Image.open(a.sheet).convert('RGB'); d = ImageDraw.Draw(im)
        for i, (x0, y0, x1, y1) in enumerate(boxes):
            d.rectangle([x0, y0, x1, y1], outline=(255, 60, 60), width=8)
            d.text((x0 + 10, y0 + 6), str(i), fill=(255, 255, 0), font_size=64)
        im.resize((im.width // 4, im.height // 4), Image.LANCZOS).save(a.preview)

if __name__ == '__main__':
    main()
