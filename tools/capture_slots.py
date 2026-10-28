"""Capture the Endor casino's slot machine from the Chapter 1 route - no
playthrough.

Warp (as tools/capture_casino.py): the hero lands below the second machine of
the row at the top of the casino (map 4 sub 1, (17, 4)), steps up to (17, 3)
so he faces it, is given 100 coins (WRAM $62AD) and talks to it. Then three
rounds of: insert three coins (UP x3), pull (A), stop the reels (A x3), answer
"play again" with yes.

The machine is a still background (pattern table $1000) with the reel symbols
as 8x8 sprites (16 x 16 symbols: tiles n, n+1 over n+2, n+3); the reels'
windows are clipped by rows of eight blank sprites (the PPU shows only eight
per scanline). The payline lamps on the left are sprites too.

Every 4th frame of the session is dumped. Writes OUT/slots.json:
  "cells": {"tx,ty": [[CHR hex, palette hex], ...]}   every state of each cell
  "sprites": [[CHR hex, 'FF' + 3 colours], ...]        every sprite tile shown
  "symbols": [[[4 CHR hex], 'FF' + 3 colours], ...]    reel symbols (2x2)
and OUT/screen.png (the machine without sprites, 1x) + OUT/screen_sprites.png.

usage: capture_slots.py HOST OUT
"""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from field_sheet import NES
from capture_field import ROM, ROUTE, EXIT_FRAME

B = EXIT_FRAME
EVENTS = [(0, 'DOWN'), (70, '-'), (180, 'UP'), (190, '-'), (260, 'A'), (264, '-'), (300, 'A'), (304, '-'), (420, 'A'), (424, '-')]
for k in range(3):
    t = 450 + 600 * k
    for dt, b in ((0, 'UP'), (6, '-'), (20, 'UP'), (26, '-'), (40, 'UP'), (46, '-'), (70, 'A'), (76, '-'), (170, 'A'), (176, '-'),
                  (230, 'A'), (236, '-'), (290, 'A'), (296, '-'), (420, 'A'), (426, '-'), (480, 'A'), (486, '-'), (540, 'A'), (546, '-')):
        EVENTS.append((t + dt, b))
START, END = 440, 2300

