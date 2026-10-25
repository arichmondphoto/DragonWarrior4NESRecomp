"""Export every walking character for AI image generation, 10x (all
character types: tools/capture_types.py + sprite_sheet.py --types).

Input: tools/sprite_sheet.py characters.json.

Writes OUT/ (and OUT.zip):
  sheets/<ID>.png          one image per character, 4 columns (facing up,
                           right, down, left) x 2 rows (walking step 1, 2),
                           160x160 cells, 12 px gutters, transparent background
  sheets_on_grey/<ID>.png  the same on flat grey (for generators that
                           don't take transparency)
  frames/<ID>_<dir><step>.png  each frame alone, 160x160, transparent
  style_reference.png      a sample of the owner's monster art
  characters.csv           ID, where the character appears, colour versions
  README.txt               how to generate and hand the art back

usage: export_ai_sprites.py CHARACTERS_JSON OUT
"""
import csv, json, os, shutil, sys
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from sprite_sheet import frame_image, DIRS

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CELL, GUT = 160, 12
GREY = (128, 128, 128, 255)

# What each character type looks like (by table type number, bank 8 $979B),
# for the CSV and the prompt. Descriptions only: the 8-bit art decides.
WHO = {
    0x00: 'party: the Hero, male (probably) - winged green helmet, sword and shield',
    0x01: 'party: Kiryl (probably) - priest in a green cap, sword and shield',
    0x02: 'party: Alena (probably) - princess in a wide purple hat, orange hair',
    0x03: 'party: Nara (probably) - fortune teller in a pointed purple hood',
    0x04: 'party: Brey (probably) - old wizard in orange with a white beard and staff',
    0x05: 'party: Taloon (probably) - stout merchant in a pink robe',
    0x06: 'party: Ragnar - knight in pink armour with a sword (the Chapter 1 leader)',
    0x07: 'party: Mara (probably) - dancer with orange hair',
    0x08: 'party: the Hero, female (probably) - green hair, sword and shield',
    0x09: 'white horse', 0x0A: 'covered wagon', 0x0B: 'sailing ship',
    0x0C: 'hot-air balloon (envelope)', 0x0D: 'hot-air balloon (basket)',
    0x0E: 'glowing ring (effect)', 0x0F: 'king / bearded old man in a robe',
    0x10: 'priest in blue and green robes', 0x11: 'dancer / girl in orange',
    0x12: 'woman in a pink dress', 0x13: 'woman with long orange hair',
    0x14: 'boy in blue', 0x15: 'small child in brown', 0x16: 'old bearded man in a brown robe',
    0x17: 'man in a green cap (merchant)', 0x18: 'armoured guard in blue',
    0x19: 'man in blue', 0x1A: 'hooded nun in blue', 0x1B: 'soldier in blue with a helmet',
    0x1C: 'skeleton', 0x1D: 'child with pigtails in brown', 0x1E: 'woman with green hair',
    0x1F: 'plump lady in pink', 0x20: 'sailor in a striped shirt', 0x21: 'man in a brown robe',
    0x22: 'bearded dwarf / miner', 0x23: 'brown dog', 0x24: 'lion / big orange cat',
    0x25: 'white cat', 0x27: 'flames', 0x28: 'woman with purple hair', 0x29: 'cook / man in a white cap',
    0x2A: 'blue slime', 0x2B: 'tools / broken objects', 0x2C: 'white fluffy cloud-like creature',
    0x2D: 'orange-haired girl in a purple hood', 0x2E: 'man in pink with a horned cap',
    0x2F: 'girl with pink hair and horns', 0x30: 'shimmering blue panel (water / magic effect)',
    0x33: 'large round boulder', 0x35: 'stone golem / statue', 0x36: 'figure in a blue hood',
    0x37: 'fighter in a pink cap', 0x38: 'man in a brown hood', 0x39: 'big knight in pink armour with a shield',
    0x3A: 'small person in blue', 0x3B: 'round man in blue', 0x3C: 'orange dragon',
    0x3D: 'purple mushroom-like monster', 0x3E: 'orange lizard / fox creature', 0x3F: 'large purple demon',
    0x40: 'bearded man in brown and orange', 0x41: 'pink spiky demon', 0x42: 'white ghost / bird',
    0x43: 'orange brick golem', 0x44: 'green dragon / lizard man', 0x45: 'witch in a pink hat',
    0x46: 'brown bear-like beast', 0x47: 'orange spiky plant monster',
    0x48: 'large horned beast, piece 1 of 4 (with the next three)', 0x49: 'large horned beast, piece 2 of 4',
    0x4A: 'large horned beast, piece 3 of 4', 0x4B: 'large horned beast, piece 4 of 4',
    0x4C: 'fighter in purple with a headband', 0x4D: 'knight in a golden horned helmet',
    0x4E: 'pink winged demon', 0x51: 'orange and white block (object)', 0x52: 'half-moon shaped object',
    0x54: 'basket / barrel', 0x58: 'small shadow', 0x59: 'large shadow', 0x5A: 'shadow',
    0x5B: 'large orange bell-shaped mound / statue', 0x5C: 'orange gate', 0x5D: 'small green hooded creature',
    0x5E: 'small purple hooded creature', 0x5F: 'sparkles (effect)', 0x60: 'sparkles (effect)',
    0x61: 'purple glitter (effect)', 0x6B: 'pink jewelled winged creature',
}

