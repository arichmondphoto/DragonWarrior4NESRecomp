"""Capture the title screen and the castle door animation from the route.

Title: the intro without input; at frame 1200 the castle under a blue sky
(the logo being typed), at frame 2400 the finished title (red sunset).
Writes OUT/title_1200.mem/.png and OUT/title_2400.mem/.png.

Doors: Ragnar leaves Burland Castle through its front door around route
frame 5150; the door swings open over the next 80 frames. Between the
closed door and the open one (both map tiles with art) the game draws three
in-between frames straight into the
nametable (no map tile has them), so they had no HD art. This dumps every
4th frame, reads the 32x32 door area (nametable columns 30-31 of the second
table and 0-1 of the first, rows 12-15) and keeps each distinct state.
Writes OUT/doors.json: {"palette", "open": [4 map-tile CHR], "closed": [...],
"frames": [[4 x 64-byte metatile CHR hex] x 3]} (in opening order).

usage: capture_extras.py HOST OUT
"""
import json, os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from capture_field import ROM, ROUTE

def main():
    host, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True); tmp = tempfile.mkdtemp(prefix='dw4extra')
    for f in (1200, 2400):
        subprocess.run([host, ROM, '--frames', str(f + 1), '--no-save', '--mem-frame', str(f), '--mem-out',
                        os.path.join(out, f'title_{f}.mem'), '--screenshot', os.path.join(out, f'title_{f}.png')],
                       check=True, capture_output=True)
    st = os.path.join(tmp, 's.cs')
    subprocess.run([host, ROM, '--frames', '5141', '--no-save', '--input', ROUTE, '--save-state', f'5140:{st}'],
                   check=True, capture_output=True)
    cells = [(1, 30), (1, 31), (0, 0), (0, 1)]
    states, palette = [], None
    for f in range(5144, 5244, 4):
        mp = os.path.join(tmp, f'{f}.mem')
        subprocess.run([host, ROM, '--load-state', st, '--frames', str(f + 1), '--no-save', '--input', ROUTE,
                        '--mem-frame', str(f), '--mem-out', mp], check=True, capture_output=True)
        m = load(mp); ci, ch, pal = m['ciram'], m['chr_ram'], m['palette']
        tiles = []
        for ty in range(12, 16):
            for nt, tx in cells:
                base = nt * 0x400; t = ci[base + ty * 32 + tx]
                at = ci[base + 0x3C0 + (ty // 4) * 8 + tx // 4]; p = (at >> (((ty % 4) // 2) * 4 + ((tx % 4) // 2) * 2)) & 3
                tiles.append((bytes(ch[0x1000 + 16 * t:0x1000 + 16 * t + 16]), bytes([pal[0], pal[4 * p + 1], pal[4 * p + 2], pal[4 * p + 3]])))
        if any(p[1:] == b'\x0f\x0f\x0f' or p[1] in (0x0f,) and p[2] in (0x0f, 0x00) for c, p in tiles): continue   # faded in/out
        mts = [b''.join(tiles[(my * 2 + dy) * 4 + mx * 2 + dx][0] for dy in range(2) for dx in range(2)).hex()
               for my in range(2) for mx in range(2)]
        if not states or states[-1] != mts: states.append(mts)
        palette = tiles[0][1].hex()
    if len(states) < 3: sys.exit(f'capture_extras: expected the door to change at least twice, got {len(states)} states')
    # Ragnar walks out: the door is drawn closed, swings open, and stays open
    json.dump({'palette': palette, 'closed': states[0], 'open': states[-1], 'frames': states[1:-1]},
              open(os.path.join(out, 'doors.json'), 'w'), indent=0)
    print(f'title + door ({len(states) - 2} in-between frames) -> {out}')

if __name__ == '__main__':
    main()
