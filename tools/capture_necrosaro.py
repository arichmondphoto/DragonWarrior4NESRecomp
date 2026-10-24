"""Capture every form of Necrosaro by letting the game transform him.

Necrosaro (monster ID $AE) changes form when his working HP reaches 0: bank 17
$9235 increments the form counter $6E7E and loads graphics ID $7206 from the
table at $926B (forms 1-7 -> $CD,$CE,$CE,$CF,$D0,$D1,$D2). Setting those
variables directly does not redraw him, so this drives the real battle:

  1. formation 25 (Necrosaro) is forced into the encounter save state;
  2. once the battle is up, his working HP ($727E/$727F, combatant record at
     $7274) is set to 1 and Ragnar ($60B6 HP, $60BB str, $60BC agi) is made
     strong enough to act first, survive and land a hit (re-applied every
     30 frames, since the later forms regenerate HP each round);
  3. A is tapped until $6E7E increments (the game transforms him), then until
     the command menu is back on screen (stable picture), and the battle is
     captured; repeat for the next form.

Writes OUT/necro_F.mem / .png for each form F (0 = the opening form) and
OUT/necrosaro.json with the form -> graphics ID list.

usage: capture_necrosaro.py HOST OUT
"""
import json, os, shutil, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
from force_formation import patch

ROM = 'rom/DragonWarriorIV.nes'
ROUTE = 'routes/ch1_to_first_battles.txt'
ENC = 8718
NECRO_FORMATION = 25

class Run:
    def __init__(self, host, tmp):
        self.host, self.tmp, self.n = host, tmp, 0
    def step(self, state, frame, frames, taps=False, png=None):
        """Run `frames` frames from `state` (which continues at frame+1)."""
        self.n += 1
        end = frame + frames
        inp = os.path.join(self.tmp, f'in{self.n}.txt')
        lines = []
        if taps:
            for f in range(frame + 3, end - 4, 25): lines += [f'{f} A', f'{f + 4} -']
        open(inp, 'w').write('\n'.join(lines) + '\n')
        out_state = os.path.join(self.tmp, f's{self.n}.cycstate'); mem = os.path.join(self.tmp, f'm{self.n}.mem')
        cmd = [self.host, ROM, '--load-state', state, '--frames', str(end + 1), '--no-save', '--input', inp,
               '--mem-frame', str(end), '--mem-out', mem, '--save-state', f'{end}:{out_state}']
        if png: cmd += ['--screenshot', png]
        subprocess.run(cmd, check=True, capture_output=True)
        return out_state, end, mem

def menu_up(mem):
    """The battle command window (its ATTACK row) is on screen."""
    ci = load(mem)['ciram']
    attack = bytes([0x25, 0x38, 0x38, 0x25, 0x27, 0x2F])           # A T T A C K
    return any(attack in bytes(ci[r * 32:(r + 1) * 32]) for r in range(18, 24))

def boost(state, wram_at):
    b = bytearray(open(state, 'rb').read())
    b[wram_at + 0x127E] = 1; b[wram_at + 0x127F] = 0          # Necrosaro HP 1
    b[wram_at + 0x0B6] = 0xE7; b[wram_at + 0x0B7] = 0x03      # Ragnar HP 999
    b[wram_at + 0x0BB] = 0xFF; b[wram_at + 0x0BC] = 0xFF      # strength, agility
    open(state, 'wb').write(b)

def main():
    host, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix='dw4necro')
    base, dump = os.path.join(tmp, 'enc.cycstate'), os.path.join(tmp, 'enc.mem')
    subprocess.run([host, ROM, '--frames', str(ENC + 1), '--no-save', '--input', ROUTE, '--mem-frame', str(ENC),
                    '--mem-out', dump, '--save-state', f'{ENC}:{base}'], check=True, capture_output=True)
    st = open(base, 'rb').read(); wram_at = st.find(load(dump)['wram'])
    start = os.path.join(tmp, 'necro.cycstate'); open(start, 'wb').write(patch(st, wram_at, NECRO_FORMATION))
    r = Run(host, tmp)
    state, frame, mem = r.step(start, ENC, 8960 - ENC)                    # battle drawn, menu up
    forms = []
    form = 0
    while True:
        w = load(mem)['wram']
        gid = w[0x1206]
        mem_out = os.path.join(out, f'necro_{form}.mem'); png_out = os.path.join(out, f'necro_{form}.png')
        state, frame, mem = r.step(state, frame, 2, png=png_out)
        shutil.copy(mem, mem_out); forms.append({'form': form, 'graphics_id': gid})
        print(f'form {form}: graphics ${gid:02X}')
        if gid == 0xD2: break
        for _ in range(120):                                               # until he transforms
            # Forms 4+ regenerate at the end of each round, so HP goes back to
            # 1 before every short step rather than once per form.
            w = load(mem)['wram']
            if w[0x127E] | w[0x127F] << 8 > 1: boost(state, wram_at)        # never undo a kill (HP 0)
            state, frame, mem = r.step(state, frame, 30, taps=True)
            if load(mem)['wram'][0xE7E] > form: break
        else:
            sys.exit(f'form {form}: no transformation')
        form = load(mem)['wram'][0xE7E]
        for _ in range(20):                                                # until the menu is back
            if menu_up(mem): break
            state, frame, mem = r.step(state, frame, 30, taps=True)
        else:
            print(f'form {form}: command menu not seen; capturing the battle as it is')
    json.dump(forms, open(os.path.join(out, 'necrosaro.json'), 'w'), indent=1)

if __name__ == '__main__':
    main()