README = """Dragon Warrior IV — every walking character, for AI image generation
=====================================================================

This is the whole game, all five chapters: the party members, every kind of
townsperson, soldier, animal, vehicle, monster and object that walks or
stands on the maps. It comes from the game's own character table (all {ntypes}
types), not from a playthrough, plus everything seen on the maps.

{n} sheets to draw (sheets/). Each is one character in 8 frames:

  columns: facing up, facing right, facing down, facing left
  rows:    walking step 1, walking step 2

sheets/<ID>.png is all 8 frames (4 x 2 grid of 160x160 cells, 12 px
gutters, transparent background); sheets_on_grey/ is the same on flat grey;
frames/ has every frame alone. characters.csv says what each one is and
where it appears; characters.png is the overview with all IDs.

Not in the batch (nothing to draw):
  * {skipped} characters drawn only with tiles of another one (single-pose
    copies of the party, pieces of a bigger object) — they reuse that art;
    characters.csv lists which.
  * People lying in bed: the game makes them by turning the standing
    character 90 degrees, and the HD pack will do the same with your art.

Generating
  * Generate a whole sheet at once (image-to-image / structure guide with the
    sheet as input, style_reference.png as the style image), so the
    character looks the same in all 8 frames. Keep the grid where it is.
  * Keep each frame's silhouette: same pose, same outline, same size and
    position in its cell. The game only draws the HD art where the original
    8-bit sprite has pixels, so anything outside the original outline is cut
    off, and gaps inside it show the map behind.
  * Keep the colours roughly as they are: the same character appears in
    other colours elsewhere, and those are made by recolouring your art.
    (Characters the route never reached are shown in a town's colours.)
  * C069-C072 are the four quarters of one large creature; draw them
    together if you can and cut them back into the four sheets.
  * Background: transparent if the generator can, otherwise flat grey
    (sheets_on_grey) — either works.
  * Suggested prompt: "top-down 2D RPG walking character sprite sheet,
    <description from characters.csv>, 4 directions x 2 walking steps,
    hand-painted fantasy illustration in the style of the reference, rich
    shading, crisp dark outlines, same poses, outlines and colours as the
    input, plain background, no text".

Handing the art back
  * One PNG per character named by ID (C001.png ...), same 4 x 2 grid, any
    size that is a multiple of the original (it is scaled back to fit).
  * Partial batches are fine; characters without art keep their 8-bit look.
"""

def main():
    rows = json.load(open(sys.argv[1])); out = sys.argv[2]
    if os.path.exists(out): shutil.rmtree(out)
    for d in ('sheets', 'sheets_on_grey', 'frames'): os.makedirs(os.path.join(out, d))
    W = 4 * CELL + 5 * GUT; H = 2 * CELL + 3 * GUT
    with open(os.path.join(out, 'characters.csv'), 'w', newline='') as f:
        wr = csv.writer(f)
        wr.writerow(['id', 'draw', 'description', 'type', 'colour_versions', 'appears_in'])
        for r in rows:
            types = r.get('types', [])
            who = WHO.get(types[0], '') if types else 'effect seen on the overworld at night'
            if r.get('art_from'):
                wr.writerow([r['id'], 'no - uses ' + r['art_from'], who, ' '.join('%02X' % t for t in types), len(r['versions']),
                             '; '.join(r['maps']) or 'not reached by the route'])
                continue
            cols = [bytes.fromhex(c) for c in r['versions'][0]['colours']]
            sheet = Image.new('RGBA', (W, H), (0, 0, 0, 0))
            for fi, fr in enumerate(r['frames']):
                img = frame_image([(bytes.fromhex(c), a) for c, a in fr], cols[fi * 4:fi * 4 + 4], 10)
                d, step = fi // 2, fi % 2
                sheet.alpha_composite(img, (GUT + d * (CELL + GUT), GUT + step * (CELL + GUT)))
                img.save(os.path.join(out, 'frames', f'{r["id"]}_{DIRS[d]}{step + 1}.png'))
            sheet.save(os.path.join(out, 'sheets', r['id'] + '.png'))
            g = Image.new('RGBA', (W, H), GREY); g.alpha_composite(sheet)
            g.convert('RGB').save(os.path.join(out, 'sheets_on_grey', r['id'] + '.png'))
            wr.writerow([r['id'], 'yes', who, ' '.join('%02X' % t for t in types), len(r['versions']),
                         '; '.join(r['maps']) or 'not reached by the route'])
    b = json.load(open(os.path.join(HERE, 'hd/monsters/boxes.json')))
    src = Image.open(os.path.join(HERE, 'hd/monsters/source/DW4Sprites.jpg')).convert('RGB')
    ref = Image.new('RGB', (1024, 512))
    for i, s in enumerate((0, 9, 20, 28, 40, 60, 75, 140)):
        im = src.crop(b[s]); im.thumbnail((250, 250))
        ref.paste(im, ((i % 4) * 256 + (256 - im.width) // 2, (i // 4) * 256 + (256 - im.height) // 2))
    ref.save(os.path.join(out, 'style_reference.png'))
    ov = os.path.join(os.path.dirname(sys.argv[1]), 'characters.png')
    if os.path.exists(ov): shutil.copy(ov, os.path.join(out, 'characters.png'))
    draw = [r for r in rows if not r.get('art_from')]
    ntypes = sum(len(r.get('types', [])) for r in rows)
    open(os.path.join(out, 'README.txt'), 'w').write(README.format(n=len(draw), ntypes=ntypes, skipped=len(rows) - len(draw)))
    shutil.make_archive(out, 'zip', os.path.dirname(out), os.path.basename(out))
    print(f'{len(draw)} characters to draw ({len(rows)} in all) -> {out} (+ .zip)')

if __name__ == '__main__':
    main()
