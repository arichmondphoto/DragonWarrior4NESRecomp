"""Package the graphics the HD pack still lacks, for OpenAI's image API
(tools/openai_sprites.py, one sub-folder per kind, each with its own
style image and rules):

  monsters/     the battle monsters with no art (hd/monsters/mapping.json
                no_art), one 1024x1024 picture each
  effects/      shadows, sparkles and other map effects (the optional
                characters of tools/export_chatgpt_sprites.py)
  night_tiles/  the night-only map tiles (Endor's crowd, Monbaraba's
                audience), one sheet; style = the owner's map atlases
  doors/        the castle doors' opening animation (Burland Castle), the
                three in-between frames drawn between the owner's closed
                and open door art
  title/        the title screen (1280x1200)

usage: export_gaps.py BUILD_DIR OUT
  BUILD_DIR: a tools/build_hd_pack.sh output's parent (monster-capture,
  field-capture, sprite-capture), e.g. build/hd
"""
import collections, glob, json, os, shutil, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(__file__))
from monster_tiles import monster
from export_chatgpt_tiles import art_tiles, render_sheet, tile_image, W as TW, H as TH
from vramdump import load
from field_sheet import NES

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.dirname(os.path.abspath(__file__))
GREY = (140, 140, 140)

MONSTER_NAMES = {43: 'Arrop', 68: 'Infsnip', 83: 'Batoidei', 84: 'Giant Octopod', 87: 'Sea Worm', 105: 'Sea Lion',
                 114: 'Zapangler', 127: 'Necrodon', 189: 'Troubadour'}

def monster_style():
    b = json.load(open(os.path.join(HERE, 'hd/monsters/boxes.json')))
    src = Image.open(os.path.join(HERE, 'hd/monsters/source/DW4Sprites.jpg')).convert('RGB')
    ref = Image.new('RGB', (1024, 1024), GREY)
    for i, s in enumerate((0, 9, 20, 28, 40, 60, 75, 140, 33)):
        m = src.crop(b[s]); m.thumbnail((320, 320))
        ref.paste(m, ((i % 3) * 341 + (341 - m.width) // 2, (i // 3) * 341 + (341 - m.height) // 2))
    return ref

def write_pkg(d, instructions, settings):
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'PROJECT_INSTRUCTIONS.txt'), 'w').write(instructions)
    json.dump(settings, open(os.path.join(d, 'settings.json'), 'w'))
    for sub in ('inputs', 'prompts'): os.makedirs(os.path.join(d, sub), exist_ok=True)

# ---------------------------------------------------------------- monsters
MON_RULES = """You redraw 8-bit Dragon Warrior IV (NES) battle monsters as large hand-painted illustrations for an HD texture pack, in the exact style of Image 2 (the pack's other monsters).
Rules: one monster, centred, filling most of the 1024 x 1024 picture; same pose, silhouette, proportions and colours as Image 1; front view as in battle; transparent background; no ground, shadow, frame, text or extra creatures.
Generate the image directly."""
MON_PROMPT = """Redraw Image 1 as a high-resolution, hand-painted Dragon Quest monster illustration in the style of Image 2: {name}.
Keep exactly the pose, silhouette, proportions and colour scheme of the 8-bit sprite in Image 1 (it will be laid over it in the game), centred, filling most of the picture. Rich painterly shading, crisp dark outline, transparent background, nothing else."""

