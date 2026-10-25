"""Capture every walking character type in the game (all chapters' heroes,
townspeople, soldiers, animals, monsters on the map...), not only the ones a
Chapter 1 route reaches.

How the game loads them (bank 28 $9A37 -> far call bank 8 function 4, $85D3):
a map's code asks for a character *type*; the loader looks the type up in the
table at bank 8 $979B (24 bytes per type: 8 x [tile source lo, tile source
hi + flags, palette/flags]) and builds the slot's frame table at WRAM
$7200+slot*64 plus the CHR tiles. Types $00-$6B exist ($859B folds the raw
numbers: $48-$4F -> $00-$07, $53+ -> -$0B). $00-$07 are the eight heroes.

The types are immediates in the (recompiled) map code, so instead this
patches the *table*: a town's own types (Burland town, map 14) are pointed
at other types' entries, ten at a time, the host loads the patched ROM
(NESRECOMP_ALLOW_PRG_MISMATCH, patch 0008) and warps into the town from the
route state, and each person slot then holds the chosen type.

Writes OUT/run_NN.mem (+ .png) and OUT/types.json:
  {"mem": "run_NN.mem", "slots": {"<slot>": <type>, ...}} per run.

usage: capture_types.py HOST OUT [--jobs 2]
"""
import argparse, json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from capture_field import ROM, ROUTE, EXIT_FRAME, size

TABLE = 0x10 + 8 * 0x4000 + (0x979B - 0x8000)   # file offset of bank 8 $979B
NTYPES = 0x6C
TOWN = (14, 0)

def fold(raw):
    """Raw type number (as kept in $6E5E) -> table index ($859B)."""
    r = raw & 0x7F
    if r >= 0x53: return r - 0x0B
    if 0x48 <= r < 0x50: return r - 0x48
    return r

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('host'); ap.add_argument('out')
    ap.add_argument('--jobs', type=int, default=2); a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='dw4types')
    env = dict(os.environ, NESRECOMP_ALLOW_PRG_MISMATCH='1')
    # an empty mod catalog: the player's installed packs (the Mac app keeps
    # one beside its settings) must not take part, and the patched ROMs
    # don't match an installed pack's target anyway
    mods = os.path.join(tmp, 'mods'); os.makedirs(mods)
    rom = open(ROM, 'rb').read()
    base, dump = os.path.join(tmp, 'exit.cs'), os.path.join(tmp, 'exit.mem')
    subprocess.run([a.host, ROM, '--frames', str(EXIT_FRAME + 1), '--no-save', '--input', ROUTE, '--mods-root', mods,
                    '--mem-frame', str(EXIT_FRAME), '--mem-out', dump, '--save-state', f'{EXIT_FRAME}:{base}'],
                   check=True, capture_output=True)
    st = open(base, 'rb').read(); ram = load(dump)['ram']
    ram_at = st.find(bytes(ram[0x500:0x600])) - 0x500
    w, h = size(*TOWN)
    b = bytearray(st)
    for e in (0x5A0, 0x5A7):
        b[ram_at + e + 2: ram_at + e + 7] = bytes([TOWN[0], TOWN[1], w // 2, h // 2, 0x82])
    warp_state = os.path.join(tmp, 'town.cs'); open(warp_state, 'wb').write(b)

    def town(rom_path, stem):
        end = EXIT_FRAME + 160
        r = subprocess.run([a.host, rom_path, '--load-state', warp_state, '--frames', str(end + 1), '--no-save', '--input',
                            ROUTE, '--mods-root', mods, '--mem-frame', str(end), '--mem-out', stem + '.mem',
                            '--screenshot', stem + '.png'], capture_output=True, text=True, env=env)
        if r.returncode:
            sys.exit(f'capture_types: the game exited with {r.returncode} for {os.path.basename(rom_path)}:\n'
                     f'{(r.stdout + r.stderr).strip()[-800:]}\n(was the host rebuilt with patches/nesrecomp/0008?)')
        return load(stem + '.mem')

    # The town's own list: which table entry each person slot (4 + index) uses.
    m = town(ROM, os.path.join(tmp, 'plain'))
    lst = []
    for i in range(16):
        if m['wram'][0xE5E + i] == 0xFF: break
        lst.append(m['wram'][0xE5E + i])
    carriers, seen = [], set()           # (slot, table entry) loaded in full (no $80 flag), one per entry
    for i, raw in enumerate(lst):
        if raw & 0x80 or fold(raw) in seen: continue
        seen.add(fold(raw)); carriers.append((4 + i, fold(raw)))
    print(f'town types {[hex(x) for x in lst]} -> {len(carriers)} slots per run')

    jobs = [list(range(NTYPES))[k:k + len(carriers)] for k in range(0, NTYPES, len(carriers))]
    def one(n):
        want = jobs[n]; patched = bytearray(rom)
        for (slot, entry), t in zip(carriers, want):
            patched[TABLE + 24 * entry: TABLE + 24 * entry + 24] = rom[TABLE + 24 * t: TABLE + 24 * t + 24]
        p = os.path.join(tmp, f'run{n}.nes'); open(p, 'wb').write(patched)
        town(p, os.path.join(a.out, f'run_{n:02d}')); os.remove(p)
        return {'mem': f'run_{n:02d}.mem', 'slots': {str(s): t for (s, e), t in zip(carriers, want)}}
    with ThreadPoolExecutor(a.jobs) as ex:
        res = list(ex.map(one, range(len(jobs))))
    json.dump(res, open(os.path.join(a.out, 'types.json'), 'w'), indent=0)
    print(f'{NTYPES} character types in {len(res)} runs -> {a.out}/types.json')

if __name__ == '__main__':
    main()
