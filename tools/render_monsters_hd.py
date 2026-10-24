"""Render forced battles with an installed HD pack, for checking monster art.

usage: render_monsters_hd.py HOST MODS_ROOT OUTDIR ID [ID ...]
Writes OUTDIR/pNNN.png (the presented 10x frame) for each monster ID.
"""
import os, subprocess, sys, tempfile
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load
host, mods, out, ids = sys.argv[1], sys.argv[2], sys.argv[3], [int(x) for x in sys.argv[4:]]
os.makedirs(out, exist_ok=True)
tmp = tempfile.mkdtemp(prefix='dw4hd')
base, dump = os.path.join(tmp, 'enc.cycstate'), os.path.join(tmp, 'enc.mem')
subprocess.run([host, 'rom/DragonWarriorIV.nes', '--frames', '8719', '--no-save', '--input', 'routes/ch1_to_first_battles.txt',
                '--mods-root', mods, '--mem-frame', '8718', '--mem-out', dump, '--save-state', f'8718:{base}'],
               check=True, capture_output=True)
st = open(base, 'rb').read(); off = st.find(load(dump)['wram'])
for i in ids:
    b = bytearray(st); b[off + 0xE45:off + 0xE49] = bytes([i, 255, 255, 255])
    p = os.path.join(tmp, f'{i}.cycstate'); open(p, 'wb').write(b)
    r = subprocess.run([host, 'rom/DragonWarriorIV.nes', '--load-state', p, '--frames', '8901', '--no-save',
                        '--mods-root', mods, '--present-out', os.path.join(out, f'p{i:03d}.png')], capture_output=True, text=True)
    if 'incompatible' in r.stdout + r.stderr: print('state refused for', i)
print('rendered', len(ids))
