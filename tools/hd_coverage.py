"""Measure what an installed HD pack still leaves in 8-bit, across the game,
without a playthrough.

Every view is rendered twice from one run: the presented HD frame with
NESRECOMP_HDPACK_DEBUG=1 (background pixels with no HD art are magenta, sprite
pixels with none cyan) and the game's own 8-bit screenshot. An 8x8 cell counts
as missing when it has magenta and the 8-bit picture is not one flat colour
there (a blank cell shows nothing either way). Sprites count when a visible
sprite's box is mostly cyan. Each missing piece is then named by its tile
bytes and colours (from the memory dump), so the same piece seen on many
screens is one line of the report.

  maps      every submap by the exit-table warp of tools/capture_field.py:
            its centre by day and by night, and for maps larger than a screen
            up to --views more viewpoints spread over it (by day)
  monsters  every monster ID as a forced battle (tools/render_monsters_hd.py):
            the settled picture, and one frame of its fade-in
  report    merge the results: OUT/report.json, OUT/report.md and contact
            sheets OUT/sheet_*.jpg of the views with something missing

Results are per view in OUT/<mode>/*.json (+ a side-by-side picture when
something is missing), so a stopped sweep resumes where it was.

usage: hd_coverage.py HOST MODS OUT maps|monsters|report [--jobs 2] [--views 3] [--only MAP[:SUB]]
"""
import argparse, collections, glob, json, os, subprocess, sys, tempfile
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from vramdump import load, tile_pixels
from capture_field import ROM, ROUTE, EXIT_FRAME, submaps, size, viewpoints

ENC_FRAME = 8718                       # tools/render_monsters_hd.py: the encounter's slots are filled
NMONSTERS = 197

def analyze(dbg_png, shot_png, mem_path, pic_out):
    """-> {'bg': n cells, 'sp': n sprites, 'bg_keys': [[CHR, PAL, x, y]], 'sp_keys': [[CHR, PAL, x, y]]}"""
    d = np.asarray(Image.open(dbg_png).convert('RGB').resize((512, 480), Image.NEAREST)).astype(int)
    shot = Image.open(shot_png).convert('RGB')
    n = np.asarray(shot.resize((512, 480), Image.NEAREST)).astype(int)
    mag = (d[..., 0] > 240) & (d[..., 1] < 20) & (d[..., 2] > 240)
    cy = (d[..., 0] < 20) & (d[..., 1] > 240) & (d[..., 2] > 240)
    # per cell: the 8-bit colours under the magenta pixels only (a cell half
    # blank, half map is not missing anything when the magenta half is blank)
    big = 10 ** 6
    lo = np.where(mag[..., None], n, big).reshape(30, 16, 32, 16, 3).min(axis=(1, 3))
    hi = np.where(mag[..., None], n, -big).reshape(30, 16, 32, 16, 3).max(axis=(1, 3))
    flat = (hi - lo).max(-1) < 8
    cells = mag.reshape(30, 16, 32, 16).mean(axis=(1, 3)) > 0.05
    cells &= ~flat
    m = load(mem_path); ch, pal, oam, fr = m['chr_ram'], m['palette'], m['oam'], m['frame']
    res = {'bg': int(cells.sum()), 'sp': 0, 'bg_keys': [], 'sp_keys': [], 'unknown_bg': 0}
    # sprites: a visible sprite whose box is mostly cyan
    covered = np.zeros((240, 256), bool)
    for i in range(64):
        y, t, a, x = oam[4 * i], oam[4 * i + 1], oam[4 * i + 2], oam[4 * i + 3]
        if y >= 0xEF: continue
        y += 1
        box = cy[2 * y:2 * y + 16, 2 * x:2 * x + 16]
        covered[y:y + 8, x:x + 8] = True
        if box.size == 0 or box.mean() < 0.15: continue
        q = a & 3; cols = bytes(pal[16 + 4 * q + 1:16 + 4 * q + 4])
        if all((c & 0x0F) >= 0x0D for c in cols): continue           # drawn in black: nothing to see
        chr_ = bytes(ch[16 * t:16 * t + 16])
        if not any(chr_): continue
        res['sp'] += 1; res['sp_keys'].append([chr_.hex().upper(), 'FF' + cols.hex().upper(), x, y])
    # background cells: name the tile by matching the picture against the pattern table
    if cells.any():
        tiles = [tile_pixels(ch, 256 + t) for t in range(256)]
        subs = [[pal[0] & 0x3F] + [pal[s * 4 + k] & 0x3F for k in (1, 2, 3)] for s in range(4)]
        for r, c in zip(*np.nonzero(cells)):
            px = [[fr[r * 8 + y][c * 8 + x] & 0x3F for x in range(8)] for y in range(8)]
            hit = None
            for s in range(4):
                for t in range(256):
                    tp = tiles[t]
                    if all(subs[s][tp[y][x]] == px[y][x] for y in range(8) for x in range(8)): hit = (t, s); break
                if hit: break
            if hit is None:
                if covered[r * 8:r * 8 + 8, c * 8:c * 8 + 8].any(): res['bg'] -= 1      # a sprite over a blank cell
                else: res['unknown_bg'] += 1                                           # scrolled off the 8 px grid
                continue
            t, s = hit
            res['bg_keys'].append([bytes(ch[0x1000 + 16 * t:0x1000 + 16 * t + 16]).hex().upper(),
                                   bytes([pal[0]] + [pal[s * 4 + k] for k in (1, 2, 3)]).hex().upper(), int(c) * 8, int(r) * 8])
    if res['bg'] > 0 or res['sp'] > 0:
        pic = Image.new('RGB', (512, 240))
        pic.paste(Image.fromarray(d.astype(np.uint8)).resize((256, 240)), (0, 0)); pic.paste(shot, (256, 0))
        pic.save(pic_out, quality=82)
    return res

