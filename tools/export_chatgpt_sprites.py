"""Package the walking characters for ChatGPT image generation.

Same characters as tools/export_ai_sprites.py, laid out for ChatGPT's own
canvas so nothing is resized or cropped on the way in or out:

  * every input is 1536x1024 (ChatGPT's 3:2 size); the 8 frames sit in a
    4x2 grid of 336x336 cells (each 16x16 frame scaled 21x, pixel-exact) at
    fixed positions (LAYOUT below; tools/check_ai_sprites.py uses the same);
  * flat grey background (#8C8C8C), no lines or text for the model to copy;
  * a ready-to-paste prompt per character, and project instructions that
    hold the rules every prompt repeats.

Writes OUT/ (and OUT.zip):
  inputs/<ID>.png              the sheet to attach
  silhouettes/<ID>.png         black-on-white outline of each frame (optional 3rd image)
  prompts/<ID>.txt             the message to send with it
  optional/                    the same for shadows, sparkles and effects
  style_reference.png, characters.csv, PROJECT_INSTRUCTIONS.txt, README.txt

usage: export_chatgpt_sprites.py CHARACTERS_JSON OUT
"""
import csv, json, os, shutil, sys
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from sprite_sheet import frame_image
from export_ai_sprites import WHO, HERE

W, H = 1536, 1024
SCALE = 21; CELL = 16 * SCALE                       # 336
X0, XG = 39, 38                                     # 39 + 4*336 + 3*38 + 39 = 1536
Y0, YG = 117, 118                                   # 117 + 2*336 + 118 + 117 = 1024
GREY = (140, 140, 140)
DIRS = ['up', 'right', 'down', 'left']

def cell_origin(frame):
    """Frame index (dir*2 + step) -> top-left of its cell."""
    d, step = frame // 2, frame % 2
    return X0 + d * (CELL + XG), Y0 + step * (CELL + YG)

# shadows, sparkles and effects: fine to leave 8-bit; drawn last if at all
OPTIONAL_TYPES = {0x0E, 0x30, 0x58, 0x59, 0x5A, 0x5F, 0x60, 0x61}

PROMPT = """Redraw Image 1 as a high-resolution, hand-painted version in the art style of Image 2.

Subject: {who}.
Image 1 is a top-down RPG walking sprite sheet: 8 frames in a 4 x 2 grid. Columns: facing up, facing right, facing down, facing left. Rows: walking step 1, walking step 2.

Hard rules:
1. Output exactly 1536 x 1024. Keep the same grid: every frame stays in its own square at exactly the same position and size as in Image 1. Do not move, resize, crop, merge, add or remove frames.
2. Trace each frame: keep the 8-bit sprite's exact silhouette, pose and proportions. Fill the whole silhouette and do not paint outside it.{sil}
3. Keep Image 1's colour scheme: the same colours in the same places.
4. It is the same character in all 8 frames: same face, outfit and details. Do not redesign it; add painted detail, soft shading and crisp dark outlines only.
5. Background: transparent. If transparency isn't possible, flat grey #8C8C8C. No shadows, ground, scenery, borders, grid lines, labels or text.
"""
SIL = " Image 3 shows each frame's exact silhouette in black."

INSTRUCTIONS = """You redraw 8-bit Dragon Warrior IV (NES) walking sprites as high-resolution, hand-painted art for an HD texture pack. Each request attaches:
  Image 1 - the 8-bit sheet to redraw (1536 x 1024, 4 x 2 grid of square frames on flat grey)
  Image 2 - the style reference (hand-painted monster art from the same pack)
  Image 3 (sometimes) - each frame's silhouette in black

Every result is cut back into frames by position and laid over the original sprite in the game, which only shows the art inside the original 8-bit outline. So these rules always apply:
  - Output exactly 1536 x 1024, one image, nothing else.
  - Same grid as Image 1: each frame in the same place at the same size. Never rearrange, resize, crop, add or drop frames.
  - Keep each frame's silhouette, pose and proportions exactly (trace the outline); fill it completely; nothing outside it.
  - Keep the colours of Image 1 in the same places.
  - One consistent character across all 8 frames; do not redesign it.
  - Style from Image 2: painterly shading, crisp dark outlines, rich but not neon colours.
  - Transparent background (or flat grey #8C8C8C). No shadows, ground, borders, grid lines, labels or text.
Generate the image directly; don't ask questions or describe a plan first.
"""

