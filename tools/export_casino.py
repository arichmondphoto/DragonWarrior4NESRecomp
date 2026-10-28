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

README = """Dragon Warrior IV - the Endor casino, for OpenAI's image API
=============================================================

Three folders:

  export OPENAI_API_KEY=sk-...
  python3 openai_sprites.py --folder cards          # 9 sheets of poker cards
  python3 openai_sprites.py --folder slot_machine   # the slot machine (1280 x 1200)
  python3 openai_sprites.py --folder slot_symbols   # the seven reel symbols, one sheet

11 images, about $0.80. Add --dry-run first to see the plan. Send back each
folder's generated/ (the results and log.jsonl).

The cards: the 53 poker cards (52 + the joker) and the card back, six to a
sheet; each sheet shows the game's 8-bit cards enlarged and the redraw keeps
every card in place.

Sheet contents:
{contents}
"""

# ---------------------------------------------------------------- slots
SYM_NAMES = {}            # filled from the capture: symbol index -> name (by look)
SK = 18                   # symbol enlargement on the sheet (16 px -> 288)
def sym_origin(i): return 64 + (i % 4) * 352 + 32, 128 + (i // 4) * 416 + 32

SLOT_RULES = """You redraw the slot machine screen of Dragon Warrior IV's casino (NES) as a high-resolution hand-painted picture for an HD texture pack, in the painterly style of Image 2 (the pack's other art).
Rules: Image 1 is the game's screen enlarged to 1280 x 1200. Keep everything exactly where it is and the same size: the JACKPOT sign, the five lamp holders on the left, the three reel windows (leave them EMPTY - plain white, the symbols are drawn separately), the pay table on the right with its symbols and numbers, the COIN label and its empty counter box, the coin slot below the reels and the dark red cabinet. Leave the black text window at the bottom plain black (the game writes its text there). No extra text, people or objects.
Generate the image directly."""
SLOT_PROMPT = """Redraw Image 1 as a detailed hand-painted golden slot machine cabinet on deep red, in the style of Image 2. Same layout and proportions as Image 1, every element in place; the three reel windows stay empty and white; the pay table keeps its symbols (777, BAR, suns, moons, stars, water drops, cherries) and numbers (1000, 500, 200, 100, 50, 20, 10, 5); the bottom window stays plain black. Output exactly 1280 x 1200."""
SYM_RULES = """You redraw the 8-bit reel symbols of Dragon Warrior IV's slot machine (NES) as high-resolution hand-painted icons for an HD texture pack, in the painterly style of Image 2.
Rules: Image 1 is a sheet of seven symbols (each 288 x 288) on a transparent background. Keep each symbol exactly where it is, the same size, shape and colours; transparent background; no frames, text or extra objects.
Generate the image directly."""
SYM_PROMPT = """Redraw the seven slot machine symbols in Image 1 as crisp, glossy hand-painted icons in the style of Image 2. Left to right, top row then bottom row: {names}. Each keeps its place, size, silhouette and colours; transparent background."""

def symbol_image(chs, pal_hex, k=SK):
    pal = bytes([0]) + bytes.fromhex(pal_hex)[1:]
    img = np.zeros((16, 16, 4), np.uint8)
    for q, ch in enumerate(chs):
        d = bytes.fromhex(ch)
        for r in range(8):
            for c in range(8):
                v = ((d[r] >> (7 - c)) & 1) | (((d[r + 8] >> (7 - c)) & 1) << 1)
                if not v: continue
                col = NES[pal[v] & 0x3F]
                img[(q // 2) * 8 + r, (q % 2) * 8 + c] = ((col >> 16) & 255, (col >> 8) & 255, col & 255, 255)
    return Image.fromarray(img, 'RGBA').resize((16 * k, 16 * k), Image.NEAREST)

def slots(build, out):
    cap = json.load(open(os.path.join(build, 'slots-capture', 'slots.json')))
    d = os.path.join(out, 'slot_machine'); write_pkg(d, SLOT_RULES, {'background': 'opaque'})
    monster_style().save(os.path.join(d, 'style_reference.png'))
    from make_slots_hdpack import blank_text_window
    from vramdump import load
    scr = Image.open(os.path.join(build, 'slots-capture', 'screen.png')).convert('RGB')
    blank_text_window(scr, cap, load(os.path.join(build, 'slots-capture', 'screen.mem'))['palette'][0], 1)
    scr.resize((1280, 1200), Image.NEAREST).save(os.path.join(d, 'inputs', 'SLOT.png'))
    open(os.path.join(d, 'prompts', 'SLOT.txt'), 'w').write(SLOT_PROMPT)
    d = os.path.join(out, 'slot_symbols'); write_pkg(d, SYM_RULES, {'background': 'transparent'})
    monster_style().save(os.path.join(d, 'style_reference.png'))
    sheet = Image.new('RGBA', (1536, 1024), (0, 0, 0, 0))
    names = []
    for i, (chs, pal) in enumerate(cap['symbols']):
        sheet.alpha_composite(symbol_image(chs, pal), sym_origin(i))
        names.append(symbol_name(chs, i))
    sheet.save(os.path.join(d, 'inputs', 'SYMBOLS.png'))
    open(os.path.join(d, 'prompts', 'SYMBOLS.txt'), 'w').write(SYM_PROMPT.format(names=', '.join(names)))
    json.dump({'symbols': cap['symbols']}, open(os.path.join(d, 'symbols.json'), 'w'), indent=1)
    return names

# the seven symbols by their CHR (sha1 of the four tiles' hex, first 12)
SYMBOL_NAME = {"596cd6ac0c68": "cherries", "790e00426640": "BAR", "ed930ddf74b0": "moon", "77d52cfedfc3": "water drop", "e543663e0247": "sun", "ba6d75e9d0e0": "star", "cde904a6d65e": "seven"}
def symbol_name(chs, i):
    import hashlib
    return SYMBOL_NAME.get(hashlib.sha1(''.join(chs).encode()).hexdigest()[:12], f'symbol {i + 1}')

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
    sym = slots(build, out)
    shutil.copy(os.path.join(TOOLS, 'openai_sprites.py'), os.path.join(out, 'openai_sprites.py'))
    open(os.path.join(out, 'README.txt'), 'w').write(README.format(contents='\n'.join(contents)))
    shutil.make_archive(out, 'zip', os.path.dirname(out), os.path.basename(out))
    print(f'{len(SHEET_CARDS)} sheets -> {out} (+ .zip)')

if __name__ == '__main__':
    main()
