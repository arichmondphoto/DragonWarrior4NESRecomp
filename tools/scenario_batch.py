#!/usr/bin/env python3
"""Batch-generate HD map tiles with Scenario (scenario.com), one job per tile,
all with the same model, prompt, settings and seed for a consistent look.

Input is the folder from tools/export_ai_tiles.py (DW4_map_tiles_for_AI).
For each tile it:
  1. scales the 160x160 tile up to the generation size (default 1024) and
     sends it as both the img2img start image and the ControlNet control
     image, so the layout stays where it is;
  2. waits for the job, downloads every result to raw/<ID>_<n>.png;
  3. saves the first result scaled back to 160x160 as out/<ID>.png
     (the file the HD pack builder reads; swap in another raw result by
     copying it over if you prefer it).
It keeps a log (log.jsonl), skips tiles that are already done (so a stopped
run can just be started again), and retries temporary errors.

Setup
  pip3 install pillow
  export SCENARIO_API_KEY=...  SCENARIO_API_SECRET=...   (Settings > API Keys)
  Train a style model on your monster sheet in Scenario (recommended), then
  put its model ID in the config (scenario_batch.json, see --write-config).

Typical use
  python3 scenario_batch.py --write-config            # writes scenario_batch.json
  python3 scenario_batch.py --dry-run --ids S001      # check the request + cost
  python3 scenario_batch.py --ids S001,W001,W002,W003,S013   # try a few tiles
  python3 scenario_batch.py                           # everything else

Options
  --tiles DIR      the export folder (default: ./DW4_map_tiles_for_AI)
  --out DIR        where results go (default: ./DW4_map_tiles_generated)
  --config FILE    settings (default: ./scenario_batch.json)
  --ids A,B,...    only these tiles; --section S|W|T|D  only one section
  --limit N        stop after N tiles
  --redo           regenerate tiles that already have a result
  --dry-run        send with ?dryRun=true (Scenario reports the cost, makes nothing)
  --jobs N         tiles in flight at once (default 2)
  --base-url URL   API root (default https://api.cloud.scenario.com/v1)
"""
import argparse, base64, csv, io, json, os, random, sys, threading, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

try:
    from PIL import Image
except ImportError:
    sys.exit('This script needs Pillow:  pip3 install pillow')

DEFAULT_CONFIG = {
    "_about": "Settings for scenario_batch.py. Every tile gets the same settings and seed. "
              "'body' is sent as the JSON request; {prompt}, {image}, {seed} are filled in per tile "
              "({image} = the tile as a PNG data URL at gen_size). Field names follow Scenario's "
              "ControlNet + Img2Img API (POST /generate/controlnet-img2img).",
    "endpoint": "/generate/controlnet-img2img",
    "gen_size": 1024,
    "input": "tiles_smooth",
    "upscale": "lanczos",
    "seed": 12345,
    "prompt": "top-down 2D fantasy RPG map tile, {subject}, hand-painted illustration in the style of "
              "classic Dragon Quest monster art, rich painterly shading, crisp dark outlines, saturated colours, "
              "same layout and colours as the input image, flat orthographic view, fills the whole square, "
              "no text, no border, no frame",
    "subjects": {
        "W": "overworld terrain seen from above",
        "T": "town or castle interior seen from above",
        "D": "dungeon, cave or tower seen from above",
        "S": "game map terrain seen from above"
    },
    "body": {
        "modelId": "PUT_YOUR_MODEL_ID_HERE",
        "prompt": "{prompt}",
        "image": "{image}",
        "controlImage": "{image}",
        "modality": "tile",
        "strength": 0.7,
        "numSamples": 2,
        "guidance": 3.5,
        "numInferenceSteps": 28,
        "width": 1024,
        "height": 1024,
        "seed": "{seed}"
    }
}

