"""Export a template kit for painting the title screen in layers.

The title is rebuilt from separate pictures (tools/make_title_hdpack.py):
sky, castle, clouds (each in a day and a sunset version), the blank stone
plate and its lettering. This writes the guides to paint them on:

  guide_day.png / guide_sunset.png   the game's title (frames 1530 / 2400) at 10x
  guide_*_marked.png                 the same with the guide lines drawn on
  guides_overlay.png                 the guide lines alone (transparent)
  templates/*.png                    empty 2560x2400 canvases, one per layer
  reference_current_title.png        the current single-picture title
  README.txt                         what each layer must be

Measured from the game (headless, frames 2401-2560): the screen above y=195 is
still; scanlines 195-210 scroll left 1 px every 4 frames, 211-239 1 px every
2 frames; every row wraps at 256 px (one screen width).

usage: export_title_kit.py HOST OUTDIR
"""
import json, os, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw, ImageFont
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from field_sheet import NES
from make_title_hdpack import cells, pixels

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM = os.path.join(HERE, 'rom', 'DragonWarriorIV.nes')
S = 10
BANDS = [(0, 195, 'still'), (195, 211, 'band A: moves left 1 px every 4 frames'),
         (211, 240, 'band B: moves left 1 px every 2 frames')]
LAYERS = ['sky_day', 'sky_sunset', 'castle_day', 'castle_sunset', 'clouds_day', 'clouds_sunset', 'plate', 'lettering']

def font(size):
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf'):
        if os.path.exists(p): return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)

