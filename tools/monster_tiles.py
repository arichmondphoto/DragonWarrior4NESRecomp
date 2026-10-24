"""Extract a battle monster's tiles from a capture_monsters.py dump.

Background: nametable cells above the command windows (rows 0-17) whose tile
number is >= $8D (lower numbers are the font and window frame), keyed by the
tile's 16 CHR bytes (BG pattern table $1000) and its 4-colour sub-palette.

Sprites: every visible OAM entry. In battle Dragon Warrior IV uses 8x8 sprites
from pattern table $0000 (verified pixel-exact against the screen). Sprite
keys use the HD-pack sprite palette form: $FF marker + the 3 sprite colours.

The monster's pixel box is the union of its BG cells and sprites; `image` is
the monster rendered as RGBA (transparent where nothing is drawn).
"""
import os, sys
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load, tile_pixels

FIRST_MONSTER_TILE = 0x8D

def monster(mem_path, png_path=None):
    m = load(mem_path)
    ci, chr_ram, pal, oam = m['ciram'], m['chr_ram'], m['palette'], m['oam']
    bg = {}
    for r in range(18):
        for c in range(32):
            t = ci[r * 32 + c]
            if t < FIRST_MONSTER_TILE: continue
            a = ci[0x3C0 + (r // 4) * 8 + c // 4]
            sub = (a >> (((r % 4) // 2) * 4 + ((c % 4) // 2) * 2)) & 3
            p = bytes([pal[0], pal[sub * 4 + 1], pal[sub * 4 + 2], pal[sub * 4 + 3]])
            bg[(r, c)] = (0x100 + t, bytes(chr_ram[0x1000 + 16 * t: 0x1000 + 16 * t + 16]), p)
    spr = []
    for k in range(0, 256, 4):
        y, t, a, x = oam[k:k + 4]
        if y >= 0xEF: continue
        so = 0x10 + (a & 3) * 4
        p = bytes([0xFF, pal[so + 1], pal[so + 2], pal[so + 3]])
        spr.append({'x': x, 'y': y + 1, 'tile': t, 'data': bytes(chr_ram[16 * t: 16 * t + 16]), 'pal': p,
                    'hflip': bool(a & 0x40), 'vflip': bool(a & 0x80), 'behind': bool(a & 0x20)})
    if not bg and not spr: return None
    xs = [c * 8 for _, c in bg] + [s['x'] for s in spr]
    ys = [r * 8 for r, _ in bg] + [s['y'] for s in spr]
    x0, y0 = min(xs), min(ys)
    x1 = max([c * 8 + 8 for _, c in bg] + [s['x'] + 8 for s in spr])
    y1 = max([r * 8 + 8 for r, _ in bg] + [s['y'] + 8 for s in spr])
    img = None
    if png_path:
        shot = Image.open(png_path).convert('RGBA')
        img = Image.new('RGBA', (x1 - x0, y1 - y0), (0, 0, 0, 0))
        for (r, c), (t, data, p) in bg.items():
            pix = tile_pixels(chr_ram, t)              # t already includes the $1000 table
            for yy in range(8):
                for xx in range(8):
                    if pix[yy][xx]:
                        img.putpixel((c * 8 + xx - x0, r * 8 + yy - y0), shot.getpixel((c * 8 + xx, r * 8 + yy)))
        for s in spr:
            pix = tile_pixels(chr_ram, s['tile'])
            for yy in range(8):
                for xx in range(8):
                    v = pix[7 - yy if s['vflip'] else yy][7 - xx if s['hflip'] else xx]
                    sx, sy = s['x'] + xx, s['y'] + yy
                    if v and sx < 256 and sy < 240:
                        img.putpixel((sx - x0, sy - y0), shot.getpixel((sx, sy)))
    return {'bg': bg, 'spr': spr, 'box': (x0, y0, x1, y1), 'image': img}
