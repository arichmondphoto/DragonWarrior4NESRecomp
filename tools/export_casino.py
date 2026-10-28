"""Package the Endor casino's playing cards for OpenAI's image API
(tools/openai_sprites.py): the 53 card faces (52 + the joker) and the card
back, six cards to a 1536 x 1024 sheet (nine sheets), each card the game's
own 5 x 7-tile card enlarged 8x (320 x 448) at fixed places
(card_origin()), on the table's green.

The capture is tools/capture_casino.py (BUILD_DIR/casino-capture/cards.json).
Sheet n holds cards SHEET_CARDS[n] ('back' = the card back).

usage: export_casino.py BUILD_DIR OUT
"""
import json, os, shutil, sys
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from field_sheet import NES
from export_gaps import monster_style, write_pkg

TOOLS = os.path.dirname(os.path.abspath(__file__))
K = 8                                   # enlargement on the sheets
CW, CH = 40 * K, 56 * K                 # one card
GX, GY = (1536 - 3 * CW) // 4, (1024 - 2 * CH) // 3
FELT = (0, 82, 0)
SUITS = ['sword', 'shield', 'slime', 'crown']          # suit = card % 4 (blue, red, blue, red)
RANKS = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
ORDER = [f'{c:02x}' for c in range(53)] + ['back']
SHEET_CARDS = [ORDER[i:i + 6] for i in range(0, len(ORDER), 6)]

def card_origin(i): return GX + (i % 3) * (CW + GX), GY + (i // 3) * (CH + GY)

def card_name(cid):
    if cid == 'back': return 'the card back'
    c = int(cid, 16)
    if c == 0x34: return 'the joker'
    return f'{RANKS[c // 4]} of {SUITS[c % 4]}s'

def card_image(cells, k=K):
    img = np.zeros((56, 40, 3), np.uint8)
    for n, (chr_hex, pal_hex) in enumerate(cells):
        d, pal = bytes.fromhex(chr_hex), bytes.fromhex(pal_hex)
        y0, x0 = (n // 5) * 8, (n % 5) * 8
        for r in range(8):
            for c in range(8):
                v = ((d[r] >> (7 - c)) & 1) | (((d[r + 8] >> (7 - c)) & 1) << 1)
                col = NES[pal[v] & 0x3F]
                img[y0 + r, x0 + c] = ((col >> 16) & 255, (col >> 8) & 255, col & 255)
    return Image.fromarray(img).resize((40 * k, 56 * k), Image.NEAREST)

RULES = """You redraw the 8-bit playing cards of Dragon Warrior IV's casino (NES) as high-resolution hand-painted cards for an HD texture pack, in the painterly style of Image 2 (the pack's other art).
Rules: Image 1 is a sheet of six cards on a green table. Keep every card exactly where it is and exactly its size (320 x 448 each); keep the green around them flat and unchanged. Each card keeps its rank in the corners, the number and arrangement of its suit symbols, its colours (blue or red), and its picture for aces, jacks, queens, kings and the joker. White card faces with a thin dark border and slightly rounded corners. No extra cards, text, shadows or frames.
Generate the image directly."""
PROMPT = """Redraw the six cards in Image 1 as crisp, hand-painted fantasy playing cards in the style of Image 2. From left to right, top row then bottom row: {names}.
The suits are Dragon Quest symbols: a blue sword, a red shield, a blue slime and a red crown. Keep each card's layout from Image 1 (corner ranks, pip positions, the large picture on aces, the letter and suit symbols on jacks, queens and kings, the purple dragon on the joker, the pattern of the card back) and its colours, but painted with clean detail. Card positions and sizes must not change; the green table stays flat."""

README = """Dragon Warrior IV - the Endor casino's playing cards, for OpenAI's image API
==========================================================================

The 53 poker cards (52 + the joker) and the card back, six to a sheet
(nine sheets, C01-C09). Each sheet shows the game's 8-bit cards enlarged;
the redraw keeps every card in place.

  export OPENAI_API_KEY=sk-...
  python3 openai_sprites.py --folder cards        # 9 images, about $0.65

Add --dry-run first to see the plan. Send back cards/generated (the
results and log.jsonl).

Sheet contents:
{contents}
"""

def main():
    build, out = sys.argv[1], sys.argv[2]
    cap = json.load(open(os.path.join(build, 'casino-capture', 'cards.json')))
    if os.path.exists(out): shutil.rmtree(out)
    d = os.path.join(out, 'cards'); write_pkg(d, RULES, {'background': 'opaque'})
    monster_style().save(os.path.join(d, 'style_reference.png'))
    contents = []
    for n, ids in enumerate(SHEET_CARDS, 1):
        sheet = Image.new('RGB', (1536, 1024), FELT)
        for i, cid in enumerate(ids):
            cells = cap['back'] if cid == 'back' else cap['cards'][cid]
            sheet.paste(card_image(cells), card_origin(i))
        sid = f'C{n:02d}'
        sheet.save(os.path.join(d, 'inputs', sid + '.png'))
        names = ', '.join(card_name(c) for c in ids)
        open(os.path.join(d, 'prompts', sid + '.txt'), 'w').write(PROMPT.format(names=names))
        contents.append(f'  {sid}: {names}')
    json.dump({'sheets': {f'C{n:02d}': ids for n, ids in enumerate(SHEET_CARDS, 1)}}, open(os.path.join(d, 'sheets.json'), 'w'), indent=1)
    shutil.copy(os.path.join(TOOLS, 'openai_sprites.py'), os.path.join(out, 'openai_sprites.py'))
    open(os.path.join(out, 'README.txt'), 'w').write(README.format(contents='\n'.join(contents)))
    shutil.make_archive(out, 'zip', os.path.dirname(out), os.path.basename(out))
    print(f'{len(SHEET_CARDS)} sheets -> {out} (+ .zip)')

if __name__ == '__main__':
    main()
