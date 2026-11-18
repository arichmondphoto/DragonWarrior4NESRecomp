#!/usr/bin/env python3
"""Package the title-screen art still to paint, for OpenAI's image API
(tools/openai_sprites.py), the same way as the other graphics:

  sky/     SKY.png           the sky painting (with the castle) widened to
                             16:9. The painting stays as it is in the middle;
                             only the two sides are painted (masks/SKY.png),
                             continuing the sky, the castle's hill and the
                             cloud sea.
  clouds/  CLOUDS_BACK.png   each moving cloud strip made twice as long
           CLOUDS_FRONT.png  (512 native pixels instead of 256), and seamless:
                             the strip's two halves are put at the ends with a
                             gap between them, and only the gap is painted
                             (masks/), so the ends already join (they are
                             neighbouring columns of the painting) and the new
                             clouds join both halves. The old join, where the
                             strip's ends were blended together, is gone.

Nothing else changes: the plate, the lettering and the look of the sky and
clouds are the owner's paintings as they are. The sunset versions are all
that is needed (the blue-sky versions are recoloured at build time).

Afterwards tools/import_title_ai.py takes the results into hd/title/layers/
(and layout.json), putting the kept parts back exactly.

usage: export_title_ai.py OUT        (e.g. out/DW4_title_for_OpenAI)
"""
import json, os, shutil, sys
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.abspath(__file__))
LAYERS = os.environ.get('DW4_TITLE_LAYERS') or os.path.join(HERE, 'hd', 'title', 'layers')   # (env: tests)

# The layers' canvas is the screen at 5x (1280x1200 = 256x240). Widescreen is
# 426 native columns: 85 more on each side.
K = 5
SIDE = 85 * K                     # 425
SKY_W, SKY_H = 2144, 1200         # sent size (multiple of 16); 2130 used
SKY_X = (SKY_W - 1280) // 2       # 432: where the painting sits
OVERLAP = 40                      # px of the kept part the model may touch, to blend

STRIP = 1280                      # a cloud strip now: 256 native
PERIOD = 2 * STRIP                # the new one: 512 native
CLOUD_H = 864                     # canvas height: 2560x864 keeps within 3:1
HALF = STRIP // 2                 # 640
C_OVERLAP = 48

SKY_RULES = """You extend a hand-painted fantasy illustration, the title screen of Dragon Warrior IV, to a wider picture for an HD texture pack.
Only the transparent part of the mask is painted: the two sides. The middle is the existing painting and must stay exactly as it is.
Generate the image directly."""
SKY_PROMPT = """Image 1 is the title-screen painting (a red sunset sky full of streaked clouds, a dark castle on a rocky hill at the right, a glowing misty horizon over calm water along the bottom) with an empty band on the left and on the right. Paint those two side bands so the picture becomes one wide 16:9 painting.
Continue everything across the borders seamlessly, in exactly the same painting style, brush texture, colours and light as the middle and as Image 2 (the finished title screen):
- the sky: the same red sunset with the same streaky cloud texture and the same darker top and brighter band above the horizon; no new sun, moon, stars or birds;
- the castle's rocky hill on the right: let its slope run down out of the picture's middle to the right and sink into the sea of clouds; no second castle, no towers, buildings or walls in the side bands;
- the glowing misty horizon and the water below it continue on both sides at the same height (in the game a band of moving clouds covers this part).
No text, no frame, no border, no vignette. Same size as Image 1 (2144 x 1200)."""

