"""Score a debug-mode HD render sweep (NESRECOMP_HDPACK_DEBUG=1).

For each monster, counts pixels the presenter painted magenta (BG tile with
no HD match) inside the monster's own BG cells and cyan (sprite with no HD
match) inside its pixel box. Anything non-zero is a piece of the original
monster that would still show its 8-bit pixels.

usage: score_hd_sweep.py CAPTURE SWEEP_DIR [--scale 10]
"""
import argparse, glob, os, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from monster_tiles import monster

ap = argparse.ArgumentParser(); ap.add_argument('capture'); ap.add_argument('sweep'); ap.add_argument('--scale', type=int, default=10)
a = ap.parse_args(); S = a.scale
bad = []
files = sorted(glob.glob(os.path.join(a.sweep, 'p*.png')))
for f in files:
    mid = int(os.path.basename(f)[1:4])
    m = monster(os.path.join(a.capture, f'{mid:03d}.mem'))
    im = np.asarray(Image.open(f).convert('RGB')).astype(int)
    mag = (im[..., 0] > 240) & (im[..., 1] < 20) & (im[..., 2] > 240)
    cyan = (im[..., 0] < 20) & (im[..., 1] > 240) & (im[..., 2] > 240)
    mbg = sum(int(mag[r * 8 * S:(r + 1) * 8 * S, c * 8 * S:(c + 1) * 8 * S].sum()) for (r, c) in m['bg'])
    x0, y0, x1, y1 = m['box']
    msp = int(cyan[y0 * S:y1 * S, x0 * S:x1 * S].sum())
    if mbg or msp: bad.append((mid, mbg // (S * S), msp // (S * S)))
print(f'{len(files)} monsters checked; {len(bad)} with original pixels still showing')
for mid, b, s in bad: print(f'  ID {mid}: {b} BG px, {s} sprite px (native)')
