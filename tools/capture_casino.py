"""Capture the Endor casino's poker table (every card face, the card back) from
the Chapter 1 route - no playthrough.

Warp (as tools/capture_field.py does): at route frame 5050 the hero is one
step from Burland Castle's exit; both entries of the exit table ($05A0) are
pointed at the Endor casino (map 4, submap 1) at (19, 10), just behind the
poker dealer, facing her. The hero is given 100 casino coins (WRAM $62AD),
talks to her, says yes and bets 1 coin.

The deck is shuffled when the game starts and kept at WRAM $7600 (one byte
per card: rank * 4 + suit, rank 0 = ace .. 12 = king; $34 = the joker); the
hand is its first five cards and a draw takes the next ones. So the capture
writes ten chosen cards there at the wager prompt, lets the deal show five,
draws all five (cursor to the middle card, down to DEAL, A) and so shows the
next five: six runs show all 53 cards.

The table: five cards of 5 x 7 tiles at nametable columns 2, 8, 14, 20, 26,
rows 10-16 (BG pattern table $1000).

Writes OUT/cards.json: {"cards": {id: [[CHR hex, palette hex] x 35 (row by
row)]}, "back": [...], "empty": [...], "slots": [[col, row] x 5],
"screen_tiles": [[CHR hex, palette hex]]} (the other tiles of the poker
screen: digits, labels) and "sprites": [[CHR hex, 'FF' + 3 colours]] (the
pointing hand); OUT/*.mem and OUT/card_XX.png (8-bit, 1x) for reference.

usage: capture_casino.py HOST OUT
"""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from capture_field import ROM, ROUTE, EXIT_FRAME

SLOTS = [(2 + 6 * i, 10) for i in range(5)]
B = EXIT_FRAME
# relative to the warp frame: walk (route), talk, yes, then A through the wager
BASE = [(0, 'DOWN'), (70, '-'), (240, 'A'), (244, '-'), (280, 'A'), (284, '-'), (420, 'A'), (424, '-'),
        (500, 'A'), (504, '-'), (560, 'A'), (564, '-'), (620, 'A'), (624, '-')]
DRAW_ALL = [(1010, 'RIGHT'), (1018, '-'), (1040, 'RIGHT'), (1048, '-'), (1070, 'DOWN'), (1078, '-'), (1100, 'A'), (1106, '-')]
STATE_AT, HAND_AT, DRAWN_AT, EMPTY_AT = 540, 1080, 1250, 470