CLOUD_RULES = """You extend a horizontal strip of painted clouds from the title screen of Dragon Warrior IV (an HD texture pack). The strip scrolls sideways and repeats.
Only the transparent part of the mask is painted: the gap in the middle of the strip. The clouds at the two ends must stay exactly as they are.
Generate the image directly."""
CLOUD_PROMPT = """Image 1 holds one strip of a sunlit sea of golden clouds along its bottom edge ({h} px tall, the whole width), with a gap in its middle. Everything above the strip is transparent.
Fill the gap with new clouds so the strip is one continuous band: the new clouds must join the clouds on the left of the gap and the clouds on the right of the gap with no visible seam.
Match the strip exactly: the same painting style and brush texture, the same golden, cream and lilac colours and light, the same size of cloud puffs, and the same outline along the top (cloud tops rising and falling within the strip's top part, the strip solid below them, down to the bottom edge). Paint different cloud shapes from the ones at the ends (no copies).
Keep the area above the cloud tops transparent; nothing above the strip, nothing in the sky: no castle, no hills, no text. Image 2 is the finished title screen, for the look. Same size as Image 1 ({w} x {H})."""

README = """Dragon Warrior IV - title screen: widescreen sky and seamless clouds
====================================================================

Three pictures, painted by OpenAI's image API the same way as the other
graphics. Each keeps the existing painting and only fills in what is new
(the mask in each folder says which part):

  sky/      the sky with the castle, widened to 16:9 (the two sides)
  clouds/   the two moving cloud strips, made twice as long and seamless

In Terminal, in this folder:

  export OPENAI_API_KEY=sk-...
  python3 openai_sprites.py --folder sky --dry-run      # what it would send
  python3 openai_sprites.py --folder sky
  python3 openai_sprites.py --folder clouds

Each folder's results land in <folder>/generated/results/. To try again,
add --redo (or --variants 3 for three choices; keep the one you like as
generated/results/<NAME>.png). About $0.10-0.30 per picture at --quality high.

Then send back the folder (or just sky/generated and clouds/generated). On
the build machine:

  python3 tools/import_title_ai.py out/DW4_title_for_OpenAI

puts them into hd/title/layers/ (the sky's painting restored exactly; each
cloud strip is the AI's alone, made to repeat on its own) and writes previews
to look at before building the pack.
"""


def save(a, path):
    Image.fromarray(np.clip(np.round(a), 0, 255).astype(np.uint8), 'RGBA' if a.shape[2] == 4 else 'RGB').save(path)


def pkg(d, rules, background, style):
    for sub in ('inputs', 'prompts', 'masks', 'preview'): os.makedirs(os.path.join(d, sub), exist_ok=True)
    open(os.path.join(d, 'PROJECT_INSTRUCTIONS.txt'), 'w').write(rules)
    json.dump({'background': background}, open(os.path.join(d, 'settings.json'), 'w'))
    style.save(os.path.join(d, 'style_reference.png'))


def mask(w, h, edit):
    """An RGBA mask: opaque = keep, transparent = paint. edit(x, y) -> bool array."""
    m = np.full((h, w, 4), 255, np.uint8)
    m[edit, 3] = 0
    return Image.fromarray(m, 'RGBA')


def style_image():
    """The finished title (the owner's composite), at the API's usual size."""
    t = Image.open(os.path.join(LAYERS, 'template.png')).convert('RGB')
    return t.resize((1280, 1200), Image.LANCZOS)


