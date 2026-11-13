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

Overworld nightfall: on the world map the clock advances as the hero walks,
and the palette steps through dusk and early-night palettes on its way to
night (clock $78, $7C, $80, $84; dawn reverses them at $C0-$C8); the water
palette also alternates. The day run also walks the overworld across each
of those steps (clock set just before it, from route frame 7200) and saves
world_dusk1..4.mem (+ a second water phase each).

Colours over time: some maps cycle colours (lava rotates one sub-palette
every 16 frames) or show other colour sets than the one at the capture frame.
So each capture also stops the route's input at the capture frame (the hero
stands still), runs HOLD more frames with the host's --palette-log (nesrecomp
patch 0019) and keeps every background palette held for at least 8 frames
(fade steps last 3): OUT/MM_SS.pals, one 32-hex-digit palette per line,
read by tools/field_sheet.py.

Tiles over time: some maps animate their tiles by loading other pictures
into the tile memory (the crowd in map 21, fountains). The same run dumps the
memories every ANIM_EVERY frames after the capture frame and keeps those
whose background tiles differ from every dump kept so far for that map:
OUT/anim/MM_SS_FRAME[_n].mem, read by tools/field_sheet.py.

Where you stand: some maps change colours by area (map 40's lava corner, a
red cave floor, the sky castle). By day, maps larger than a screen are also
visited at up to VIEWS spread points (the same points tools/hd_coverage.py
checks): OUT/view/MM_SS_vK.mem and .pals, read by tools/field_sheet.py.

Writes OUT/MM_SS.mem / .png / .pals per submap (+ index.json). Maps whose
palette is still fading in are retried with more frames.

