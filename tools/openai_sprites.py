#!/usr/bin/env python3
"""Batch-redraw the Dragon Warrior IV character sheets with OpenAI's image API.

Works on the DW4_characters_for_ChatGPT folder (tools/export_chatgpt_sprites.py).
For each character it sends one image edit request:
    image 1  inputs/<ID>.png          the 8-bit sheet (1536x1024, 4x2 grid)
    image 2  style_reference.png      your monster art
    image 3  silhouettes/<ID>.png     (only with --silhouette)
    prompt   PROJECT_INSTRUCTIONS.txt + prompts/<ID>.txt
with the same model, size, quality and settings every time, and saves:
    results/<ID>.png        the first image (what you send back / what gets checked)
    raw/<ID>_<n>.png        every image returned (with --variants N)
    log.jsonl               one line per request: tokens used, cost, errors
It skips characters that already have a result (so a stopped run can simply
be started again), retries rate limits and server errors, runs a few
requests at once, and stops before going over --budget.

Needs only Python 3.8+ (no packages). Get an API key at
platform.openai.com > API keys, then in Terminal:

    export OPENAI_API_KEY=sk-...
    cd DW4_characters_for_ChatGPT
    python3 openai_sprites.py --dry-run                       # what it would do, estimated cost
    python3 openai_sprites.py --ids C007,C017,C042            # the pilot
    python3 openai_sprites.py --budget 25                     # everything else, stop at $25
    python3 openai_sprites.py --ids-from redo.txt --redo      # redo the ones the checker flagged

Options
  --model M         default gpt-image-2.5-sunburst (OpenAI's model for precise
                    edits); gpt-image-2 is the cheaper previous generation
  --quality Q       low | medium | high (default) | xhigh | max (2.5 models only)
  --variants N      images per character (1-4, default 1; each one is billed)
  --silhouette      also send the silhouette image (if outlines drift)
  --ids A,B / --ids-from FILE   only these characters (FILE: one ID per line or
                    the checker's report.csv: rows marked redo)
  --optional        include the optional effects (shadows, sparkles)
  --redo            regenerate even if results/<ID>.png exists
  --limit N         stop after N characters
  --jobs N          requests at once (default 3)
  --budget USD      stop starting new requests once the logged cost reaches this
  --dry-run         list the work and the estimated cost; sends nothing
"""
import argparse, base64, csv, json, os, random, sys, threading, time, urllib.error, urllib.request, uuid
from concurrent.futures import ThreadPoolExecutor

API = os.environ.get('OPENAI_BASE_URL', 'https://api.openai.com/v1').rstrip('/') + '/images/edits'
SIZE = '1536x1024'

# USD per 1M tokens (OpenAI's published rates, October 2026; check
# platform.openai.com/docs/pricing). Used to report cost from each
# response's token counts.
RATES = {'text_in': 5.00, 'image_in': 8.00, 'image_out': 30.00}
# Output image tokens per request at 1536x1024, for the --dry-run estimate.
# 'high' is measured (pilot, gpt-image-2.5-sunburst: 1372 out, 1280 per input
# image, ~$0.065 per character); the others are guesses. The log has the real numbers.
OUT_TOKENS = {'low': 300, 'medium': 700, 'high': 1372, 'xhigh': 2600, 'max': 4000}
IN_TOKENS_PER_IMAGE = 1280

HERE = os.path.dirname(os.path.abspath(__file__))

