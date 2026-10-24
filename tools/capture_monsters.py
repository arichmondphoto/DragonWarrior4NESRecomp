"""Capture every Dragon Warrior IV battle monster from the running game.

Drives the Chapter 1 route to the first random encounter (frame 8718, just
after the game fills the battle slots), saves a state, then for each monster
ID writes a one-monster fixed battle (slots $6E45-$6E48 = ID,$FF,$FF,$FF;
counts $6E49-$6E4C = 1,0,0,0; flags $6E44 = $C0, as the game's own fixed-battle
setup does) into a copy of that state and runs into the battle. For each ID it writes:

    OUT/NNN.png   the battle screen (native 256x240)
    OUT/NNN.mem   the --mem-out dump at the battle screen (CHR RAM, nametables,
                  palette, RAM) used to key HD tiles
    OUT/names.json  the name the battle window shows (one word for long names)

usage: capture_monsters.py HOST OUT [--first 0] [--last 194] [--jobs 2]
"""
import argparse, json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from make_font_hdpack import GLYPHS

ROM = 'rom/DragonWarriorIV.nes'
ROUTE = 'routes/ch1_to_first_battles.txt'
ENCOUNTER_FRAME = 8718      # slots written at 8716; battle graphics load later
BATTLE_FRAME = 8900         # battle screen fully drawn
SLOTS = 0x6E45 - 0x6000     # offset of the battle slots in WRAM

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('host'); ap.add_argument('out')
    ap.add_argument('--first', type=int, default=0)
    ap.add_argument('--last', type=int, default=194)
    ap.add_argument('--jobs', type=int, default=2)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='dw4mon')
    base, dump = os.path.join(tmp, 'enc.cycstate'), os.path.join(tmp, 'enc.mem')
    subprocess.run([a.host, ROM, '--frames', str(ENCOUNTER_FRAME + 1), '--no-save', '--input', ROUTE,
                    '--mem-frame', str(ENCOUNTER_FRAME), '--mem-out', dump,
                    '--save-state', f'{ENCOUNTER_FRAME}:{base}'], check=True, capture_output=True)
    state = open(base, 'rb').read()
    wram_at = state.find(load(dump)['wram'])
    if wram_at < 0: sys.exit('could not locate WRAM inside the save state')

    def one(mid):
        st = bytearray(state)
        # As the game's fixed-battle setup ($A1AD) would: one monster, count 1,
        # battle flags $C0 (see force_formation.py).
        st[wram_at + SLOTS: wram_at + SLOTS + 4] = bytes([mid, 0xFF, 0xFF, 0xFF])
        st[wram_at + SLOTS + 4: wram_at + SLOTS + 8] = bytes([1, 0, 0, 0])
        st[wram_at + SLOTS - 1] = 0xC0
        path = os.path.join(tmp, f'{mid}.cycstate'); open(path, 'wb').write(st)
        stem = os.path.join(a.out, f'{mid:03d}')
        subprocess.run([a.host, ROM, '--load-state', path, '--frames', str(BATTLE_FRAME + 1), '--no-save',
                        '--mem-frame', str(BATTLE_FRAME), '--mem-out', stem + '.mem',
                        '--screenshot', stem + '.png'], capture_output=True, timeout=120)
        os.remove(path)
        ci = load(stem + '.mem')['ciram']
        return mid, ''.join((GLYPHS.get(0x100 + ci[19 * 32 + c]) or ' ') for c in range(13, 27)).strip()

    with ThreadPoolExecutor(a.jobs) as ex:
        names = dict(ex.map(one, range(a.first, a.last + 1)))
    json.dump({str(k): v for k, v in sorted(names.items())}, open(os.path.join(a.out, 'names.json'), 'w'), indent=1)
    print(f'captured {len(names)} monsters -> {a.out}')

if __name__ == '__main__':
    main()
