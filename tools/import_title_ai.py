#!/usr/bin/env python3
"""Take the title pictures painted from tools/export_title_ai.py's package into
hd/title/layers/ and layout.json:

  sky_wide_sunset.png           2130x1200 (426 native columns at 5x): the
                                painted sides with the owner's painting put
                                back exactly in the middle (blended into the
                                sides over the 40 px the model was allowed to
                                touch); layout "wide" of the sky layer
  clouds_back_wide_sunset.png   2560 px strips (512 native) that repeat: the
  clouds_front_wide_sunset.png  painted gap with the strip's two halves put
                                back at the ends, then turned so the old strip
                                is where it was (x 0-1279) and the new clouds
                                follow it; layout "wide" of each cloud layer

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


def over(a, b, w):
    """b over a with weight w (per column), on RGBA (straight alpha)."""
    w = w[None, :, None]
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
        # the painting where it is, fading into the painted sides over the
        # overlap the model was allowed to touch
        w = np.minimum(ramp(SKY_W, SKY_X, SKY_X + OVERLAP), 1 - ramp(SKY_W, SKY_X + 1280 - OVERLAP, SKY_X + 1280))[None, :, None]
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
        h = src.shape[0]
        gen = load(res, 'RGBA', (PERIOD, CLOUD_H))[CLOUD_H - h:]
        if gen[..., 3].min() > 250:
            print(f'  {cid}: the result has no transparency (the sky above the clouds came back painted); '
                  'run it again with --redo, or check settings.json says transparent')
        ends = np.zeros_like(gen); ends[:, :HALF] = src[:, HALF:]; ends[:, PERIOD - HALF:] = src[:, :HALF]
        w = np.maximum(1 - ramp(PERIOD, HALF - C_OVERLAP, HALF), ramp(PERIOD, PERIOD - HALF, PERIOD - HALF + C_OVERLAP))
        out = over(gen, ends, w)
        out = np.roll(out, HALF, axis=1)            # the old strip back at x 0-1279
        assert np.abs(out[:, :STRIP] - src)[src[..., 3] > 0].max() < 1.0
        fn = name + '_wide_sunset.png'
        save(out, os.path.join(LAYERS, fn))
        specs[name]['wide'] = {'files': {'sunset': fn}, 'period': PERIOD,
                               'note': 'repeats every 2560 px (512 native); the first 1280 are the old strip'}
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
            y = specs[name]['at'][1]
            region = canvas[y:y + row.shape[0]]
            al = row[..., 3:] / 255; region[..., :3] = region[..., :3] * (1 - al) + row[..., :3] * al
        save(canvas[..., :3], os.path.join(prev, 'title_wide_sunset.png'))
    print('imported:', ', '.join(done), f'-> {LAYERS} (layout.json updated); previews in {prev}')
    print('next: rebuild the HD pack (bump HD_VERSION in package_macos_app.sh)')


if __name__ == '__main__':
    main()
