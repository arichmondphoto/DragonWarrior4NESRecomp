# Closed-loop route driver for DW4 headless runs.
# drive.py BASE_ROUTE STATE START_FRAME PLAN OUT_ROUTE OUT_STATE
# PLAN tokens: L3 R2 U5 D1 (tile steps), A/B/START taps as "tA", waits as "w60",
# "untilmap" moves "D*" = keep going down until map id changes.
import sys, subprocess, os
GAME='./build-headless/nes_game'; ROM='rom/DragonWarriorIV.nes'
base, state, frame, plan, out_route, out_state = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
route = [l.rstrip('\n') for l in open(base) if l.strip()]
DIRS = {'L':'LEFT','R':'RIGHT','U':'UP','D':'DOWN'}
tmp = 'out/drv'; os.makedirs(tmp, exist_ok=True)

def run(lines, nframes):
    """Run from current state for nframes with the given input lines; return ram and new state."""
    global state, frame
    inp = f'{tmp}/in.txt'; open(inp,'w').write('\n'.join(lines)+'\n' if lines else '')
    end = frame + nframes
    st = f'{tmp}/s{end}.cycstate'
    r = subprocess.run([GAME, ROM, '--load-state', state, '--frames', str(end+1), '--no-save',
                        '--input', inp, '--mem-frame', str(end), '--mem-out', f'{tmp}/m.txt',
                        '--save-state', f'{end}:{st}'], capture_output=True, text=True)
    if not os.path.exists(st): sys.exit('run failed: ' + r.stderr[-400:])
    m = {}
    for ln in open(f'{tmp}/m.txt'):
        q = ln.split()
        if len(q) > 2 and q[0] == 'ram':
            b = int(q[1][:-1], 16)
            for i, x in enumerate(q[2:]): m[b+i] = int(x, 16)
    state, frame = st, end
    route.extend(lines)
    return m

def pos(m): return (m[0x40], m[0x44], m[0x45])

m = run([], 2); print('start', frame, pos(m))
for tok in plan.split():
    if tok[0] == 'w': m = run([], int(tok[1:])); continue
    if tok[0] == 't':
        m = run([f'{frame+1} {tok[1:]}', f'{frame+5} -'], 30); print(tok, pos(m)); continue
    d = DIRS[tok[0]]; until_map = tok[1:] == '*'; n = 999 if until_map else int(tok[1:])
    start_map = pos(m)[0]; done = 0; fails = 0
    while done < n:
        before = pos(m)
        m = run([f'{frame+1} {d}', f'{frame+17} -'], 22)
        after = pos(m)
        if after != before: done += 1; fails = 0
        else:
            fails += 1
            if fails > 6: print('blocked', tok, after); break
            m = run([], 30)
        if until_map and pos(m)[0] != start_map:
            m = run([], 90); break
    print(tok, frame, pos(m))
open(out_route,'w').write('\n'.join(route)+'\n')
__import__('shutil').move(state, out_state) if state != out_state else None
print('end frame', frame, pos(m))