def monsters(build, out):
    d = os.path.join(out, 'monsters'); write_pkg(d, MON_RULES, {'background': 'transparent'})
    monster_style().save(os.path.join(d, 'style_reference.png'))
    ids = json.load(open(os.path.join(HERE, 'hd/monsters/mapping.json')))['no_art']['ids']
    n = 0
    for mid in ids:
        if mid not in MONSTER_NAMES: continue                  # 173: the capture is a shop, not a battle
        m = monster(os.path.join(build, 'monster-capture', f'{mid:03d}.mem'), os.path.join(build, 'monster-capture', f'{mid:03d}.png'))
        if not m: continue
        im = m['image']; k = max(1, min(820 // im.width, 820 // im.height))
        im = im.resize((im.width * k, im.height * k), Image.NEAREST)
        sheet = Image.new('RGBA', (1024, 1024), GREY + (255,)); sheet.alpha_composite(im, ((1024 - im.width) // 2, (1024 - im.height) // 2))
        sheet.convert('RGB').save(os.path.join(d, 'inputs', f'M{mid:03d}.png'))
        open(os.path.join(d, 'prompts', f'M{mid:03d}.txt'), 'w').write(MON_PROMPT.format(name=MONSTER_NAMES[mid]))
        n += 1
    return n

# ---------------------------------------------------------------- effects
def effects(build, out):
    tmp = tempfile.mkdtemp()
    subprocess.run([sys.executable, os.path.join(TOOLS, 'export_chatgpt_sprites.py'),
                    os.path.join(build, 'sprite-capture', 'characters.json'), os.path.join(tmp, 'pkg')], check=True, capture_output=True)
    src = os.path.join(tmp, 'pkg'); d = os.path.join(out, 'effects')
    write_pkg(d, open(os.path.join(src, 'PROJECT_INSTRUCTIONS.txt')).read(), {'background': 'transparent'})
    shutil.copy(os.path.join(src, 'style_reference.png'), d)
    for sub in ('inputs', 'prompts', 'silhouettes'):
        os.makedirs(os.path.join(d, sub), exist_ok=True)
        for f in os.listdir(os.path.join(src, 'optional', sub)): shutil.copy(os.path.join(src, 'optional', sub, f), os.path.join(d, sub))
    shutil.rmtree(tmp)
    return len(os.listdir(os.path.join(d, 'inputs')))

# ---------------------------------------------------------------- night tiles
NIGHT_RULES = """You redraw 8-bit Dragon Warrior IV (NES) map tiles as hand-painted HD map tiles that must match the existing HD tiles shown in Image 2 exactly in style (same painting, same grass and floor).
Rules: output 1536 x 1024; keep the same grid and square positions as Image 1; each tile fills its square edge to edge; keep each tile's layout and colours; no borders, labels or text.
Generate the image directly."""
NIGHT_PROMPT = """Redraw Image 1 as high-resolution, hand-painted map tiles matching the style of the HD tiles and characters in Image 2.
Image 1 holds 10 square map tiles from a top-down 2D RPG, each showing a person seen from above standing on the ground: the first six are spectators of Endor's arena standing on grass at night, the last four are the audience of Monbaraba's theatre standing on a red stone floor.
Hard rules:
1. Output exactly 1536 x 1024. Keep the same grid: every tile stays in its own square at the same position and size, grey gaps between them. Unused squares stay plain grey.
2. Each tile fills its whole square edge to edge; the ground (grass or red floor) runs to every edge so the tiles sit seamlessly next to each other and next to plain ground tiles like those in Image 2.
3. Keep each person's pose, clothes and colours; paint them like the characters in Image 2.
4. No text, borders, shadows or vignettes.
"""

def night_tiles(build, out):
    d = os.path.join(out, 'night_tiles'); write_pkg(d, NIGHT_RULES, {'background': 'opaque'})
    tiles = art_tiles(json.load(open(os.path.join(build, 'field-capture', 'field_tiles.json'))))
    ids = [f'T{n}' for n in range(118, 128)]
    render_sheet([tiles[i] for i in ids]).save(os.path.join(d, 'inputs', 'N01.png'))
    open(os.path.join(d, 'prompts', 'N01.txt'), 'w').write(NIGHT_PROMPT)
    json.dump({'layout': 'tools/export_chatgpt_tiles.py', 'sheets': {'N01': ids}}, open(os.path.join(d, 'sheets.json'), 'w'), indent=0)
    # style: the owner's grass / floor tiles and people, as they look in the pack
    art = os.path.join(build, 'field-capture', 'art')
    ref = Image.new('RGB', (1024, 1024), GREY)
    tiles_all = tiles
    # the plainest owner tiles closest to the two grounds (grass, red floor)
    def ground(ref_tile):
        """Owner tiles that are mostly the crowd tile's ground colour."""
        px = np.asarray(tile_image(*ref_tile))
        edge = np.concatenate([px[0], px[-1], px[:, 0], px[:, -1]])        # the ground shows at the edges
        cols, cnt = np.unique(edge, axis=0, return_counts=True); g = cols[cnt.argmax()].astype(float)
        best = []
        for aid, tp in tiles.items():
            if aid in ids or not os.path.exists(os.path.join(art, aid + '.png')): continue
            a = np.asarray(tile_image(*tp)).reshape(-1, 3).astype(float)
            near = (np.abs(a - g).sum(1) < 40).mean()
            if near > 0.6: best.append((-near, aid))
        return [aid for _, aid in sorted(best)[:3]]
    picks = ground(tiles[ids[0]]) + ground(tiles[ids[-1]])
    for i, t in enumerate(picks):
        p = os.path.join(art, t + '.png')
        if os.path.exists(p): ref.paste(Image.open(p).convert('RGB').resize((300, 300)), (12 + (i % 3) * 337, 12 + (i // 3) * 337))
    for i, cid in enumerate(('C017', 'C019', 'C022')):
        p = os.path.join(HERE, 'hd/sprites/source', cid + '.png')
        if not os.path.exists(p): continue
        fr = Image.open(p).convert('RGBA').crop((39 + 2 * 374, 117, 39 + 2 * 374 + 336, 117 + 336)); fr.thumbnail((300, 300))
        bg = Image.new('RGBA', fr.size, GREY + (255,)); bg.alpha_composite(fr)
        ref.paste(bg.convert('RGB'), (12 + i * 337, 686))
    ref.save(os.path.join(d, 'style_reference.png'))
    return len(ids)

# ---------------------------------------------------------------- doors
DOOR_RULES = """You paint the in-between animation frames of a castle door opening, for an HD texture pack of Dragon Warrior IV (NES), matching the pack's existing HD door art exactly.
Generate the image directly."""
DOOR_PROMPT = """Image 1 shows a big castle double door opening, seen from the front, as five frames from left to right. Frame 1 (closed) and frame 5 (fully open) are already the finished high-resolution art; frames 2, 3 and 4 are still 8-bit.
Redraw frames 2, 3 and 4 as high-resolution, hand-painted art in exactly the style of frames 1 and 5: the same stone wall, arch, door wood, metal and dark doorway, so that playing frames 1-2-3-4-5 in order shows the doors swinging open smoothly. Keep each 8-bit frame's layout (where each door leaf is and how far it has swung).
Hard rules: output exactly 1536 x 1024; every frame stays in its square at the same position and size; frames 1 and 5 stay as they are; grey background between the squares; no text, labels or borders."""
DOOR_CELL, DOOR_GAP = 256, 26                       # 5 frames of 32x32 px at 8x
def door_origin(i): return (1536 - 5 * DOOR_CELL - 4 * DOOR_GAP) // 2 + i * (DOOR_CELL + DOOR_GAP), (1024 - DOOR_CELL) // 2

def doors(build, out):
    """Burland Castle's front door: closed (map tiles with art), three frames
    the game draws while it swings (nametable cells only, no map tile), open. Frames captured from the route as Ragnar
    leaves the castle (frames 5150-5230)."""
    d = os.path.join(out, 'doors'); write_pkg(d, DOOR_RULES, {'background': 'opaque'})
    data = json.load(open(os.path.join(build, 'extra-capture', 'doors.json')))
    art = os.path.join(build, 'field-capture', 'art')
    import hashlib
    ids = {v[0]: k for k, v in json.load(open(os.path.join(HERE, 'hd', 'field', 'ids.json')))['ids'].items()}
    art_id = lambda c: ids[hashlib.sha1(bytes.fromhex(c)).hexdigest()[:16]]
    frames = data['frames']                              # opening order
    sheet = Image.new('RGB', (1536, 1024), GREY)
    def from_art(ids):
        im = Image.new('RGB', (320, 320))
        for k, t in enumerate(ids): im.paste(Image.open(os.path.join(art, t + '.png')).convert('RGB'), ((k % 2) * 160, (k // 2) * 160))
        return im.resize((DOOR_CELL, DOOR_CELL), Image.LANCZOS)
    def from_chr(state):
        im = Image.new('RGB', (32, 32))
        pal = bytes.fromhex(data['palette'])
        for k, c in enumerate(state):
            im.paste(tile_image(bytes.fromhex(c), pal).resize((16, 16), Image.NEAREST), ((k % 2) * 16, (k // 2) * 16))
        return im.resize((DOOR_CELL, DOOR_CELL), Image.NEAREST)
    closed, opened = [art_id(c) for c in data['closed']], [art_id(c) for c in data['open']]
    sheet.paste(from_art(closed), door_origin(0))
    for i, st in enumerate(frames): sheet.paste(from_chr(st), door_origin(i + 1))
    sheet.paste(from_art(opened), door_origin(4))
    sheet.save(os.path.join(d, 'inputs', 'DOOR1.png'))
    open(os.path.join(d, 'prompts', 'DOOR1.txt'), 'w').write(DOOR_PROMPT)
    from_art(closed).resize((1024, 1024)).save(os.path.join(d, 'style_reference.png'))
    json.dump({'cells': [list(door_origin(i)) for i in range(5)], 'cell': DOOR_CELL, 'frames_opening': frames,
               'palette': data['palette']}, open(os.path.join(d, 'doors.json'), 'w'), indent=0)
    return 3

# ---------------------------------------------------------------- title
TITLE_RULES = """You repaint the title screen of Dragon Warrior IV (NES) as a high-resolution hand-painted illustration for an HD texture pack.
Generate the image directly."""
TITLE_PROMPT = """Repaint Image 1, the title screen of Dragon Warrior IV, as a high-resolution, hand-painted fantasy illustration in the style of Image 2.
Keep the composition exactly: the stone title plate with the words "DRAGON WARRIOR" and the Roman numeral "IV" (same lettering, same size and place; the letters must be spelled exactly), the silhouette of the castle on its hill at the same place and size, the sea of clouds along the bottom, the red sunset sky. Same colours.
Hard rules: output exactly 1280 x 1200, nothing moved or resized, no extra text, no borders."""

def title(build, out):
    d = os.path.join(out, 'title'); write_pkg(d, TITLE_RULES, {'background': 'opaque'})
    shot = os.path.join(build, 'extra-capture', 'title_2400.png')
    Image.open(shot).convert('RGB').resize((1280, 1200), Image.NEAREST).save(os.path.join(d, 'inputs', 'TITLE.png'))
    open(os.path.join(d, 'prompts', 'TITLE.txt'), 'w').write(TITLE_PROMPT)
    monster_style().save(os.path.join(d, 'style_reference.png'))
    return 1

README = """Dragon Warrior IV - the remaining graphics, for OpenAI's image API
=================================================================

Five folders, one per kind of graphic, each with its own rules and style
picture. Run the script once per folder:

  export OPENAI_API_KEY=sk-...
  python3 openai_sprites.py --folder monsters      # {monsters} battle monsters with no art
  python3 openai_sprites.py --folder effects       # {effects} map effects (shadows, sparkles...)
  python3 openai_sprites.py --folder night_tiles   # {night} night-only town tiles, one sheet
  python3 openai_sprites.py --folder doors         # the castle door opening frames, one sheet
  python3 openai_sprites.py --folder title         # the title screen

That is {total} images, about ${cost:.2f}. Add --dry-run first to see the plan.
Each folder gets its own generated/ folder: send all five back
(generated/results and generated/log.jsonl).

Not included: the Endor casino (slots and poker). The route this project
captures from never reaches it (it opens later in the story); it needs a
save from a later chapter to capture.
"""

def main():
    build, out = sys.argv[1], sys.argv[2]
    if os.path.exists(out): shutil.rmtree(out)
    os.makedirs(out)
    n = {'monsters': monsters(build, out), 'effects': effects(build, out), 'night': night_tiles(build, out),
         'doors': doors(build, out), 'title': title(build, out)}
    shutil.copy(os.path.join(TOOLS, 'openai_sprites.py'), os.path.join(out, 'openai_sprites.py'))
    images = n['monsters'] + n['effects'] + 1 + 1 + 1
    open(os.path.join(out, 'README.txt'), 'w').write(README.format(total=images, cost=images * 0.07, **n))
    shutil.make_archive(out, 'zip', os.path.dirname(out), os.path.basename(out))
    print(f'{images} images -> {out} (+ .zip): {n}')

if __name__ == '__main__':
    main()
