"""Export every walking character for AI image generation, 10x.

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

README = """Dragon Warrior IV — walking characters for AI image generation
==============================================================

{n} characters (party, townspeople, soldiers, animals, ships and wagons,
monsters seen on the map, and a few effects). Each is drawn in 8 frames:

  columns: facing up, facing right, facing down, facing left
  rows:    walking step 1, walking step 2

sheets/<ID>.png is all 8 frames of one character (4 x 2 grid of 160x160
cells, 12 px gutters, transparent background); sheets_on_grey/ is the same
on flat grey; frames/ has every frame alone. IDs match characters.png.

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
  * Background: transparent if the generator can, otherwise flat grey
    (sheets_on_grey) — either works.
  * Suggested prompt: "top-down 2D RPG walking character sprite sheet,
    {{who}}, 4 directions x 2 walking steps, hand-painted fantasy
    illustration in the style of the reference, rich shading, crisp dark
    outlines, same poses, outlines and colours as the input, plain
    background, no text".

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
        wr = csv.writer(f); wr.writerow(['id', 'colour_versions', 'appears_in'])
        for r in rows:
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
            wr.writerow([r['id'], len(r['versions']), '; '.join(r['maps'])])
    b = json.load(open(os.path.join(HERE, 'hd/monsters/boxes.json')))
    src = Image.open(os.path.join(HERE, 'hd/monsters/source/DW4Sprites.jpg')).convert('RGB')
    ref = Image.new('RGB', (1024, 512))
    for i, s in enumerate((0, 9, 20, 28, 40, 60, 75, 140)):
        im = src.crop(b[s]); im.thumbnail((250, 250))
        ref.paste(im, ((i % 4) * 256 + (256 - im.width) // 2, (i // 4) * 256 + (256 - im.height) // 2))
    ref.save(os.path.join(out, 'style_reference.png'))
    open(os.path.join(out, 'README.txt'), 'w').write(README.format(n=len(rows)))
    shutil.make_archive(out, 'zip', os.path.dirname(out), os.path.basename(out))
    print(f'{len(rows)} characters -> {out} (+ .zip)')

if __name__ == '__main__':
    main()