def multipart(fields, files):
    """fields: [(name, value)], files: [(name, filename, bytes)] -> (body, content type)."""
    b = '----dw4' + uuid.uuid4().hex
    out = []
    for k, v in fields:
        out += [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n'.encode(), str(v).encode(), b'\r\n']
    for k, fn, data in files:
        out += [f'--{b}\r\nContent-Disposition: form-data; name="{k}"; filename="{fn}"\r\n'
                f'Content-Type: image/png\r\n\r\n'.encode(), data, b'\r\n']
    out.append(f'--{b}--\r\n'.encode())
    return b''.join(out), f'multipart/form-data; boundary={b}'

def cost_of(usage):
    if not usage: return None
    det = usage.get('input_tokens_details') or {}
    img_in = det.get('image_tokens', 0); txt_in = det.get('text_tokens', usage.get('input_tokens', 0) - img_in)
    out = usage.get('output_tokens', 0)
    return (txt_in * RATES['text_in'] + img_in * RATES['image_in'] + out * RATES['image_out']) / 1e6

def wanted_ids(a, folder):
    ids = []
    for sub in ([''] + (['optional/'] if a.optional else [])):
        d = os.path.join(folder, sub + 'inputs')
        if os.path.isdir(d): ids += [(f[:-4], sub) for f in sorted(os.listdir(d)) if f.endswith('.png')]
    pick = None
    if a.ids: pick = {x.strip().upper() for x in a.ids.split(',') if x.strip()}
    if a.ids_from:
        txt = open(a.ids_from).read().splitlines()
        if txt and txt[0].startswith('id,'):
            pick = {r['id'] for r in csv.DictReader(txt) if r.get('verdict') == 'redo'}
        else:
            pick = {x.strip().upper() for x in txt if x.strip()}
    if pick is not None:
        allids = {i for i, s in ids}
        if a.optional is False:   # asked-for optional IDs are fine too
            d = os.path.join(folder, 'optional/inputs')
            if os.path.isdir(d): ids += [(f[:-4], 'optional/') for f in sorted(os.listdir(d)) if f.endswith('.png') and f[:-4] not in allids]
        ids = [(i, s) for i, s in ids if i in pick]
        missing = pick - {i for i, s in ids}
        if missing: print('not found (skipped):', ', '.join(sorted(missing)))
    return ids

def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--folder', default=HERE, help='the DW4_characters_for_ChatGPT folder (default: this script\'s folder)')
    ap.add_argument('--out', help='where results go (default: <folder>/generated)')
    ap.add_argument('--model', default='gpt-image-2.5-sunburst')
    ap.add_argument('--quality', default='high')
    ap.add_argument('--variants', type=int, default=1)
    ap.add_argument('--silhouette', action='store_true')
    ap.add_argument('--ids'); ap.add_argument('--ids-from')
    ap.add_argument('--optional', action='store_true')
    ap.add_argument('--redo', action='store_true')
    ap.add_argument('--limit', type=int)
    ap.add_argument('--jobs', type=int, default=3)
    ap.add_argument('--budget', type=float)
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    folder = a.folder
    if not os.path.isdir(os.path.join(folder, 'inputs')):
        sys.exit(f'no inputs/ folder in {folder}: run this from the DW4_characters_for_ChatGPT folder (or pass --folder)')
    out = a.out or os.path.join(folder, 'generated')
    res_dir, raw_dir = os.path.join(out, 'results'), os.path.join(out, 'raw')
    os.makedirs(res_dir, exist_ok=True); os.makedirs(raw_dir, exist_ok=True)
    logp = os.path.join(out, 'log.jsonl')

    spent = 0.0
    if os.path.exists(logp):
        for line in open(logp):
            try: spent += json.loads(line).get('cost_usd') or 0
            except ValueError: pass

    jobs = wanted_ids(a, folder)
    if not a.redo: jobs = [(i, s) for i, s in jobs if not os.path.exists(os.path.join(res_dir, i + '.png'))]
    if a.limit: jobs = jobs[:a.limit]
    nimg = 3 if a.silhouette else 2
    est_each = (a.variants * OUT_TOKENS.get(a.quality, 5500) * RATES['image_out'] +
                nimg * IN_TOKENS_PER_IMAGE * RATES['image_in'] + 600 * RATES['text_in']) / 1e6
    print(f'{len(jobs)} characters, model {a.model}, quality {a.quality}, {a.variants} image(s) each'
          f'{", with silhouettes" if a.silhouette else ""}')
    print(f'estimated ~${est_each:.2f} each, ~${est_each * len(jobs):.2f} in all '
          f'(rough; the log shows the real cost). Logged so far: ${spent:.2f}')
    if a.dry_run:
        print('dry run:', ' '.join(i for i, s in jobs)); return
    if not jobs: print('nothing to do'); return
    key = os.environ.get('OPENAI_API_KEY')
    if not key: sys.exit('set OPENAI_API_KEY first (export OPENAI_API_KEY=sk-...)')

    instructions = open(os.path.join(folder, 'PROJECT_INSTRUCTIONS.txt')).read().strip()
    style = open(os.path.join(folder, 'style_reference.png'), 'rb').read()
    lock = threading.Lock(); state = {'spent': spent, 'done': 0, 'stop': False}

    def log(rec):
        with lock:
            with open(logp, 'a') as f: f.write(json.dumps(rec) + '\n')

    def one(job):
        cid, sub = job
        with lock:
            if state['stop'] or (a.budget is not None and state['spent'] >= a.budget):
                state['stop'] = True; return
        pname = cid + ('_with_silhouette' if a.silhouette else '') + '.txt'
        prompt = instructions + '\n\n' + open(os.path.join(folder, sub + 'prompts', pname)).read().strip()
        files = [('image[]', cid + '.png', open(os.path.join(folder, sub + 'inputs', cid + '.png'), 'rb').read()),
                 ('image[]', 'style_reference.png', style)]
        if a.silhouette:
            files.append(('image[]', cid + '_silhouette.png', open(os.path.join(folder, sub + 'silhouettes', cid + '.png'), 'rb').read()))
        fields = [('model', a.model), ('prompt', prompt), ('size', SIZE), ('quality', a.quality),
                  ('background', 'transparent'), ('output_format', 'png'), ('n', a.variants)]
        body, ctype = multipart(fields, files)
        t0 = time.time()
        for attempt in range(6):
            req = urllib.request.Request(API, data=body, method='POST',
                                         headers={'Authorization': 'Bearer ' + key, 'Content-Type': ctype})
            try:
                with urllib.request.urlopen(req, timeout=600) as r: resp = json.loads(r.read())
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors='replace')[:600]
                if e.code in (429, 500, 502, 503, 504) and attempt < 5:
                    time.sleep(min(90, 5 * 2 ** attempt) + random.random() * 3); continue
                print(f'  {cid}: FAILED HTTP {e.code}: {msg}'); log({'id': cid, 'error': f'HTTP {e.code}', 'detail': msg})
                if e.code in (401, 403): state['stop'] = True
                return
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 5: time.sleep(5 * 2 ** attempt); continue
                print(f'  {cid}: FAILED {e}'); log({'id': cid, 'error': str(e)}); return
        imgs = [base64.b64decode(d['b64_json']) for d in resp.get('data', []) if d.get('b64_json')]
        if not imgs:
            print(f'  {cid}: no image in the response'); log({'id': cid, 'error': 'no image', 'detail': str(resp)[:600]}); return
        for n, data in enumerate(imgs, 1):
            open(os.path.join(raw_dir, f'{cid}_{n}.png'), 'wb').write(data)
        open(os.path.join(res_dir, cid + '.png'), 'wb').write(imgs[0])
        c = cost_of(resp.get('usage'))
        with lock:
            state['spent'] += c or est_each; state['done'] += 1
            print(f'  {cid}: done ({state["done"]}/{len(jobs)}) ' +
                  (f'${c:.3f}' if c is not None else '(no usage reported)') + f', total ${state["spent"]:.2f}')
        log({'id': cid, 'model': a.model, 'quality': a.quality, 'variants': len(imgs), 'silhouette': a.silhouette,
             'usage': resp.get('usage'), 'cost_usd': c, 'seconds': round(time.time() - t0)})

    with ThreadPoolExecutor(max(1, a.jobs)) as ex:
        list(ex.map(one, jobs))
    if state['stop'] and a.budget is not None and state['spent'] >= a.budget:
        print(f'stopped at the ${a.budget:.2f} budget; run again with a higher --budget to continue')
    print(f'finished {state["done"]} of {len(jobs)}; results in {res_dir}; total logged ${state["spent"]:.2f}')

if __name__ == '__main__':
    main()