usage: capture_field.py HOST OUT [--jobs 2] [--night]
"""
import argparse, glob, json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load

ROM = 'rom/DragonWarriorIV.nes'
ROUTE = 'routes/ch1_to_first_battles.txt'
EXIT_FRAME = 5050
HOLD = 120                      # frames of palette log after the capture frame
ANIM_EVERY = 6                  # frames between the extra memory dumps (OUT/anim)
VIEWS = 3                       # extra viewpoints per map larger than a screen (by day)
MIN_HELD = 8                    # a palette must stay this long to count (fade steps last 3)

def held_palettes(log):
    """Background palettes (32 hex digits) held for at least MIN_HELD frames in a --palette-log file."""
    out, run, prev = [], 0, None
    for line in open(log):
        parts = line.split()
        if len(parts) != 2: continue
        bg = parts[1][:32]
        run = run + 1 if bg == prev else 1; prev = bg
        if run == MIN_HELD and bg not in out:
            b = bytes.fromhex(bg)
            if max(b) != min(b): out.append(bg)              # not a blank (all one colour) screen
    return out
R = open(ROM, 'rb').read()[16:]
def rd(b, a): return R[b * 0x4000 + (a - 0x8000)]
def rw(b, a): return rd(b, a) | rd(b, a + 1) << 8

def submaps(mp):
    a, out = rw(23, 0xB08D + 2 * mp), []
    while rd(23, a) != 0xFF and len(out) < 40:
        out.append((rd(23, a), rw(23, a + 1))); a += 3
    return out

def viewpoints(mp, sub, views=VIEWS):
    """Map cells to stand on: the middle, then up to `views` points spread over a map larger than a screen."""
    w, h = size(mp, sub); pts = [(w // 2, h // 2)]
    xs = [x for x in range(8, max(w - 7, 9), 15)]; ys = [y for y in range(7, max(h - 6, 8), 14)]
    grid = [(x, y) for y in ys for x in xs if abs(x - w // 2) > 6 or abs(y - h // 2) > 6]
    if grid and views:
        step = max(1, -(-len(grid) // views))
        pts += grid[step // 2::step][:views]
    return [(min(x, 120), min(y, 120)) for x, y in pts]

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
    ap.add_argument('--only', action='append', default=[], metavar='MAP[:SUB]', help='only these maps, no overworld (for checks)')
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

    def warp(mp, sub, frames, k=0):
        x, y = viewpoints(mp, sub)[k]
        b = bytearray(st)
        for e in (0x5A0, 0x5A7):
            b[ram_at + e + 2: ram_at + e + 7] = bytes([mp, sub, x, y, 0x82])
        p = os.path.join(tmp, f'{mp}_{sub}_{k}.cs'); open(p, 'wb').write(b)
        if k: os.makedirs(os.path.join(a.out, 'view'), exist_ok=True)
        stem = os.path.join(a.out, f'{mp:02d}_{sub:02d}{sfx}' if k == 0 else f'view/{mp:02d}_{sub:02d}_v{k}{sfx}')
        end = EXIT_FRAME + frames
        # the route's input up to the capture frame, then nothing: the hero stands still
        inp = os.path.join(tmp, f'{mp}_{sub}_{k}.in')
        open(inp, 'w').write(''.join(l for l in open(ROUTE) if l.strip() and int(l.split()[0]) <= end) + f'{end} -\n')
        log = os.path.join(tmp, f'{mp}_{sub}_{k}.pal')
        subprocess.run([a.host, ROM, '--load-state', p, '--frames', str(end + HOLD + 1), '--no-save', '--input', inp,
                        '--mem-frame', str(end), '--mem-out', stem + '.mem', '--palette-log', log] + (['--screenshot', stem + '.png'] if k == 0 else []) + [
                        '--mem-every', str(ANIM_EVERY)],
                       check=True, capture_output=True)
        # animated tiles: keep the later dumps whose background tiles are new
        anim = os.path.join(a.out, 'anim'); os.makedirs(anim, exist_ok=True)
        tag = f'{mp:02d}_{sub:02d}' + (f'_v{k}' if k else '')
        seen = {bytes(load(stem + '.mem')['chr_ram'][0x1000:0x2000])}
        for f in sorted(glob.glob(glob.escape(stem + '.mem') + '.*'), key=lambda f: int(f.rsplit('.', 1)[1])):
            m = load(f); bg = bytes(m['chr_ram'][0x1000:0x2000])
            if bg not in seen and max(m['palette'][:16]) != min(m['palette'][:16]):
                seen.add(bg)
                os.replace(f, os.path.join(anim, f'{tag}_{f.rsplit(".", 1)[1]}{sfx}.mem'))
            else: os.remove(f)
        # the frames from the capture on
        lines = [l for l in open(log) if l.split() and int(l.split()[0]) >= end]
        open(log, 'w').write(''.join(lines))
        open(stem + '.pals', 'w').write(''.join(x + '\n' for x in held_palettes(log)))
        for x in (p, inp, log): os.remove(x)
        m = load(stem + '.mem')
        return m

    def one(job):
        mp, sub = job
        for frames in (160, 450):
            m = warp(mp, sub, frames)
            if max(m['palette'][:16]) != min(m['palette'][:16]): break
        if not a.night:                                   # the other viewpoints (kept only if lit)
            for k in range(1, len(viewpoints(mp, sub))):
                for frames in (160, 450):
                    v = warp(mp, sub, frames, k)
                    if max(v['palette'][:16]) != min(v['palette'][:16]): break
        r = m['ram']
        return {'map': mp, 'sub': sub, 'loaded': [r[0x63], r[0x64]], 'kind': r[0x28]}

    jobs = [(mp, sub) for mp in range(73) for sub in range(len(submaps(mp)))]
    if a.only:
        want = [tuple(int(x) for x in o.split(':')) for o in a.only]
        jobs = [j for j in jobs if j in want or (j[0],) in want]
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, jobs))
    # The overworld itself, from the route (frame 7200 is on the world map).
    if not a.night and not a.only:
        wst = os.path.join(tmp, 'world.cs')
        subprocess.run([a.host, ROM, '--frames', '7201', '--no-save', '--input', ROUTE, '--mem-frame', '7200',
                        '--mem-out', os.path.join(a.out, 'world.mem'), '--screenshot', os.path.join(a.out, 'world.png'),
                        '--save-state', f'7200:{wst}'], check=True, capture_output=True)
        wm = load(os.path.join(a.out, 'world.mem')); wbase = open(wst, 'rb').read()
        wat = wbase.find(bytes(wm['wram'][:0x400])); day = bytes(wm['palette'][:16])
        def dusk(job):
            n, clock = job
            b = bytearray(wbase); b[wat + 0x2ED] = clock
            p = os.path.join(tmp, f'dusk{n}.cs'); open(p, 'wb').write(b)
            def at(f, stem):
                subprocess.run([a.host, ROM, '--load-state', p, '--frames', str(f + 1), '--no-save', '--input', ROUTE,
                                '--mem-frame', str(f), '--mem-out', stem + '.mem'], check=True, capture_output=True)
                return load(stem + '.mem')
            stem = os.path.join(a.out, f'world_dusk{n}')
            for f in range(7220, 7700, 20):                  # walk until the palette steps
                m = at(f, stem)
                if m['wram'][0x2ED] > clock and bytes(m['palette'][4:16]) != day[4:16]:
                    at(f + 10, stem + 'b')                    # the other water phase
                    return True
            for x in (stem + '.mem', stem + 'b.mem'):
                if os.path.exists(x): os.remove(x)
            return False
        with ThreadPoolExecutor(a.jobs) as ex:
            got = list(ex.map(dusk, [(1, 0x77), (2, 0x7B), (3, 0x7F), (4, 0x83)]))
        print(f'  overworld nightfall: {sum(got)} of 4 palette steps captured')
    json.dump(res, open(os.path.join(a.out, f'index{sfx}.json'), 'w'), indent=0)
    print(f'captured {len(res)} submaps{" at night" if a.night else " + the overworld"} -> {a.out}')

if __name__ == '__main__':
    main()
