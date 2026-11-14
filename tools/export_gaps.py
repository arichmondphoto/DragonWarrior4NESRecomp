"""Package the graphics the HD pack still lacks, for OpenAI's image API
(tools/openai_sprites.py, one sub-folder per kind, each with its own
style image and rules). What is missing is read from the build's reports
and captures, so the package always holds what is left:

  map_tiles/       map tiles with no art (field-report.json "missing"), on
                   sheets of 24; new IDs are added to hd/field/ids.json
  characters/      walking characters with no hd/sprites/source art
                   (C069-C072 = one big demon, one sheet)
  battle/          battle pictures with no art: the shop scene's merchant
                   (capture 173) and the Impostor's "Double" after Transform
                   (needs --host: one forced battle)
  battle_effects/  battle sprite effects: the Transform smoke cloud (3
                   stages) and the sparkles around the Double (--host)

Earlier rounds (all done now, still available with --only): monsters,
effects, night_tiles, doors, title.

usage: export_gaps.py BUILD_DIR OUT [--host HOST] [--only KIND,...]
  BUILD_DIR: a tools/build_hd_pack.sh output's parent (monster-capture,
  field-capture, sprite-capture, *-report.json), e.g. out/build7
"""
import argparse, collections, glob, hashlib, json, os, shutil, subprocess, sys, tempfile
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, os.path.dirname(__file__))
from monster_tiles import monster
from vramdump import tile_pixels
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

# ---------------------------------------------------------------- map tiles (round 2)
MAP_PROMPT = """Redraw Image 1 as high-resolution, hand-painted map tiles matching the style of the HD tiles in Image 2.
Image 1 holds {n} square map tiles from a top-down 2D fantasy RPG (Dragon Warrior IV): {what}
Hard rules:
1. Output exactly 1536 x 1024. Keep the same 6 x 4 grid: every tile stays in its own square at the same position and size, grey gaps between them. Unused squares stay plain grey.
2. Each tile fills its whole square edge to edge; ground, water and walls run straight off every edge so the tiles sit seamlessly next to each other and next to tiles like those in Image 2.
3. Keep each tile's layout (the same shapes in the same places), top-down view and colours.
4. No text, borders, shadows or vignettes.
"""
PREFIX_WHAT = {'W': 'overworld tiles', 'T': 'town tiles', 'D': 'dungeon and tower tiles', 'S': 'shared town and dungeon tiles'}

def next_ids(ids, prefix, n):
    used = {int(k[1:]) for k in ids if k[0] == prefix and k[1:].isdigit()}
    out, k = [], max(used, default=0) + 1
    while len(out) < n:
        if k not in used: out.append(f'{prefix}{k:03d}')
        k += 1
    return out