class Api:
    def __init__(self, base, key, secret, project=None):
        self.base = base.rstrip('/'); self.project = project
        self.auth = 'Basic ' + base64.b64encode(f'{key}:{secret}'.encode()).decode()

    def call(self, method, path, body=None, query=None, tries=6):
        q = dict(query or {})
        if self.project: q['projectId'] = self.project
        url = self.base + path + ('?' + '&'.join(f'{k}={v}' for k, v in q.items()) if q else '')
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(tries):
            req = urllib.request.Request(url, data=data, method=method,
                                         headers={'Authorization': self.auth, 'Content-Type': 'application/json',
                                                  'Accept': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    return json.loads(r.read() or b'{}')
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors='replace')[:500]
                if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                    time.sleep(min(60, 3 * 2 ** attempt) + random.random()); continue
                raise RuntimeError(f'{method} {path} -> HTTP {e.code}: {msg}')
            except urllib.error.URLError as e:
                if attempt < tries - 1: time.sleep(3 * 2 ** attempt); continue
                raise RuntimeError(f'{method} {path} -> {e.reason}')

    def download(self, url):
        for attempt in range(5):
            try:
                with urllib.request.urlopen(url, timeout=120) as r: return r.read()
            except Exception:
                if attempt == 4: raise
                time.sleep(3 * 2 ** attempt)

def data_url(img):
    b = io.BytesIO(); img.save(b, 'PNG')
    return 'data:image/png;base64,' + base64.b64encode(b.getvalue()).decode()

def fill(obj, values):
    """Replace {placeholders} in the body template; a value that is exactly
    one placeholder keeps the value's type (e.g. an integer seed)."""
    if isinstance(obj, dict): return {k: fill(v, values) for k, v in obj.items()}
    if isinstance(obj, list): return [fill(v, values) for v in obj]
    if isinstance(obj, str):
        for k, v in values.items():
            if obj == '{' + k + '}': return v
        for k, v in values.items():
            if isinstance(v, (str, int, float)): obj = obj.replace('{' + k + '}', str(v))
    return obj

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--tiles', default='DW4_map_tiles_for_AI')
    ap.add_argument('--out', default='DW4_map_tiles_generated')
    ap.add_argument('--config', default='scenario_batch.json')
    ap.add_argument('--write-config', action='store_true')
    ap.add_argument('--ids'); ap.add_argument('--section'); ap.add_argument('--limit', type=int)
    ap.add_argument('--redo', action='store_true'); ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--base-url', default='https://api.cloud.scenario.com/v1')
    ap.add_argument('--project-id', default=os.environ.get('SCENARIO_PROJECT_ID'))
    a = ap.parse_args()

    if a.write_config:
        if os.path.exists(a.config): sys.exit(f'{a.config} already exists; delete it first to start over')
        json.dump(DEFAULT_CONFIG, open(a.config, 'w'), indent=2)
        print(f'wrote {a.config}: put your model ID in body.modelId, then try --dry-run --ids S001'); return
    if not os.path.exists(a.config):
        sys.exit(f'no {a.config} yet: run with --write-config first')
    cfg = json.load(open(a.config))
    if 'PUT_YOUR' in json.dumps(cfg['body']): sys.exit(f'set body.modelId in {a.config} first')
    key, secret = os.environ.get('SCENARIO_API_KEY'), os.environ.get('SCENARIO_API_SECRET')
    if not key or not secret: sys.exit('set SCENARIO_API_KEY and SCENARIO_API_SECRET (Scenario: Settings > API Keys)')
    api = Api(a.base_url, key, secret, a.project_id)

    src = os.path.join(a.tiles, cfg.get('input', 'tiles_smooth'))
    if not os.path.isdir(src): sys.exit(f'tile folder not found: {src}')
    ids = sorted(f[:-4] for f in os.listdir(src) if f.endswith('.png'))
    if a.ids: want = set(a.ids.split(',')); ids = [i for i in ids if i in want]
    if a.section: ids = [i for i in ids if i[0] == a.section.upper()]
    out, raw = os.path.join(a.out, 'out'), os.path.join(a.out, 'raw')
    os.makedirs(out, exist_ok=True); os.makedirs(raw, exist_ok=True)
    if not a.redo and not a.dry_run: ids = [i for i in ids if not os.path.exists(os.path.join(out, i + '.png'))]
    if a.limit: ids = ids[:a.limit]
    print(f'{len(ids)} tiles to generate' + (' (dry run)' if a.dry_run else ''))
    G = int(cfg.get('gen_size', 1024))
    rs = Image.LANCZOS if cfg.get('upscale', 'lanczos') == 'lanczos' else Image.NEAREST
    lock = threading.Lock(); logf = open(os.path.join(a.out, 'log.jsonl'), 'a')
    done = [0]; cost = [0.0]

    def log(rec):
        with lock: logf.write(json.dumps(rec) + '\n'); logf.flush()

    def one(tid):
        img = Image.open(os.path.join(src, tid + '.png')).convert('RGB').resize((G, G), rs)
        prompt = cfg['prompt'].replace('{subject}', cfg.get('subjects', {}).get(tid[0], 'game map tile'))
        body = fill(cfg['body'], {'prompt': prompt, 'image': data_url(img), 'seed': cfg.get('seed', 12345), 'id': tid})
        try:
            r = api.call('POST', cfg['endpoint'], body, {'dryRun': 'true'} if a.dry_run else None)
            if a.dry_run:
                c = (r.get('creativeUnitsCost') or r.get('cost') or (r.get('billing') or {}).get('cost') or
                     (r.get('job') or {}).get('creativeUnitsCost'))
                with lock:
                    if isinstance(c, (int, float)): cost[0] += c
                print(f'  {tid}: dry run ok, cost {c}'); log({'id': tid, 'dry_run': r}); return
            job = r.get('job') or {}
            jid = job.get('jobId') or job.get('id')
            if not jid: raise RuntimeError(f'no job id in response: {json.dumps(r)[:300]}')
            t0 = time.time()
            while True:
                time.sleep(3)
                j = api.call('GET', f'/jobs/{jid}').get('job', {})
                st = j.get('status')
                if st in ('success', 'succeeded'): break
                if st in ('failure', 'failed', 'canceled', 'cancelled'):
                    raise RuntimeError(f'job {jid} {st}: {j.get("error") or j.get("statusMessage") or ""}')
                if time.time() - t0 > 900: raise RuntimeError(f'job {jid} still {st} after 15 min')
            assets = (j.get('metadata') or {}).get('assetIds') or []
            if not assets: raise RuntimeError(f'job {jid} finished without images')
            files = []
            for n, aid in enumerate(assets):
                url = api.call('GET', f'/assets/{aid}').get('asset', {}).get('url')
                im = Image.open(io.BytesIO(api.download(url))).convert('RGBA')
                p = os.path.join(raw, f'{tid}_{n + 1}.png'); im.save(p); files.append(p)
                if n == 0: im.resize((160, 160), Image.LANCZOS).save(os.path.join(out, tid + '.png'))
            log({'id': tid, 'job': jid, 'assets': assets, 'files': files, 'seconds': round(time.time() - t0)})
            with lock:
                done[0] += 1
                print(f'  {tid}: done ({done[0]}/{len(ids)})')
        except Exception as e:
            log({'id': tid, 'error': str(e)}); print(f'  {tid}: FAILED  {e}')

    with ThreadPoolExecutor(max(1, a.jobs)) as ex:
        list(ex.map(one, ids))
    if a.dry_run and cost[0]: print(f'estimated total: {cost[0]:g} credits for {len(ids)} tiles')
    elif not a.dry_run:
        print(f'finished {done[0]} of {len(ids)}; results in {out} (all versions in {raw}); '
              f'run again to retry any that failed')

if __name__ == '__main__':
    main()