class Sweep:
    def __init__(self, a):
        self.a = a; self.tmp = tempfile.mkdtemp(prefix='dw4cov')
        self.env = dict(os.environ, NESRECOMP_HDPACK_DEBUG='1')
        # one mod catalog per worker (the game writes its mod state there, and
        # runs sharing one folder trip over each other): hard-linked copies
        import queue, shutil
        self.roots = queue.Queue()
        for i in range(a.jobs):
            d = os.path.join(self.tmp, f'mods{i}')
            try: shutil.copytree(a.mods, d, copy_function=os.link)
            except OSError: shutil.copytree(a.mods, d)
            self.roots.put(d)

    def base(self, frame):
        """A save state of the route at `frame`, made with the pack loaded (states are tied to the pack)."""
        st, dump = os.path.join(self.tmp, f'b{frame}.cs'), os.path.join(self.tmp, f'b{frame}.mem')
        subprocess.run([self.a.host, ROM, '--frames', str(frame + 1), '--no-save', '--input', ROUTE, '--mods-root', self.a.mods,
                        '--mem-frame', str(frame), '--mem-out', dump, '--save-state', f'{frame}:{st}'], check=True, capture_output=True)
        return open(st, 'rb').read(), load(dump)

    def view(self, state, end, name, out_dir, info, keep_input=True):
        """Run `state` to frame `end`, analyze it, write OUT/<mode>/<name>.json."""
        js = os.path.join(out_dir, name + '.json')
        if os.path.exists(js): return json.load(open(js))
        p = os.path.join(self.tmp, name + '.cs'); open(p, 'wb').write(state)
        stem = os.path.join(self.tmp, name); root = self.roots.get()
        args = [self.a.host, ROM, '--load-state', p, '--frames', str(end + 1), '--no-save', '--mods-root', root,
                '--present-out', stem + '_d.png', '--screenshot', stem + '_n.png', '--mem-frame', str(end), '--mem-out', stem + '.mem']
        if keep_input: args += ['--input', ROUTE]
        r = subprocess.run(args, capture_output=True, text=True, env=self.env)
        self.roots.put(root); os.remove(p)
        if r.returncode or not os.path.exists(stem + '_d.png'):
            res = dict(info, error=(r.stdout + r.stderr).strip()[-200:])
        else:
            res = dict(info, **analyze(stem + '_d.png', stem + '_n.png', stem + '.mem', os.path.join(out_dir, name + '.jpg')))
            m = load(stem + '.mem'); res['loaded'] = [m['ram'][0x63], m['ram'][0x64]]
            res['dark'] = max(m['palette'][:16]) == min(m['palette'][:16])
        for x in ('_d.png', '_n.png', '.mem'):
            if os.path.exists(stem + x): os.remove(stem + x)
        json.dump(res, open(js, 'w'))
        return res

    def maps(self):
        out = os.path.join(self.a.out, 'maps'); os.makedirs(out, exist_ok=True)
        st, m = self.base(EXIT_FRAME)
        ram_at = st.find(bytes(m['ram'][0x500:0x600])) - 0x500; wat = st.find(bytes(m['wram'][:0x400]))
        jobs = []
        for mp in range(73):
            for sub in range(len(submaps(mp))):
                if self.a.only and (mp, sub) not in self.a.only and (mp, None) not in self.a.only: continue
                # the middle, plus viewpoints spread over maps larger than a screen
                pts = viewpoints(mp, sub, self.a.views)
                for k, (x, y) in enumerate(pts):
                    jobs.append((mp, sub, k, x, y, False))
                jobs.append((mp, sub, 0, pts[0][0], pts[0][1], True))
        def one(job):
            mp, sub, k, x, y, night = job
            b = bytearray(st)
            for e in (0x5A0, 0x5A7): b[ram_at + e + 2:ram_at + e + 7] = bytes([mp, sub, x, y, 0x82])
            if night: b[wat + 0x2ED] = 0x80
            name = f'{mp:02d}_{sub:02d}_{k}{"n" if night else ""}'
            info = {'mode': 'maps', 'name': name, 'map': mp, 'sub': sub, 'x': x, 'y': y, 'night': night}
            res = self.view(bytes(b), EXIT_FRAME + 200, name, out, info)
            if res.get('dark') and 'retry' not in res:                # still fading in: give it longer
                os.remove(os.path.join(out, name + '.json'))
                res = self.view(bytes(b), EXIT_FRAME + 450, name, out, dict(info, retry=True))
            return res
        self.run(jobs, one, 'views')

    def monsters(self):
        out = os.path.join(self.a.out, 'monsters'); os.makedirs(out, exist_ok=True)
        st, m = self.base(ENC_FRAME); off = st.find(m['wram'])
        jobs = [(i, f) for i in range(NMONSTERS) for f in (ENC_FRAME + 182, ENC_FRAME + self.a.fade_at)]
        def one(job):
            i, end = job
            b = bytearray(st); b[off + 0xE45:off + 0xE49] = bytes([i, 255, 255, 255])
            name = f'm{i:03d}_{"final" if end == ENC_FRAME + 182 else "fade"}'
            return self.view(bytes(b), end, name, out, {'mode': 'monsters', 'name': name, 'monster': i}, keep_input=False)
        self.run(jobs, one, 'battle frames')

    def run(self, jobs, one, what):
        done = [0]
        def wrapped(j):
            r = one(j); done[0] += 1
            if done[0] % 50 == 0: print(f'  {done[0]}/{len(jobs)} {what}', flush=True)
            return r
        with ThreadPoolExecutor(self.a.jobs) as ex: res = list(ex.map(wrapped, jobs))
        bad = [r for r in res if r.get('bg', 0) > 0 or r.get('sp', 0) > 0]; err = [r for r in res if 'error' in r]
        print(f'{len(res)} {what}: {len(bad)} with something missing, {len(err)} failed')