def main():
    host, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True); tmp = tempfile.mkdtemp(prefix='dw4casino')
    def run(*args):
        subprocess.run([host, ROM, '--no-save', '--mods-root', tempfile.mkdtemp(prefix='mods', dir=tmp), *map(str, args)],
                       check=True, capture_output=True)
    route = [l for l in open(ROUTE).read().splitlines() if l.strip() and int(l.split()[0]) < B]
    def inputs(name, events):
        p = os.path.join(tmp, name)
        open(p, 'w').write('\n'.join(route + [f'{B + f} {b}' for f, b in sorted(events)]) + '\n'); return p
    s0, m0 = os.path.join(tmp, 'exit.cs'), os.path.join(tmp, 'exit.mem')
    run('--frames', B + 1, '--input', ROUTE, '--save-state', f'{B}:{s0}', '--mem-frame', B, '--mem-out', m0)
    st = bytearray(open(s0, 'rb').read()); m = load(m0)
    ra = st.find(bytes(m['ram'][0x500:0x600])) - 0x500; wa = st.find(bytes(m['wram'][:0x400]))
    for e in (0x5A0, 0x5A7): st[ra + e + 2:ra + e + 7] = bytes([4, 1, 19, 10, 0x82])
    st[wa + 0x2AD] = 100
    warp = os.path.join(tmp, 'warp.cs'); open(warp, 'wb').write(st)
    base_in = inputs('base.txt', BASE)
    s540, m540 = os.path.join(tmp, 's540.cs'), os.path.join(out, 'wager.mem')
    run('--load-state', warp, '--frames', B + EMPTY_AT + 1, '--input', base_in, '--mem-frame', B + EMPTY_AT,
        '--mem-out', os.path.join(out, 'empty.mem'))
    run('--load-state', warp, '--frames', B + STATE_AT + 1, '--input', base_in, '--save-state', f'{B + STATE_AT}:{s540}',
        '--mem-frame', B + STATE_AT, '--mem-out', m540)
    st = bytearray(open(s540, 'rb').read()); m = load(m540)
    wa = st.find(bytes(m['wram'][:0x400])); assert wa > 0
    draw_in = inputs('draw.txt', BASE + DRAW_ALL)

    def grid(mem, slot):
        cm = load(mem); ci, ch, pal = cm['ciram'], cm['chr_ram'], cm['palette']
        x0, y0 = SLOTS[slot]; cells = []
        for ty in range(y0, y0 + 7):
            for tx in range(x0, x0 + 5):
                t = ci[ty * 32 + tx]; at = ci[0x3C0 + (ty // 4) * 8 + tx // 4]
                p = (at >> (((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2)) & 3
                cells.append([bytes(ch[0x1000 + 16 * t:0x1000 + 16 * t + 16]).hex(), bytes([pal[0], pal[4 * p + 1], pal[4 * p + 2], pal[4 * p + 3]]).hex()])
        return cells
    cards, mems = {}, [os.path.join(out, 'empty.mem'), m540]
    deck = list(range(53))
    for r in range(6):
        ten = (deck[r * 10:r * 10 + 10] + [52] * 10)[:10]
        b = bytearray(st)
        for i, c in enumerate(ten): b[wa + 0x1600 + i] = c
        sp = os.path.join(tmp, f'd{r}.cs'); open(sp, 'wb').write(b)
        for f, part in ((HAND_AT, ten[:5]), (DRAWN_AT, ten[5:])):
            mp = os.path.join(out, f'deal{r}_{f}.mem'); mems.append(mp)
            run('--load-state', sp, '--frames', B + f + 1, '--input', draw_in, '--mem-frame', B + f, '--mem-out', mp,
                '--screenshot', mp[:-4] + '.png')
            for s, c in enumerate(part): cards.setdefault(f'{c:02x}', grid(mp, s))
    missing = [f'{c:02x}' for c in deck if f'{c:02x}' not in cards]
    if missing: sys.exit(f'capture_casino: cards not shown: {missing}')

    # the other tiles of the poker screen and the pointing hand (sprite)
    in_cards = {(x, y) for x0, y0 in SLOTS for x in range(x0, x0 + 5) for y in range(y0, y0 + 7)}
    screen, sprites = set(), set()
    for mp in mems:
        cm = load(mp); ci, ch, pal, oam = cm['ciram'], cm['chr_ram'], cm['palette'], cm['oam']
        for ty in range(30):
            for tx in range(32):
                if (tx, ty) in in_cards: continue
                t = ci[ty * 32 + tx]; d = bytes(ch[0x1000 + 16 * t:0x1000 + 16 * t + 16])
                if not any(d): continue
                at = ci[0x3C0 + (ty // 4) * 8 + tx // 4]; p = (at >> (((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2)) & 3
                screen.add((d.hex(), bytes([pal[0], pal[4 * p + 1], pal[4 * p + 2], pal[4 * p + 3]]).hex()))
        for i in range(64):
            y, t, a = oam[4 * i], oam[4 * i + 1], oam[4 * i + 2]
            if y >= 0xEF: continue
            d = bytes(ch[16 * t:16 * t + 16]); q = a & 3
            if any(d): sprites.add((d.hex(), 'ff' + bytes(pal[16 + 4 * q + 1:16 + 4 * q + 4]).hex()))
    json.dump({'slots': SLOTS, 'cards': cards, 'back': grid(m540, 0), 'empty': grid(os.path.join(out, 'empty.mem'), 0),
               'screen_tiles': sorted(screen), 'sprites': sorted(sprites)}, open(os.path.join(out, 'cards.json'), 'w'))
    print(f'poker: {len(cards)} cards, {len(screen)} other screen tiles, {len(sprites)} sprite tiles -> {out}')

if __name__ == '__main__':
    main()
