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
  battles   every monster ID as a forced battle played on by the route's own
            battle input for --span frames, sampled every --every frames:
            attacks, damage blinks, spells and the battle's end
  dusk      the overworld while night falls (the four palette steps of
            tools/capture_field.py's nightfall walk), sampled over time
  chars     every walking character type (tools/capture_types.py's table
            patch: the pack is loaded with patched ROMs) in a town, sampled
            while they walk about
  report    merge the results: OUT/report.json, OUT/report.md and contact
            sheets OUT/sheet_*.jpg of the views with something missing

maps --times N samples each view N times, --every frames apart (animated
tiles: fountains, flames, the map 21 crowd). A sampled view's result is the
union of its samples' missing pieces; its picture is the worst sample.

Results are per view in OUT/<mode>/*.json (+ a side-by-side picture when
something is missing), so a stopped sweep resumes where it was.

usage: hd_coverage.py HOST MODS OUT maps|monsters|battles|dusk|chars|report [--jobs 2] [--views 3]
           [--only MAP[:SUB]] [--times 1] [--every 12] [--span 480]
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

    def view(self, state, end, name, out_dir, info, keep_input=True, start=None, every=0, rom=ROM, env=None, inp=None):
        """Run `state` to frame `end`, analyze it, write OUT/<mode>/<name>.json.
        With `start` and `every`: analyze every `every`th frame from `start` to `end`
        and merge (missing pieces: union; counts and picture: the worst frame)."""
        js = os.path.join(out_dir, name + '.json')
        if os.path.exists(js): return json.load(open(js))
        p = os.path.join(self.tmp, name + '.cs'); open(p, 'wb').write(state)
        stem = os.path.join(self.tmp, name); root = self.roots.get()
        frames = [end] if not every else list(range(start, end + 1, every))
        args = [self.a.host, rom, '--load-state', p, '--frames', str(end + 1), '--no-save', '--mods-root', root,
                '--present-out', stem + '_d.png', '--screenshot', stem + '_n.png', '--mem-frame', str(frames[0]), '--mem-out', stem + '.mem']
        if every: args += ['--present-every', str(every), '--shot-every', str(every), '--mem-every', str(every)]
        if inp or keep_input: args += ['--input', inp or ROUTE]
        r = subprocess.run(args, capture_output=True, text=True, env=dict(self.env, **(env or {})))
        self.roots.put(root); os.remove(p)
        def files(f):
            if not every: return stem + '_d.png', stem + '_n.png', stem + '.mem'
            return (f'{stem}_d_{f:05d}.png', f'{stem}_n_{f:05d}.png', stem + '.mem' if f == frames[0] else f'{stem}.mem.{f}')
        if r.returncode or not all(os.path.exists(x) for x in files(frames[-1])):
            res = dict(info, error=(r.stdout + r.stderr).strip()[-200:])
        else:
            res, worst = None, -1
            for f in frames:
                d, n, mem = files(f)
                if not os.path.exists(d): continue
                pic = os.path.join(self.tmp, f'{name}_{f}.jpg')
                one = analyze(d, n, mem, pic)
                m = load(mem); one['loaded'] = [m['ram'][0x63], m['ram'][0x64]]
                one['dark'] = max(m['palette'][:16]) == min(m['palette'][:16])
                score = one['bg'] + 8 * one['sp']
                if res is None: res = dict(info, **one, samples=0, bad_frames=[])
                else:
                    seen = {(k[0], k[1]) for k in res['bg_keys']}
                    res['bg_keys'] += [k for k in one['bg_keys'] if (k[0], k[1]) not in seen]
                    seen = {(k[0], k[1]) for k in res['sp_keys']}
                    res['sp_keys'] += [k for k in one['sp_keys'] if (k[0], k[1]) not in seen]
                    res['unknown_bg'] += one['unknown_bg']
                res['samples'] += 1
                if score > 0: res['bad_frames'].append(f)
                if score > worst:
                    worst = score; res.update(bg=one['bg'], sp=one['sp'], frame=f, loaded=one['loaded'], dark=one['dark'])
                    if os.path.exists(pic): os.replace(pic, os.path.join(out_dir, name + '.jpg'))
                if os.path.exists(pic): os.remove(pic)
            if not every: res.pop('samples'); res.pop('bad_frames')
        for f in frames:
            for x in files(f):
                if os.path.exists(x): os.remove(x)
        for x in glob.glob(glob.escape(stem) + '_[dn]*.png') + glob.glob(glob.escape(stem + '.mem') + '*'):
            os.remove(x)
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
            ev, t = self.a.every, self.a.times
            def at(end, info):
                if t <= 1: return self.view(bytes(b), end, name, out, info)
                s0 = -(-end // ev) * ev                               # samples fall on multiples of --every
                return self.view(bytes(b), s0 + ev * (t - 1), name, out, info, start=s0, every=ev)
            res = at(EXIT_FRAME + 200, info)
            if res.get('dark') and 'retry' not in res:                # still fading in: give it longer
                os.remove(os.path.join(out, name + '.json'))
                res = at(EXIT_FRAME + 456, dict(info, retry=True))
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

    def battles(self):
        """Each monster in a forced battle, played on with the route's battle input, sampled over time."""
        out = os.path.join(self.a.out, 'battles'); os.makedirs(out, exist_ok=True)
        st, m = self.base(ENC_FRAME); off = st.find(m['wram'])
        ev = self.a.every; start = -(-(ENC_FRAME + 120) // ev) * ev       # after the fade-in (monsters check that)
        def one(i):
            b = bytearray(st); b[off + 0xE45:off + 0xE49] = bytes([i, 255, 255, 255])
            name = f'b{i:03d}'
            return self.view(bytes(b), start + ev * (self.a.span // ev), name, out, {'mode': 'battles', 'name': name, 'monster': i},
                             start=start, every=ev)
        ids = sorted({m for m, _ in self.a.only}) if self.a.only else range(NMONSTERS)
        self.run(list(ids), one, 'battles')

    def dusk(self):
        """The overworld while night falls: capture_field.py's nightfall walk at each clock step."""
        out = os.path.join(self.a.out, 'dusk'); os.makedirs(out, exist_ok=True)
        st, m = self.base(7200); wat = st.find(bytes(m['wram'][:0x400]))
        ev = self.a.every
        def one(job):
            n, clock = job
            b = bytearray(st); b[wat + 0x2ED] = clock
            name = f'dusk{n}'
            s0 = -(-7212 // ev) * ev
            return self.view(bytes(b), s0 + ev * (500 // ev), name, out, {'mode': 'dusk', 'name': name, 'clock': clock},
                             start=s0, every=ev)
        self.run([(1, 0x77), (2, 0x7B), (3, 0x7F), (4, 0x83)], one, 'nightfall walks')

    def chars(self):
        """Every walking character type, by capture_types.py's table patch, in a town, while they walk about."""
        from capture_types import TABLE, NTYPES, TOWN, fold
        out = os.path.join(self.a.out, 'chars'); os.makedirs(out, exist_ok=True)
        st, m = self.base(EXIT_FRAME)
        ram_at = st.find(bytes(m['ram'][0x500:0x600])) - 0x500
        w, h = size(*TOWN); b = bytearray(st)
        for e in (0x5A0, 0x5A7): b[ram_at + e + 2: ram_at + e + 7] = bytes([TOWN[0], TOWN[1], w // 2, h // 2, 0x82])
        st = bytes(b)
        ev = self.a.every; s0 = -(-(EXIT_FRAME + 160) // ev) * ev; end = s0 + ev * (self.a.span // ev)
        idle = os.path.join(self.tmp, 'idle.in')
        open(idle, 'w').write(''.join(l for l in open(ROUTE) if l.strip() and int(l.split()[0]) <= EXIT_FRAME + 1) + f'{EXIT_FRAME + 1} -\n')
        # which of the town's person slots load a full type of their own (capture_types.py)
        mem = os.path.join(self.tmp, 'plain_types.mem')
        subprocess.run([self.a.host, ROM, '--load-state', self._state_file(st), '--frames', str(EXIT_FRAME + 161), '--no-save',
                        '--input', idle, '--mods-root', self.a.mods, '--mem-frame', str(EXIT_FRAME + 160), '--mem-out', mem],
                       check=True, capture_output=True)
        wr = load(mem)['wram']; lst = []
        for i in range(16):
            if wr[0xE5E + i] == 0xFF: break
            lst.append(wr[0xE5E + i])
        carriers, seen = [], set()
        for i, raw in enumerate(lst):
            if raw & 0x80 or fold(raw) in seen: continue
            seen.add(fold(raw)); carriers.append((4 + i, fold(raw)))
        rom = open(ROM, 'rb').read()
        jobs = [list(range(NTYPES))[k:k + len(carriers)] for k in range(0, NTYPES, len(carriers))]
        def one(n):
            patched = bytearray(rom)
            for (slot, entry), t in zip(carriers, jobs[n]):
                patched[TABLE + 24 * entry: TABLE + 24 * entry + 24] = rom[TABLE + 24 * t: TABLE + 24 * t + 24]
            p = os.path.join(self.tmp, f'types{n}.nes'); open(p, 'wb').write(patched)
            name = f'types_{n:02d}'
            r = self.view(st, end, name, out, {'mode': 'chars', 'name': name, 'types': jobs[n]}, start=s0, every=ev,
                          rom=p, env={'NESRECOMP_ALLOW_PRG_MISMATCH': '1'}, inp=idle)
            os.remove(p); return r
        self.run(list(range(len(jobs))), one, 'character runs')

    def _state_file(self, st):
        p = os.path.join(self.tmp, f'st{len(st)}_{hash(st) & 0xFFFFFF:06x}.cs')
        if not os.path.exists(p): open(p, 'wb').write(st)
        return p

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
    ap.add_argument('mode', choices=('maps', 'monsters', 'battles', 'dusk', 'chars', 'report'))
    ap.add_argument('--jobs', type=int, default=2); ap.add_argument('--views', type=int, default=3)
    ap.add_argument('--fade-at', type=int, default=104, help='monsters: frames after the encounter of the fade-in frame to check (fade runs ~+96..+112)')
    ap.add_argument('--only', action='append', default=[], help='maps: MAP or MAP:SUB; battles: monster ID (repeatable)')
    ap.add_argument('--times', type=int, default=1, help='maps: samples per view, --every frames apart')
    ap.add_argument('--every', type=int, default=12, help='frames between samples (maps --times, battles, dusk, chars)')
    ap.add_argument('--span', type=int, default=480, help='battles, chars: frames sampled')
    a = ap.parse_args()
    a.only = {(int(s.split(':')[0]), int(s.split(':')[1]) if ':' in s else None) for s in a.only}
    os.makedirs(a.out, exist_ok=True)
    if a.mode == 'report': return report(a.out)
    s = Sweep(a)
    getattr(s, a.mode)()

if __name__ == '__main__':
    main()