README = """Dragon Warrior IV characters - package for ChatGPT
==================================================

{n} characters to draw (inputs/ + prompts/), plus {k} optional effects
(optional/: shadows, sparkles - fine to leave 8-bit).

Set up once
  1. In ChatGPT make a Project (e.g. "DW4 sprites"). Paste
     PROJECT_INSTRUCTIONS.txt into the project's instructions and add
     style_reference.png to the project files.
  2. Choose the image model/quality ChatGPT offers for the highest fidelity.

For each character (one NEW chat per character, inside the project)
  1. Attach inputs/<ID>.png first, then style_reference.png
     (and silhouettes/<ID>.png third if the outline keeps drifting).
  2. Paste prompts/<ID>.txt as the message.
  3. Download the result as <ID>.png (PNG, keep the transparency). If the
     grid moved or the character changed, regenerate - don't fix it by
     follow-up edits in the same chat; a fresh chat drifts less.
  A new chat per character keeps earlier characters out of the result.

Start with a pilot of 3 (C007 Ragnar, C017 a priest, C042 the slime) and send
them back before doing the rest: they are checked and fitted
automatically (tools/check_ai_sprites.py), and the report says which pass,
which were nudged into place, and which to redo.

What "accurate" means here
  The game draws your art only inside the original 8-bit outline of each
  frame, so the outline, pose and position matter more than anything else.
  Small drift (a few pixels, slightly bigger or smaller) is fitted
  automatically; a wrong pose, a missing frame or a moved grid needs a redo.

characters.csv: id, what it is, where it appears, and whether it's optional.
"""

def main():
    rows = json.load(open(sys.argv[1])); out = sys.argv[2]
    if os.path.exists(out): shutil.rmtree(out)
    for sub in ('', 'optional/'):
        for d in ('inputs', 'silhouettes', 'prompts'): os.makedirs(os.path.join(out, sub + d))
    n = k = 0
    with open(os.path.join(out, 'characters.csv'), 'w', newline='') as f:
        wr = csv.writer(f); wr.writerow(['id', 'description', 'optional', 'appears_in'])
        for r in rows:
            if r.get('art_from'): continue
            types = r.get('types', [])
            who = WHO.get(types[0], '') if types else 'faint sparkles seen on the overworld at night'
            opt = not types or types[0] in OPTIONAL_TYPES
            sub = 'optional/' if opt else ''
            cols = [bytes.fromhex(c) for c in r['versions'][0]['colours']]
            sheet = Image.new('RGBA', (W, H), GREY + (255,))
            sil = Image.new('RGBA', (W, H), (255, 255, 255, 255))
            for fi, fr in enumerate(r['frames']):
                img = frame_image([(bytes.fromhex(c), a) for c, a in fr], cols[fi * 4:fi * 4 + 4], SCALE)
                sheet.alpha_composite(img, cell_origin(fi))
                black = Image.new('RGBA', img.size, (0, 0, 0, 255)); black.putalpha(img.getchannel('A'))
                sil.alpha_composite(black, cell_origin(fi))
            sheet.convert('RGB').save(os.path.join(out, sub + 'inputs', r['id'] + '.png'))
            sil.convert('RGB').save(os.path.join(out, sub + 'silhouettes', r['id'] + '.png'))
            open(os.path.join(out, sub + 'prompts', r['id'] + '.txt'), 'w').write(PROMPT.format(who=who, sil=''))
            open(os.path.join(out, sub + 'prompts', r['id'] + '_with_silhouette.txt'), 'w').write(PROMPT.format(who=who, sil=SIL))
            wr.writerow([r['id'], who, 'yes' if opt else '', '; '.join(r['maps']) or 'not reached by the route'])
            k += opt; n += not opt
    shutil.copy(os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), 'characters.png'), os.path.join(out, 'characters.png')) \
        if os.path.exists(os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), 'characters.png')) else None
    # style reference at ChatGPT's square size
    b = json.load(open(os.path.join(HERE, 'hd/monsters/boxes.json')))
    src = Image.open(os.path.join(HERE, 'hd/monsters/source/DW4Sprites.jpg')).convert('RGB')
    ref = Image.new('RGB', (1024, 1024), GREY)
    for i, s in enumerate((0, 9, 20, 28, 40, 60, 75, 140, 33)):
        im = src.crop(b[s]); im.thumbnail((320, 320))
        ref.paste(im, ((i % 3) * 341 + (341 - im.width) // 2, (i // 3) * 341 + (341 - im.height) // 2))
    ref.save(os.path.join(out, 'style_reference.png'))
    open(os.path.join(out, 'PROJECT_INSTRUCTIONS.txt'), 'w').write(INSTRUCTIONS)
    open(os.path.join(out, 'README.txt'), 'w').write(README.format(n=n, k=k))
    shutil.make_archive(out, 'zip', os.path.dirname(out), os.path.basename(out))
    print(f'{n} characters + {k} optional -> {out} (+ .zip)')

if __name__ == '__main__':
    main()
