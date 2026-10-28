"""Render the playing cards' rank glyphs (A 2 .. 10 J Q K) once, as masks, into
hd/casino/cards/glyphs.png (+ glyphs.json: each glyph's box), so the deck
(tools/compose_deck.py) needs no system font at build time.

Font: Liberation Serif Bold (SIL Open Font License).

usage: make_card_glyphs.py [FONT.ttf]
"""
import json, os, sys
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(HERE, 'hd', 'casino', 'cards')
RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
CAP = 240                                     # cap height of the masks

def main():
    font = sys.argv[1] if len(sys.argv) > 1 else '/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf'
    f = ImageFont.truetype(font, int(CAP * 1.42))
    masks = []
    for t in RANKS:
        bb = f.getbbox(t); m = Image.new('L', (bb[2] - bb[0] + 8, bb[3] - bb[1] + 8), 0)
        ImageDraw.Draw(m).text((4 - bb[0], 4 - bb[1]), t, font=f, fill=255)
        masks.append(m.crop(m.getbbox()))
    W = sum(m.width + 8 for m in masks); H = max(m.height for m in masks)
    sheet = Image.new('L', (W, H), 0); boxes = {}; x = 0
    for t, m in zip(RANKS, masks):
        sheet.paste(m, (x, 0)); boxes[t] = [x, 0, x + m.width, m.height]; x += m.width + 8
    sheet.save(os.path.join(OUT, 'glyphs.png'), optimize=True)
    json.dump({'font': os.path.basename(font), 'glyphs': boxes}, open(os.path.join(OUT, 'glyphs.json'), 'w'), indent=1)
    print(f'{len(RANKS)} glyphs -> {OUT}/glyphs.png')

if __name__ == '__main__':
    main()
