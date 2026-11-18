#!/usr/bin/env python3
"""Take the title pictures painted from tools/export_title_ai.py's package into
hd/title/layers/ and layout.json:

  sky_wide_sunset.png           2130x1200 (426 native columns at 5x): the
                                painted sides with the owner's painting put
                                back exactly in the middle; layout "wide" of
                                the sky layer
  clouds_back_wide_sunset.png   the AI's cloud strips as painted (none of the
  clouds_front_wide_sunset.png  old strips mixed in), made to repeat on their
                                own: their ends overlapped by 160 px and cut
                                along each row's best seam (2400 px = 480
                                native around); taller and placed higher than
                                the old strips where the clouds rise above
                                them; layout "wide" of each cloud layer

The model repaints the whole picture, not just the masked part, so its copy
of the kept painting only resembles it. Where the two meet, each row is cut
where they differ least (a seam found from row to row, as in image quilting),
within the strip the model was told to blend in and a little beyond, then
softened over 3 px: no cross-fade, which leaves see-through doubled cloud tops
where the outlines do not line up.

It also writes previews (OUT/preview/): the wide title as the pack will draw
it (sunset), and each strip repeated twice, to check the joins by eye.

usage: import_title_ai.py PACKAGE [--keep-old]
  PACKAGE: the export folder, with sky/generated/results/SKY.png and
  clouds/generated/results/CLOUDS_BACK.png, CLOUDS_FRONT.png (any of them)
"""
import json, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
WRAP = 160                    # columns of the AI strip's ends laid over each other to make it repeat
from export_title_ai import (LAYERS, SKY_W, SKY_H, SKY_X, OVERLAP, SIDE, STRIP, PERIOD, CLOUD_H, HALF, C_OVERLAP)


def load(path, mode, size):
    im = Image.open(path).convert(mode)
    if im.size != size:
        print(f'  {os.path.basename(path)}: {im.size[0]}x{im.size[1]}, resized to {size[0]}x{size[1]}')
        im = im.resize(size, Image.LANCZOS)
    return np.asarray(im).astype(float)


def ramp(n, x0, x1):
    """0 before x0, 1 after x1, linear between (over the columns 0..n-1)."""
    x = np.arange(n, dtype=float)
    return np.clip((x - x0) / max(1, x1 - x0), 0, 1)


def seam(kept, gen, x0, x1, kept_left, feather=3.0):
    """Weight of `kept` (H x W): 1 on its side of a cut that runs down the rows
    within columns x0..x1-1 where kept and gen differ least (each row's cut at
    most 1 column from the last row's), 0 on the other side, ramped over
    `feather` px."""
    def pm(a):
        if a.shape[2] == 4: return np.concatenate([a[..., :3] * a[..., 3:] / 255, a[..., 3:]], -1)
        return a
    err = np.abs(pm(kept[:, x0:x1]) - pm(gen[:, x0:x1])).sum(-1)
    err = (err + np.roll(err, 1, 1) + np.roll(err, -1, 1)) / 3          # a little context sideways
    h, n = err.shape
    cost = err.copy(); back = np.zeros((h, n), int)
    for y in range(1, h):
        prev = np.stack([np.r_[np.inf, cost[y - 1, :-1]], cost[y - 1], np.r_[cost[y - 1, 1:], np.inf]])
        k = prev.argmin(0); back[y] = np.arange(n) + k - 1; cost[y] += prev[k, np.arange(n)]
    cut = np.zeros(h, int); cut[-1] = cost[-1].argmin()
    for y in range(h - 1, 0, -1): cut[y - 1] = back[y, cut[y]]
    x = np.arange(kept.shape[1])[None, :]; c = (cut + x0)[:, None]
    w = np.clip((c - x) / feather + 0.5, 0, 1)
    return w if kept_left else 1 - w


def over(a, b, w):
    """b over a with weight w (per column, or per pixel), on RGBA (straight alpha)."""
    w = w[None, :, None] if w.ndim == 1 else w[..., None]
    al = a[..., 3:] * (1 - w) + b[..., 3:] * w
    rgb = (a[..., :3] * a[..., 3:] * (1 - w) + b[..., :3] * b[..., 3:] * w) / np.maximum(al, 1e-6)
    return np.concatenate([rgb, al], -1)


def save(a, path):
    Image.fromarray(np.clip(np.round(a), 0, 255).astype(np.uint8), 'RGBA' if a.shape[2] == 4 else 'RGB').save(path, optimize=True)