def map_tiles(a, out):
    """Every map tile the build has no art for, with a new art ID (written to
    hd/field/ids.json with the palette the sheet shows it in, so the
    returned sheet slices back through tools/slice_field_sheets.py)."""
    missing = json.load(open(os.path.join(a.build, 'field-report.json')))['missing']
    if not missing: return 0
    rows = json.load(open(os.path.join(a.build, 'field-capture', 'field_tiles_all.json')))
    by_item = collections.defaultdict(list)
    for r in rows: by_item[r['item']].append(r)
    idp = os.path.join(HERE, 'hd', 'field', 'ids.json'); idj = json.load(open(idp)); ids = idj['ids']
    by_fp = {v[0]: k for k, v in ids.items()}
    tiles, uses = [], {}
    for prefix in 'WTDS':
        mine = [m for m in missing if m[0] == prefix]
        fresh = iter(next_ids(ids, prefix, len(mine)))
        for iid in mine:
            vs = by_item[iid]
            # the palette it is seen in most (daytime first)
            best = max(vs, key=lambda r: (not all(u.endswith('(night)') for u in r.get('used_in', [])), len(r.get('used_in', []))))
            t, pal = bytes.fromhex(best['chr']), bytes.fromhex(best['nes_colors'])
            fp = hashlib.sha1(t).hexdigest()[:16]
            aid = by_fp.get(fp) or next(fresh)
            ids.setdefault(aid, [fp, pal.hex()])
            tiles.append((aid, t, bytes.fromhex(ids[aid][1]))); uses[aid] = sorted({u for r in vs for u in r.get('used_in', [])})[:6]
    json.dump(idj, open(idp, 'w'), indent=0)
    d = os.path.join(out, 'map_tiles'); write_pkg(d, NIGHT_RULES, {'background': 'opaque'})
    sheets = {}
    for s0 in range(0, len(tiles), 24):
        part = tiles[s0:s0 + 24]; name = f'M{s0 // 24 + 1:02d}'
        render_sheet([(t, p) for _, t, p in part]).save(os.path.join(d, 'inputs', name + '.png'))
        kinds = collections.Counter(aid[0] for aid, _, _ in part)
        what = ', '.join(f'{n} {PREFIX_WHAT[k]}' for k, n in kinds.items()) + ' (in that order, left to right, top to bottom).'
        open(os.path.join(d, 'prompts', name + '.txt'), 'w').write(MAP_PROMPT.format(n=len(part), what=what))
        sheets[name] = [aid for aid, _, _ in part]
    json.dump({'layout': 'tools/export_chatgpt_tiles.py', 'sheets': sheets, 'used_in': uses}, open(os.path.join(d, 'sheets.json'), 'w'), indent=0)
    # style: for each new tile the owner's tile closest in colour, as the pack shows it
    art = os.path.join(a.build, 'field-capture', 'art')
    have = {aid: tp for aid, tp in art_tiles(rows).items() if os.path.exists(os.path.join(art, aid + '.png'))}
    mean = lambda t, p: np.asarray(tile_image(t, p)).reshape(-1, 3).mean(0)
    hm = {aid: mean(*tp) for aid, tp in have.items()}
    picks = []
    for aid, t, p in tiles:
        m = mean(t, p)
        for _, h in sorted((np.abs(v - m).sum(), h) for h, v in hm.items() if h[0] == aid[0] or aid[0] == 'S'):
            if h not in picks: picks.append(h); break
    ref = Image.new('RGB', (1024, 1024), GREY)
    for i, h in enumerate(picks[:16]):
        ref.paste(Image.open(os.path.join(art, h + '.png')).convert('RGB').resize((240, 240)), (16 + (i % 4) * 252, 16 + (i // 4) * 252))
    ref.save(os.path.join(d, 'style_reference.png'))
    return len(sheets)

# ---------------------------------------------------------------- characters (round 2)
def characters(a, out):
    """Walking characters without art in hd/sprites/source."""
    have = {f[:-4] for f in os.listdir(os.path.join(HERE, 'hd', 'sprites', 'source')) if f.endswith('.png')}
    tmp = tempfile.mkdtemp()
    subprocess.run([sys.executable, os.path.join(TOOLS, 'export_chatgpt_sprites.py'),
                    os.path.join(a.build, 'sprite-capture', 'characters.json'), os.path.join(tmp, 'pkg')], check=True, capture_output=True)
    src = os.path.join(tmp, 'pkg'); d = os.path.join(out, 'characters')
    want = []
    for f in sorted(os.listdir(os.path.join(src, 'inputs'))):
        cid = f[:-4]
        parts = cid.split('-')
        if '-' in cid: parts = [f'C{n:03d}' for n in range(int(parts[0][1:]), int(parts[1][1:]) + 1)]
        if not all(p in have for p in parts): want.append(cid)
    if not want: shutil.rmtree(tmp); return 0
    write_pkg(d, open(os.path.join(src, 'PROJECT_INSTRUCTIONS.txt')).read(), {'background': 'transparent'})
    shutil.copy(os.path.join(src, 'style_reference.png'), d)
    os.makedirs(os.path.join(d, 'silhouettes'), exist_ok=True)
    for cid in want:
        shutil.copy(os.path.join(src, 'inputs', cid + '.png'), os.path.join(d, 'inputs'))
        shutil.copy(os.path.join(src, 'silhouettes', cid + '.png'), os.path.join(d, 'silhouettes'))
        for f in os.listdir(os.path.join(src, 'prompts')):
            if f == cid + '.txt' or f.startswith(cid + '_'): shutil.copy(os.path.join(src, 'prompts', f), os.path.join(d, 'prompts'))
    shutil.rmtree(tmp)
    return len(want)

# ---------------------------------------------------------------- battle captures
IMPOSTOR = 153
SMOKE_FRAMES = (9020, 9024, 9026)       # Transform: small puff, cloud, full cloud (tools/hd_coverage.py ENC_FRAME + forced Impostor)
SPARKLE_FRAMES = (9036, 9040)           # the two sparkle shapes around the Double
DOUBLE_FRAME = 9050

def forced_battle(host, monster_id, frames, tmp):
    """Mem dumps + 8-bit screenshots of a battle against monster_id, forced
    at the encounter of the reference route (as tools/hd_coverage.py)."""
    sys.path.insert(0, TOOLS); import hd_coverage as Hc
    mods = os.path.join(tmp, 'mods'); os.makedirs(mods, exist_ok=True)
    st, dump = os.path.join(tmp, 'b.cs'), os.path.join(tmp, 'b.mem')
    f0 = Hc.ENC_FRAME
    subprocess.run([host, Hc.ROM, '--frames', str(f0 + 1), '--no-save', '--input', Hc.ROUTE, '--mods-root', mods,
                    '--mem-frame', str(f0), '--mem-out', dump, '--save-state', f'{f0}:{st}'], check=True, capture_output=True)
    b = bytearray(open(st, 'rb').read()); off = b.find(load(dump)['wram'])
    b[off + 0xE45:off + 0xE49] = bytes([monster_id, 255, 255, 255]); open(st, 'wb').write(bytes(b))
    fr = sorted(frames); out = {}
    for f in fr:
        subprocess.run([host, Hc.ROM, '--load-state', st, '--frames', str(f + 1), '--no-save', '--input', Hc.ROUTE, '--mods-root', mods,
                        '--screenshot', os.path.join(tmp, f'n{f}.png'), '--mem-frame', str(f), '--mem-out', os.path.join(tmp, f'm{f}.mem')],
                       check=True, capture_output=True)
        out[f] = (os.path.join(tmp, f'm{f}.mem'), os.path.join(tmp, f'n{f}.png'))
    return out

def sprite_piece(mem, shot):
    """The frame's sprites: RGBA picture (from the 8-bit screenshot) and their keys."""
    m = monster(mem); spr = m['spr']; ch = load(mem)['chr_ram']
    x0, y0 = min(s['x'] for s in spr), min(s['y'] for s in spr)
    x1, y1 = max(s['x'] for s in spr) + 8, max(s['y'] for s in spr) + 8
    im = Image.new('RGBA', (x1 - x0, y1 - y0)); sh = Image.open(shot).convert('RGBA')
    for s in spr:
        px = tile_pixels(ch, s['tile'])
        for yy in range(8):
            for xx in range(8):
                if px[7 - yy if s['vflip'] else yy][7 - xx if s['hflip'] else xx]:
                    im.putpixel((s['x'] + xx - x0, s['y'] + yy - y0), sh.getpixel((s['x'] + xx, s['y'] + yy)))
    keys = [{'x': s['x'] - x0, 'y': s['y'] - y0, 'chr': s['data'].hex().upper(), 'pal': s['pal'].hex().upper(),
             'hflip': s['hflip'], 'vflip': s['vflip']} for s in spr]
    return im, keys

def bg_piece(mem, shot):
    """The monster area's BG cells (tile >= $8D): picture + keys."""
    m = monster(mem, shot); x0, y0 = m['box'][:2]
    keys = [{'x': c * 8 - x0, 'y': r * 8 - y0, 'chr': data.hex().upper(), 'pal': p.hex().upper()} for (r, c), (t, data, p) in sorted(m['bg'].items())]
    keys += [{'x': s['x'] - x0, 'y': s['y'] - y0, 'chr': s['data'].hex().upper(), 'pal': s['pal'].hex().upper(),
              'hflip': s['hflip'], 'vflip': s['vflip'], 'sprite': True} for s in m['spr']]
    return m['image'], keys

def on_grey(im, size, fill=0.8):
    k = max(1, int(min(size[0] * fill / im.width, size[1] * fill / im.height)))
    big = im.resize((im.width * k, im.height * k), Image.NEAREST)
    sheet = Image.new('RGBA', size, GREY + (255,)); pos = ((size[0] - big.width) // 2, (size[1] - big.height) // 2)
    sheet.alpha_composite(big, pos)
    return sheet.convert('RGB'), {'scale': k, 'origin': list(pos), 'size': [im.width, im.height]}

BATTLE_PROMPTS = {
    'M173': """Redraw Image 1 as a high-resolution, hand-painted Dragon Quest character illustration in the style of Image 2: a plump, cheerful travelling merchant with a big moustache, a red fez-like cap, blue waistcoat, yellow baggy trousers and a large grey sack over one arm, as shown behind a shop counter.
Keep exactly the pose, silhouette, proportions and colour scheme of the 8-bit picture in Image 1 (it is laid over it in the game), centred, filling most of the picture. Rich painterly shading, crisp dark outline, transparent background, nothing else.""",
    'M153D': """Redraw Image 1 as a high-resolution, hand-painted Dragon Quest monster illustration in the style of Image 2: the Impostor transformed into a copy of the hero Ragnar, a big knight in a pink helmet and purple armour holding a sword upright, front view as in battle.
Keep exactly the pose, silhouette, proportions and colour scheme of the 8-bit picture in Image 1 (it is laid over it in the game), centred, filling most of the picture. Rich painterly shading, crisp dark outline, transparent background, nothing else.""",
}

def battle(a, out, cap):
    """Battle pictures with no art: the shop scene's merchant (monster capture
    173 is a shop, not a battle) and the Impostor's Double after Transform."""
    d = os.path.join(out, 'battle'); write_pkg(d, MON_RULES, {'background': 'transparent'})
    monster_style().save(os.path.join(d, 'style_reference.png'))
    pieces = {'M173': bg_piece(os.path.join(a.build, 'monster-capture', '173.mem'), os.path.join(a.build, 'monster-capture', '173.png'))}
    if cap: pieces['M153D'] = bg_piece(*cap[DOUBLE_FRAME])
    layout = {}
    for name, (im, keys) in pieces.items():
        sheet, pos = on_grey(im, (1024, 1024)); sheet.save(os.path.join(d, 'inputs', name + '.png'))
        open(os.path.join(d, 'prompts', name + '.txt'), 'w').write(BATTLE_PROMPTS[name])
        layout[name] = dict(pos, tiles=keys)
    json.dump(layout, open(os.path.join(d, 'pieces.json'), 'w'), indent=0)
    return len(pieces)

FX_RULES = """You redraw 8-bit Dragon Warrior IV (NES) battle effects as hand-painted HD effects for an HD texture pack, in the style of Image 2 (the pack's monster art).
Generate the image directly."""
FX_PROMPT = """Image 1 shows the frames of a magic effect from a fantasy RPG battle, each in its own square on a grey background, left to right: {what}
Redraw every frame as high-resolution, hand-painted art in the style of Image 2: soft, glowing, painterly white and pale-blue magic smoke {extra}with crisp clean edges.
Hard rules:
1. Output exactly 1536 x 1024. Every frame stays in its own square at exactly the same position and size, with the same outline as in Image 1 (it is laid over the 8-bit frame in the game).
2. Keep the grey background between and around the shapes flat and empty.
3. No text, borders, characters or extra objects."""

def battle_effects(a, out, cap):
    if not cap: return 0
    d = os.path.join(out, 'battle_effects'); write_pkg(d, FX_RULES, {'background': 'transparent'})
    monster_style().save(os.path.join(d, 'style_reference.png'))
    frames = [sprite_piece(*cap[f]) for f in SMOKE_FRAMES]
    # sparkles: four copies of one 8x8 sprite; one is enough
    for f in SPARKLE_FRAMES:
        im, keys = sprite_piece(*cap[f]); k = keys[0]
        frames.append((im.crop((k['x'], k['y'], k['x'] + 8, k['y'] + 8)), [dict(k, x=0, y=0)]))
    cell, gap = 256, 32
    x0 = (1536 - len(frames) * cell - (len(frames) - 1) * gap) // 2
    sheet = Image.new('RGB', (1536, 1024), GREY); layout = []
    for i, (im, keys) in enumerate(frames):
        k = cell // max(im.width, im.height)
        big = im.resize((im.width * k, im.height * k), Image.NEAREST)
        ox, oy = x0 + i * (cell + gap) + (cell - big.width) // 2, (1024 - big.height) // 2
        sheet.paste(big, (ox, oy), big)
        layout.append({'origin': [ox, oy], 'scale': k, 'size': [im.width, im.height], 'tiles': keys})
    sheet.save(os.path.join(d, 'inputs', 'FX01.png'))
    open(os.path.join(d, 'prompts', 'FX01.txt'), 'w').write(FX_PROMPT.format(
        what='three growing stages of a puff of magic smoke (the cast of "Transform"), then two small four-pointed sparkles.',
        extra='puffs made of round billowing curls, and small bright sparkles, '))
    json.dump({'FX01': layout}, open(os.path.join(d, 'pieces.json'), 'w'), indent=0)
    return 1

README = """Dragon Warrior IV - the remaining graphics, for OpenAI's image API
=================================================================

One folder per kind of graphic, each with its own rules and style picture.
Run the script once per folder:

  export OPENAI_API_KEY=sk-...
{runs}
That is {total} images, about ${cost:.2f}. Add --dry-run first to see the plan.
Each folder gets its own generated/ folder: send them all back
(generated/results and generated/log.jsonl).

{notes}"""
FOLDER_NOTE = {
    'map_tiles': 'map tiles with no art yet, on sheets of 24',
    'characters': 'walking characters with no art yet',
    'battle': "the item-shop merchant and the Impostor's Double",
    'battle_effects': 'the Transform smoke cloud and sparkles, one sheet',
    'monsters': 'battle monsters with no art', 'effects': 'map effects (shadows, sparkles...)',
    'night_tiles': 'night-only town tiles', 'doors': 'castle door opening frames', 'title': 'the title screen',
}
NOTES = """Not included, and why:
  - The ENIX logo on the "PRESENTED BY" screen: a company logo is not
    something to redraw; the pack smooths the game's own pixels instead.
  - The party's spells and the story's cutscenes and ending: the save the
    captures start from is in chapter 1, so they have not been reached yet.
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('build'); ap.add_argument('out')
    ap.add_argument('--host', help='headless host: captures the Impostor battle (battle/, battle_effects/)')
    ap.add_argument('--only', help='comma-separated kinds')
    a = ap.parse_args()
    out = a.out
    if os.path.exists(out): shutil.rmtree(out)
    os.makedirs(out)
    tmp = tempfile.mkdtemp()
    cap = forced_battle(a.host, IMPOSTOR, SMOKE_FRAMES + SPARKLE_FRAMES + (DOUBLE_FRAME,), tmp) if a.host else None
    kinds = {'map_tiles': lambda: map_tiles(a, out), 'characters': lambda: characters(a, out),
             'battle': lambda: battle(a, out, cap), 'battle_effects': lambda: battle_effects(a, out, cap),
             'monsters': lambda: monsters(a.build, out), 'effects': lambda: effects(a.build, out),
             'night_tiles': lambda: night_tiles(a.build, out), 'doors': lambda: doors(a.build, out), 'title': lambda: title(a.build, out)}
    want = a.only.split(',') if a.only else ['map_tiles', 'characters', 'battle', 'battle_effects']
    n = {k: kinds[k]() for k in want}
    shutil.rmtree(tmp)
    shutil.copy(os.path.join(TOOLS, 'openai_sprites.py'), os.path.join(out, 'openai_sprites.py'))
    runs = ''.join(f'  python3 openai_sprites.py --folder {k:<15} # {v}: {FOLDER_NOTE[k]}\n' for k, v in n.items() if v)
    images = sum(n.values())
    open(os.path.join(out, 'README.txt'), 'w').write(README.format(runs=runs, total=images, cost=images * 0.07, notes=NOTES))
    shutil.make_archive(out, 'zip', os.path.dirname(os.path.abspath(out)), os.path.basename(out))
    print(f'{images} images -> {out} (+ .zip): {n}')

if __name__ == '__main__':
    main()