def sky(out):
    d = os.path.join(out, 'sky'); pkg(d, SKY_RULES, 'opaque', style_image())
    lay = json.load(open(os.path.join(LAYERS, 'layout.json')))
    spec = next(l for l in lay['layers'] if l['name'] == 'sky')
    src = np.asarray(Image.open(os.path.join(LAYERS, spec['files']['sunset'])).convert('RGB')).astype(float)
    assert src.shape[:2] == (1200, 1280), src.shape
    # the sides start as the painting's edge colours, blurred (a hint of the
    # colours; the mask lets the model paint them over)
    a = np.zeros((SKY_H, SKY_W, 3))
    a[:, SKY_X:SKY_X + 1280] = src
    a[:, :SKY_X] = src[:, :1][:, [0] * SKY_X]
    a[:, SKY_X + 1280:] = src[:, -1:][:, [0] * (SKY_W - SKY_X - 1280)]
    hint = np.asarray(Image.fromarray(a.astype(np.uint8)).filter(ImageFilter.GaussianBlur(60))).astype(float)
    a[:, :SKY_X] = hint[:, :SKY_X]; a[:, SKY_X + 1280:] = hint[:, SKY_X + 1280:]
    save(a, os.path.join(d, 'inputs', 'SKY.png'))
    x = np.arange(SKY_W)[None, :].repeat(SKY_H, 0)
    edit = (x < SKY_X + OVERLAP) | (x >= SKY_X + 1280 - OVERLAP)
    mask(SKY_W, SKY_H, edit).save(os.path.join(d, 'masks', 'SKY.png'))
    open(os.path.join(d, 'prompts', 'SKY.txt'), 'w').write(SKY_PROMPT)
    # for a person: the painted parts marked
    g = a.copy(); g[edit] = g[edit] * 0.45 + np.array([40, 160, 255]) * 0.55
    gi = Image.fromarray(g.astype(np.uint8)); gi.thumbnail((1072, 600)); gi.save(os.path.join(d, 'preview', 'SKY_painted_part_in_blue.png'))
    return 1


def clouds(out):
    d = os.path.join(out, 'clouds'); pkg(d, CLOUD_RULES, 'transparent', style_image())
    lay = json.load(open(os.path.join(LAYERS, 'layout.json')))
    n = 0
    for name, cid in (('clouds_back', 'CLOUDS_BACK'), ('clouds_front', 'CLOUDS_FRONT')):
        spec = next(l for l in lay['layers'] if l['name'] == name)
        src = np.asarray(Image.open(os.path.join(LAYERS, spec['files']['sunset'])).convert('RGBA')).astype(float)
        h = src.shape[0]; assert src.shape[1] == STRIP, src.shape
        a = np.zeros((CLOUD_H, PERIOD, 4))
        y0 = CLOUD_H - h
        # the strip's second half at the left end, its first half at the right
        # end: column PERIOD-1 (strip x 639) meets column 0 (strip x 640) when it
        # repeats, so the ends join already; the gap between them is painted
        a[y0:, :HALF] = src[:, HALF:]
        a[y0:, PERIOD - HALF:] = src[:, :HALF]
        save(a, os.path.join(d, 'inputs', cid + '.png'))
        yy, xx = np.mgrid[0:CLOUD_H, 0:PERIOD]
        edit = (yy >= y0) & (xx >= HALF - C_OVERLAP) & (xx < PERIOD - HALF + C_OVERLAP)
        mask(PERIOD, CLOUD_H, edit).save(os.path.join(d, 'masks', cid + '.png'))
        open(os.path.join(d, 'prompts', cid + '.txt'), 'w').write(CLOUD_PROMPT.format(h=h, w=PERIOD, H=CLOUD_H))
        g = a[y0:].copy(); g[..., :3] = g[..., :3] * g[..., 3:] / 255 + np.array([30, 30, 60]) * (1 - g[..., 3:] / 255); g[..., 3] = 255
        e = edit[y0:]; g[e, :3] = g[e, :3] * 0.45 + np.array([40, 160, 255]) * 0.55
        gi = Image.fromarray(g.astype(np.uint8)); gi.thumbnail((1280, 400)); gi.save(os.path.join(d, 'preview', cid + '_painted_part_in_blue.png'))
        n += 1
    return n


def main():
    if len(sys.argv) != 2: sys.exit(__doc__)
    out = sys.argv[1]
    if os.path.exists(out): shutil.rmtree(out)
    os.makedirs(out)
    n = sky(out) + clouds(out)
    shutil.copy(os.path.join(TOOLS, 'openai_sprites.py'), os.path.join(out, 'openai_sprites.py'))
    open(os.path.join(out, 'README.txt'), 'w').write(README)
    shutil.make_archive(out, 'zip', os.path.dirname(os.path.abspath(out)), os.path.basename(out))
    print(f'{n} pictures -> {out} (+ .zip)')


if __name__ == '__main__':
    main()