def main():
    if len(sys.argv) < 2: sys.exit(__doc__)
    pkg = sys.argv[1]
    lay_p = os.path.join(LAYERS, 'layout.json'); lay = json.load(open(lay_p))
    specs = {l['name']: l for l in lay['layers']}
    prev = os.path.join(pkg, 'preview'); os.makedirs(prev, exist_ok=True)
    done = []

    res = os.path.join(pkg, 'sky', 'generated', 'results', 'SKY.png')
    if os.path.exists(res):
        gen = load(res, 'RGB', (SKY_W, SKY_H))
        src = np.asarray(Image.open(os.path.join(LAYERS, specs['sky']['files']['sunset'])).convert('RGB')).astype(float)
        mid = np.zeros_like(gen); mid[:, SKY_X:SKY_X + 1280] = src
        # the painting where it is, joined to the painted sides along the
        # rows' best cuts near its edges
        band = 3 * OVERLAP
        w = np.minimum(seam(mid, gen, SKY_X + 1, SKY_X + band, False),
                       seam(mid, gen, SKY_X + 1280 - band, SKY_X + 1280 - 1, True))[..., None]
        out = gen * (1 - w) + mid * w
        x0 = SKY_X - SIDE
        out = out[:, x0:x0 + 1280 + 2 * SIDE]
        save(out, os.path.join(LAYERS, 'sky_wide_sunset.png'))
        specs['sky']['wide'] = {'files': {'sunset': 'sky_wide_sunset.png'}, 'at': [-SIDE, 0],
                                'note': 'the sky at 16:9 (426 native columns); the middle 1280 is sky_sunset.png'}
        done.append('sky')

    strips = {}
    for name, cid in (('clouds_back', 'CLOUDS_BACK'), ('clouds_front', 'CLOUDS_FRONT')):
        res = os.path.join(pkg, 'clouds', 'generated', 'results', cid + '.png')
        src = np.asarray(Image.open(os.path.join(LAYERS, specs[name]['files']['sunset'])).convert('RGBA')).astype(float)
        if not os.path.exists(res):
            strips[name] = None; continue
        h0 = src.shape[0]
        full = load(res, 'RGBA', (PERIOD, CLOUD_H))
        # the new clouds may rise above the old strip's top: keep those rows
        # too (the layer starts higher), or their tops are cut off flat
        rows = np.flatnonzero((full[..., 3] > 8).any(1))
        extra = max(0, (CLOUD_H - h0) - int(rows.min()) + 2) if len(rows) else 0
        h = h0 + extra
        gen = full[CLOUD_H - h:]
        if gen[..., 3].min() > 250:
            print(f'  {cid}: the result has no transparency (the sky above the clouds came back painted); '
                  'run it again with --redo, or check settings.json says transparent')
        # The AI's strip as it painted it, nothing of the old strip mixed in.
        # Its two ends nearly meet (they were painted from neighbouring columns
        # of the old strip) but not quite, so it is made to repeat on its own:
        # its last WRAP columns are laid over its first ones, each row cut where
        # the two agree best (seam(), as at any join), and the strip ends where
        # that overlap begins. Repeating, column period-1 is followed by the
        # columns that came after it in the painting.
        period = PERIOD - WRAP
        tail = np.zeros_like(gen); tail[:, :WRAP] = gen[:, period:]
        w = seam(tail, gen, 1, WRAP - 1, True)
        out = over(gen, tail, w)[:, :period]
        fn = name + '_wide_sunset.png'
        save(out, os.path.join(LAYERS, fn))
        x_at, y_at = specs[name]['at']
        specs[name]['wide'] = {'files': {'sunset': fn}, 'period': period, 'at': [x_at, y_at - extra],
                               'note': f'the AI strip alone, repeating every {period} px ({period // 5} native)'}
        strips[name] = out
        rep = np.concatenate([out, out], 1)
        bg = np.array([60, 40, 90.0]); al = rep[..., 3:] / 255
        save(rep[..., :3] * al + bg * (1 - al), os.path.join(prev, f'{name}_repeated_twice.png'))
        done.append(name)

    if not done: sys.exit(f'no results found under {pkg}/sky/generated/results or {pkg}/clouds/generated/results')
    json.dump(lay, open(lay_p, 'w'), indent=1); open(lay_p, 'a').write('\n')

    # the wide title as the pack draws it (sunset, clouds at scroll 0)
    skyp = os.path.join(LAYERS, 'sky_wide_sunset.png')
    if os.path.exists(skyp) and 'wide' in specs['sky']:
        canvas = np.asarray(Image.open(skyp).convert('RGBA')).astype(float)
        for nm, at in (('plate', 'plate'), ('lettering', 'lettering')):
            im = np.asarray(Image.open(os.path.join(LAYERS, specs[nm]['files']['all'])).convert('RGBA')).astype(float)
            x, y = specs[nm]['at']; x += SIDE
            region = canvas[y:y + im.shape[0], x:x + im.shape[1]]
            al = im[..., 3:] / 255; region[..., :3] = region[..., :3] * (1 - al) + im[..., :3] * al
        for name in ('clouds_back', 'clouds_front'):
            st = strips.get(name)
            if st is None:
                st = np.asarray(Image.open(os.path.join(LAYERS, specs[name]['files']['sunset'])).convert('RGBA')).astype(float)
            reps = int(np.ceil(canvas.shape[1] / st.shape[1])) + 1
            # native x 0 is strip x 0 at scroll 0: the side starts SIDE before it
            row = np.roll(np.concatenate([st] * reps, 1), SIDE, axis=1)[:, :canvas.shape[1]]
            y = specs[name]['wide']['at'][1] if strips.get(name) is not None else specs[name]['at'][1]
            region = canvas[y:y + row.shape[0]]
            al = row[..., 3:] / 255; region[..., :3] = region[..., :3] * (1 - al) + row[..., :3] * al
        save(canvas[..., :3], os.path.join(prev, 'title_wide_sunset.png'))
    print('imported:', ', '.join(done), f'-> {LAYERS} (layout.json updated); previews in {prev}')
    print('next: rebuild the HD pack (bump HD_VERSION in package_macos_app.sh)')


if __name__ == '__main__':
    main()