def main():
    host, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True); tmp = tempfile.mkdtemp(prefix='dw4slots')
    def run(*args):
        subprocess.run([host, ROM, '--no-save', '--mods-root', tempfile.mkdtemp(prefix='mods', dir=tmp), *map(str, args)],
                       check=True, capture_output=True)
    route = [l for l in open(ROUTE).read().splitlines() if l.strip() and int(l.split()[0]) < B]
    inp = os.path.join(tmp, 'in.txt')
    open(inp, 'w').write('\n'.join(route + [f'{B + f} {b}' for f, b in sorted(EVENTS)]) + '\n')
    s0, m0 = os.path.join(tmp, 'exit.cs'), os.path.join(tmp, 'exit.mem')
    run('--frames', B + 1, '--input', ROUTE, '--save-state', f'{B}:{s0}', '--mem-frame', B, '--mem-out', m0)
    st = bytearray(open(s0, 'rb').read()); m = load(m0)
    ra = st.find(bytes(m['ram'][0x500:0x600])) - 0x500; wa = st.find(bytes(m['wram'][:0x400]))
    for e in (0x5A0, 0x5A7): st[ra + e + 2:ra + e + 7] = bytes([4, 1, 17, 4, 0x82])
    st[wa + 0x2AD] = 100
    prev = os.path.join(tmp, 'warp.cs'); open(prev, 'wb').write(st)
    # to the slot screen, then every 4th frame by chained save states
    first = os.path.join(tmp, f's{START}.cs')
    run('--load-state', prev, '--frames', B + START + 1, '--input', inp, '--save-state', f'{B + START}:{first}')
    prev = first
    cells, sprites, symbols = {}, set(), set()
    shot_done = False
    for f in range(START + 4, END + 1, 4):
        sp, mp = os.path.join(tmp, f's{f}.cs'), os.path.join(tmp, 'm.mem')
        args = ['--load-state', prev, '--frames', B + f + 1, '--input', inp, '--save-state', f'{B + f}:{sp}',
                '--mem-frame', B + f, '--mem-out', mp]
        if not shot_done: args += ['--screenshot', os.path.join(out, 'screen_sprites.png')]
        run(*args); os.remove(prev); prev = sp
        cm = load(mp); ci, ch, pal, oam = cm['ciram'], cm['chr_ram'], cm['palette'], cm['oam']
        if ci[2 * 32 + 8] != 0x90: continue                       # not the slot machine screen (JACKPOT tile)
        if not shot_done:
            shot_done = True; keep = mp + '.screen'; os.rename(mp, keep); mp = keep
            json.dump({'palette': list(pal)}, open(os.path.join(out, 'screen_palette.json'), 'w'))
            screen_mem = keep
        for ty in range(30):
            for tx in range(32):
                t = ci[ty * 32 + tx]; at = ci[0x3C0 + (ty // 4) * 8 + tx // 4]
                p = (at >> (((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2)) & 3
                v = [bytes(ch[0x1000 + 16 * t:0x1000 + 16 * t + 16]).hex(), bytes([pal[0], pal[4 * p + 1], pal[4 * p + 2], pal[4 * p + 3]]).hex()]
                lst = cells.setdefault(f'{tx},{ty}', [])
                if v not in lst: lst.append(v)
        by_xy = {}
        for i in range(64):
            y, t, a, x = oam[4 * i], oam[4 * i + 1], oam[4 * i + 2], oam[4 * i + 3]
            if y >= 0xEF: continue
            d = bytes(ch[16 * t:16 * t + 16]); q = a & 3
            if not any(d): continue
            key = (d.hex(), 'ff' + bytes(pal[16 + 4 * q + 1:16 + 4 * q + 4]).hex())
            sprites.add(key); by_xy[(x, y)] = (t, key)
        for (x, y), (t, key) in by_xy.items():                     # 2x2 symbols: t, t+1 right, t+2 below, t+3 below right
            r, d, dr = by_xy.get((x + 8, y)), by_xy.get((x, y + 8)), by_xy.get((x + 8, y + 8))
            if r and d and dr and r[0] == t + 1 and d[0] == t + 2 and dr[0] == t + 3 and t % 4 == 0:
                symbols.add(((key[0], r[1][0], d[1][0], dr[1][0]), key[1]))
    if not shot_done: sys.exit('capture_slots: never reached the slot machine')
    # the machine without sprites (from the nametable), for the art package
    cm = load(screen_mem); ci, ch, pal = cm['ciram'], cm['chr_ram'], cm['palette']
    from PIL import Image
    img = Image.new('RGB', (256, 240)); px = img.load()
    for ty in range(30):
        for tx in range(32):
            t = ci[ty * 32 + tx]; at = ci[0x3C0 + (ty // 4) * 8 + tx // 4]
            p = (at >> (((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2)) & 3
            for r in range(8):
                lo, hi = ch[0x1000 + 16 * t + r], ch[0x1000 + 16 * t + r + 8]
                for c in range(8):
                    v = ((lo >> (7 - c)) & 1) | (((hi >> (7 - c)) & 1) << 1)
                    col = NES[(pal[0] if v == 0 else pal[4 * p + v]) & 0x3F]
                    px[tx * 8 + c, ty * 8 + r] = ((col >> 16) & 255, (col >> 8) & 255, col & 255)
    img.save(os.path.join(out, 'screen.png'))
    os.rename(screen_mem, os.path.join(out, 'screen.mem'))
    json.dump({'cells': cells, 'sprites': sorted(sprites), 'symbols': sorted([list(k), p] for k, p in symbols)},
              open(os.path.join(out, 'slots.json'), 'w'))
    dyn = sum(1 for v in cells.values() if len(v) > 1)
    print(f'slots: {len(cells)} cells ({dyn} change), {len(sprites)} sprite tiles, {len(symbols)} reel symbols -> {out}')

if __name__ == '__main__':
    main()