def main():
    host, out = sys.argv[1], sys.argv[2]
    os.makedirs(os.path.join(out, 'templates'), exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='dw4kit')
    shots = {}
    for f in (700, 1530, 2400):
        mods = tempfile.mkdtemp(prefix='mods', dir=tmp)
        png, mem = os.path.join(tmp, f'{f}.png'), os.path.join(tmp, f'{f}.mem')
        subprocess.run([host, ROM, '--frames', str(f + 1), '--no-save', '--mods-root', mods, '--screenshot', png,
                        '--mem-frame', str(f), '--mem-out', mem], check=True, capture_output=True)
        shots[f] = (png, mem)
    up = lambda p: Image.open(p).convert('RGB').resize((256 * S, 240 * S), Image.NEAREST)
    day, sunset = up(shots[1530][0]), up(shots[2400][0])
    day.save(os.path.join(out, 'guide_day.png')); sunset.save(os.path.join(out, 'guide_sunset.png'))

    # where things are on the finished screen
    fin, blank = cells(shots[2400][1]), cells(shots[700][1])
    letter = np.zeros((240, 256), bool)
    for k, (c, pal, p) in fin.items():
        if blank[k][0] != c: letter[k[1] * 8:k[1] * 8 + 8, k[0] * 8:k[0] * 8 + 8] = pixels(c) != pixels(blank[k][0])
    def bbox(m):
        ys, xs = np.nonzero(m); return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    words = {'DRAGON': letter[47:68, 40:124], 'WARRIOR': letter[47:68, 124:212], 'TM': letter[36:47, 188:212],
             'IV': letter[68:110, 100:156]}
    offs = {'DRAGON': (40, 47), 'WARRIOR': (124, 47), 'TM': (188, 36), 'IV': (100, 68)}
    boxes = {}
    for w, m in words.items():
        x0, y0, x1, y1 = bbox(m); ox, oy = offs[w]; boxes[w] = (x0 + ox, y0 + oy, x1 + ox, y1 + oy)
    plate = [k for k, (c, pal, p) in fin.items() if p == 3 and pixels(c).any()]
    pb = (min(t[0] for t in plate) * 8, min(t[1] for t in plate) * 8, (max(t[0] for t in plate) + 1) * 8, (max(t[1] for t in plate) + 1) * 8)
    # castle and its hill: the 8-bit picture's dark red ($06) and orange ($26) pixels
    shot = np.asarray(Image.open(shots[2400][0]).convert('RGB')).astype(int)
    rgb = lambda c: np.array([(NES[c] >> 16) & 255, (NES[c] >> 8) & 255, NES[c] & 255])
    castle = np.zeros((240, 256), bool)
    for c in (0x06, 0x26): castle |= (np.abs(shot - rgb(c)).sum(-1) < 8)
    castle[200:] = False
    cb = bbox(castle)
    cloud = np.zeros((240, 256), bool)
    for k, (c, pal, p) in fin.items():
        if p == 0: cloud[k[1] * 8:k[1] * 8 + 8, k[0] * 8:k[0] * 8 + 8] = pixels(c) != 0
    cloud_top = int(np.nonzero(cloud.any(1))[0].min())

    # guide lines
    ov = Image.new('RGBA', (256 * S, 240 * S), (0, 0, 0, 0)); d = ImageDraw.Draw(ov)
    F, Fs = font(44), font(34)
    sc = lambda b: tuple(v * S for v in b)
    d.rectangle((0, 0, 8 * S - 1, 240 * S - 1), fill=(0, 0, 0, 110))
    d.text((12, 1180), 'hidden\nby the\ngame', font=Fs, fill=(255, 255, 255, 255))
    for (y0, y1, what), col in zip(BANDS, ((255, 255, 255), (0, 255, 255), (255, 0, 255))):
        if y0: d.line((0, y0 * S, 256 * S, y0 * S), fill=col + (255,), width=6)
        if y0: d.text((100, y0 * S + 10), f'y={y0 * S}: {what}', font=F, fill=col + (255,), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    d.line((0, cloud_top * S, 256 * S, cloud_top * S), fill=(255, 255, 0, 200), width=3)
    d.text((100, cloud_top * S - 56), f'y={cloud_top * S}: highest cloud tops (still part of the clouds is above y=1950)', font=Fs,
           fill=(255, 255, 0, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    d.rectangle(sc(pb), outline=(0, 255, 0, 255), width=8)
    d.text((pb[0] * S, pb[3] * S + 8), f'plate {pb[0] * S},{pb[1] * S} - {pb[2] * S},{pb[3] * S}', font=Fs, fill=(0, 255, 0, 255),
           stroke_width=3, stroke_fill=(0, 0, 0, 255))
    order = [('DRAGON', 'typed 1st'), ('WARRIOR', 'typed 2nd'), ('IV', 'appears with the sunset'), ('TM', 'appears with the sunset')]
    for w, when in order:
        b = boxes[w]; d.rectangle(sc(b), outline=(255, 160, 0, 255), width=5)
        d.text((b[0] * S, b[1] * S - 40 if w != 'IV' else b[3] * S + 6), f'{w}: {when}', font=Fs, fill=(255, 160, 0, 255),
               stroke_width=3, stroke_fill=(0, 0, 0, 255))
    d.rectangle(sc(cb), outline=(255, 80, 80, 255), width=6)
    d.text((cb[0] * S, cb[1] * S - 44), 'castle + hill (8-bit outline)', font=Fs, fill=(255, 80, 80, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
    ov.save(os.path.join(out, 'guides_overlay.png'))
    for name, im in (('day', day), ('sunset', sunset)):
        Image.alpha_composite(im.convert('RGBA'), ov).convert('RGB').save(os.path.join(out, f'guide_{name}_marked.png'))
    empty = Image.new('RGBA', (256 * S, 240 * S), (0, 0, 0, 0))
    for l in LAYERS: empty.save(os.path.join(out, 'templates', l + '.png'))
    cur = os.path.join(HERE, 'hd', 'title', 'TITLE.png')
    if os.path.exists(cur): Image.open(cur).convert('RGB').resize((256 * S, 240 * S), Image.LANCZOS).save(os.path.join(out, 'reference_current_title.png'))
    info = dict(canvas=[256 * S, 240 * S], plate=[v * S for v in pb], castle=[v * S for v in cb], cloud_top=cloud_top * S,
                bands=[dict(y0=a * S, y1=b * S, motion=w) for a, b, w in BANDS], letters={w: [v * S for v in b] for w, b in boxes.items()})
    json.dump(info, open(os.path.join(out, 'layout.json'), 'w'), indent=1)
    print(json.dumps(info))

if __name__ == '__main__':
    main()