def report(out):
    views = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(out, '*', '*.json')))]
    keys = {'bg': collections.OrderedDict(), 'sp': collections.OrderedDict()}
    for v in views:
        for kind in ('bg', 'sp'):
            for chr_, pal, x, y in v.get(kind + '_keys', []):
                e = keys[kind].setdefault(chr_, {'chr': chr_, 'palettes': [], 'views': [], 'at': [v['name'], x, y]})
                if pal not in e['palettes']: e['palettes'].append(pal)
                if v['name'] not in e['views']: e['views'].append(v['name'])
    bad = [v for v in views if v.get('bg', 0) > 0 or v.get('sp', 0) > 0]
    rep = {'views': len(views), 'failed': [v['name'] for v in views if 'error' in v], 'with_missing': len(bad),
           'bg_tiles': list(keys['bg'].values()), 'sprite_tiles': list(keys['sp'].values()),
           'by_view': [{k: v[k] for k in ('mode', 'name', 'bg', 'sp', 'unknown_bg') if k in v} for v in bad]}
    json.dump(rep, open(os.path.join(out, 'report.json'), 'w'), indent=1)
    lines = [f'# HD coverage report', '', f'{len(views)} views checked, {len(bad)} with something still in 8-bit, {len(rep["failed"])} failed.',
             f'{len(rep["bg_tiles"])} different background tiles and {len(rep["sprite_tiles"])} different sprite tiles have no HD art.', '']
    by_mode = collections.defaultdict(list)
    for v in bad: by_mode[v['mode']].append(v)
    for mode, vs in by_mode.items():
        lines += [f'## {mode}: {len(vs)} views', '']
        lines += [f'- `{v["name"]}`: {v.get("bg", 0)} background cells, {v.get("sp", 0)} sprites' for v in sorted(vs, key=lambda v: -(v.get('bg', 0) + 8 * v.get('sp', 0)))]
        lines.append('')
        pics = [os.path.join(out, mode, v['name'] + '.jpg') for v in sorted(vs, key=lambda v: -(v.get('bg', 0) + 8 * v.get('sp', 0)))]
        pics = [p for p in pics if os.path.exists(p)]
        for n in range(0, len(pics), 24):                       # contact sheets, 3 x 8 pairs
            sheet = Image.new('RGB', (3 * 512, 8 * 240), 'white')
            for i, p in enumerate(pics[n:n + 24]): sheet.paste(Image.open(p), ((i % 3) * 512, (i // 3) * 240))
            sheet.save(os.path.join(out, f'sheet_{mode}_{n // 24:02d}.jpg'), quality=80)
    open(os.path.join(out, 'report.md'), 'w').write('\n'.join(lines) + '\n')
    print('\n'.join(lines[:4])); print(f'-> {out}/report.md, report.json, sheet_*.jpg')

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('host'); ap.add_argument('mods'); ap.add_argument('out')
    ap.add_argument('mode', choices=('maps', 'monsters', 'report'))
    ap.add_argument('--jobs', type=int, default=2); ap.add_argument('--views', type=int, default=3)
    ap.add_argument('--fade-at', type=int, default=104, help='monsters: frames after the encounter of the fade-in frame to check (fade runs ~+96..+112)')
    ap.add_argument('--only', action='append', default=[], help='maps: MAP or MAP:SUB (repeatable)')
    a = ap.parse_args()
    a.only = {(int(s.split(':')[0]), int(s.split(':')[1]) if ':' in s else None) for s in a.only}
    os.makedirs(a.out, exist_ok=True)
    if a.mode == 'report': return report(a.out)
    s = Sweep(a)
    s.maps() if a.mode == 'maps' else s.monsters()

if __name__ == '__main__':
    main()
