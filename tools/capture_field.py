"""Capture every field map (towns, castles, shrines, dungeons, overworld) by
warping into it from the Chapter 1 route — no playthrough.

Dragon Warrior IV keeps the current map in $63 (map) / $64 (submap). Each map
has an exit table in RAM at $05A0: 7-byte entries (x, y, dest map, dest
submap, dest x, dest y, flags) that the exit routine (bank 27 $8020) copies
into $63/$64/$44/$45 when the hero steps on an exit. At frame 5050 of the
route the hero is one step from Burland Castle's exit, so writing a
destination into both entries of that table makes the game load any map.

After loading, the game keeps (WRAM):
  $7600  32 metatiles x 4 tile numbers (TL TR BL BR; BG pattern table $1000)
  $7680  overworld only: 16 shoreline variants x 4 tile numbers
  $76C0  sub-palette (0-3) of each of the 32 metatiles
  $7800  the decoded map, one byte per cell (low 5 bits = metatile)
$28 is 0 on overworld-style maps. The map list (bank 17 $B08D) gives the
submaps of each of the 73 maps.

Night: the palette is chosen at map load from the clock at WRAM $62ED (bank
14 $BB02: night once it is >= $78). With --night the clock is set to $80
before each warp and files are named MM_SS_n (towns, castles and the
overworld load their night palettes; dungeons look the same).

Writes OUT/MM_SS.mem / .png per submap (+ index.json). Maps whose palette is
still fading in are retried with more frames.

usage: capture_field.py HOST OUT [--jobs 2] [--night]
"""
import argparse, json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load

ROM = 'rom/DragonWarriorIV.nes'
ROUTE = 'routes/ch1_to_first_battles.txt'
EXIT_FRAME = 5050
R = open(ROM, 'rb').read()[16:]
def rd(b, a): return R[b * 0x4000 + (a - 0x8000)]
def rw(b, a): return rd(b, a) | rd(b, a + 1) << 8

def submaps(mp):
    a, out = rw(23, 0xB08D + 2 * mp), []
    while rd(23, a) != 0xFF and len(out) < 40:
        out.append((rd(23, a), rw(23, a + 1))); a += 3
    return out

def size(mp, sub):
    """Map width/height from the map header (bank 9 maps 00-2C, 10 to 44, 11 after)."""
    addr = submaps(mp)[sub][1]
    pref = 9 if mp < 0x2D else 10 if mp < 0x45 else 11
    for b in [pref] + [x for x in (9, 10, 11) if x != pref]:
        w, h = rd(b, addr), rd(b, addr + 1)
        if 4 <= w <= 160 and 4 <= h <= 160: return w, h
    return 20, 20

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('host'); ap.add_argument('out')
    ap.add_argument('--jobs', type=int, default=2); ap.add_argument('--night', action='store_true')
    a = ap.parse_args(); sfx = '_n' if a.night else ''
    os.makedirs(a.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='dw4field')
    base, dump = os.path.join(tmp, 'exit.cs'), os.path.join(tmp, 'exit.mem')
    subprocess.run([a.host, ROM, '--frames', str(EXIT_FRAME + 1), '--no-save', '--input', ROUTE, '--mem-frame',
                    str(EXIT_FRAME), '--mem-out', dump, '--save-state', f'{EXIT_FRAME}:{base}'], check=True, capture_output=True)
    st = open(base, 'rb').read(); ram = load(dump)['ram']
    ram_at = st.find(bytes(ram[0x500:0x600])) - 0x500
    if a.night:
        wram_at = st.find(bytes(load(dump)['wram'][:0x400]))
        st = bytearray(st); st[wram_at + 0x2ED] = 0x80; st = bytes(st)

    def warp(mp, sub, frames):
        w, h = size(mp, sub)
        b = bytearray(st)
        for e in (0x5A0, 0x5A7):
            b[ram_at + e + 2: ram_at + e + 7] = bytes([mp, sub, min(w // 2, 120), min(h // 2, 120), 0x82])
        p = os.path.join(tmp, f'{mp}_{sub}.cs'); open(p, 'wb').write(b)
        stem = os.path.join(a.out, f'{mp:02d}_{sub:02d}{sfx}'); end = EXIT_FRAME + frames
        subprocess.run([a.host, ROM, '--load-state', p, '--frames', str(end + 1), '--no-save', '--input', ROUTE,
                        '--mem-frame', str(end), '--mem-out', stem + '.mem', '--screenshot', stem + '.png'],
                       check=True, capture_output=True)
        os.remove(p)
        m = load(stem + '.mem')
        return m

    def one(job):
        mp, sub = job
        for frames in (160, 450):
            m = warp(mp, sub, frames)
            if max(m['palette'][:16]) != min(m['palette'][:16]): break
        r = m['ram']
        return {'map': mp, 'sub': sub, 'loaded': [r[0x63], r[0x64]], 'kind': r[0x28]}

    jobs = [(mp, sub) for mp in range(73) for sub in range(len(submaps(mp)))]
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, jobs))
    # The overworld itself, from the route (frame 7200 is on the world map).
    if not a.night: subprocess.run([a.host, ROM, '--frames', '7201', '--no-save', '--input', ROUTE, '--mem-frame', '7200',
                    '--mem-out', os.path.join(a.out, 'world.mem'), '--screenshot', os.path.join(a.out, 'world.png')],
                   check=True, capture_output=True)
    json.dump(res, open(os.path.join(a.out, f'index{sfx}.json'), 'w'), indent=0)
    print(f'captured {len(res)} submaps{" at night" if a.night else " + the overworld"} -> {a.out}')

if __name__ == '__main__':
    main()
