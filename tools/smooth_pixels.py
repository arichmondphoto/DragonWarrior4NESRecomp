"""Smooth upscaling of 1-bit pixel art (8x8 NES tiles) to anti-aliased HD masks.

Scale2x (EPX) twice gives a 4x bitmap whose diagonals are already stepped
in the artist's intent; a supersampled blur + threshold then rounds every
contour, and a final downsample anti-aliases the edge. Shapes, stroke
positions and spacing stay exactly where the original pixels put them.
"""
from PIL import Image, ImageFilter

def scale2x(g):
    h, w = len(g), len(g[0]); out = [[0] * (2 * w) for _ in range(2 * h)]
    at = lambda y, x: g[y][x] if 0 <= y < h and 0 <= x < w else 0
    for y in range(h):
        for x in range(w):
            p = g[y][x]; A, B, C, D = at(y - 1, x), at(y, x + 1), at(y, x - 1), at(y + 1, x)
            e0 = e1 = e2 = e3 = p
            if C == A and C != D and A != B: e0 = A
            if A == B and A != C and B != D: e1 = B
            if D == C and D != B and C != A: e2 = C
            if B == D and B != A and D != C: e3 = D
            out[2*y][2*x], out[2*y][2*x+1], out[2*y+1][2*x], out[2*y+1][2*x+1] = e0, e1, e2, e3
    return out

PAD = 4

def pad(bits, mode):
    """Surround an 8x8 tile with PAD pixels: 'zero' (isolated glyphs) or
    'edge' (window pieces whose lines continue into the neighbouring tile)."""
    n = len(bits)
    def at(y, x):
        if mode == 'edge':
            return bits[min(max(y, 0), n - 1)][min(max(x, 0), n - 1)]
        return bits[y][x] if 0 <= y < n and 0 <= x < n else 0
    return [[at(y, x) for x in range(-PAD, n + PAD)] for y in range(-PAD, n + PAD)]

def smooth_mask(bits, S=32, roundness=0.9, weight=0.0, mode='zero'):
    """bits: 8x8 list of 0/1. Returns an L image S x S (alpha mask).
    weight > 0 thickens strokes slightly, < 0 thins them."""
    g = scale2x(scale2x(pad(bits, mode)))            # 4x, with context
    n = len(g)
    # Supersample so the final downsample has >= 3 source pixels per output
    # pixel at any scale (32 px of Scale2x output per tile -> S px).
    up = max(8, -(-S * 3 // 32))
    im = Image.new('L', (n, n))
    im.putdata([255 if v else 0 for row in g for v in row])
    big = im.resize((n * up, n * up), Image.NEAREST)
    big = big.filter(ImageFilter.GaussianBlur(radius=roundness * up))
    thr = int(128 - weight * 60)
    big = big.point(lambda v: 255 if v >= thr else 0)
    o = PAD * 4 * up                                 # crop the context away
    big = big.crop((o, o, o + 32 * up, o + 32 * up))
    return big.resize((S, S), Image.LANCZOS)
