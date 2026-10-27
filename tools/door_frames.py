"""Add the castle doors' in-between animation frames to the map tiles.

When a big castle door opens, the game draws three in-between frames
straight into the nametable (tools/capture_extras.py doors.json), so they
are not map tiles and the field capture never lists them. This turns each
frame into four 16x16 "map tiles" (TL TR BL BR), drawn in every palette the
closed door is drawn with (other castles, night), and cuts their art from
the owner's generated sheet hd/field/doors/DOOR1.png (tools/export_gaps.py
layout: five 256 px cells, closed / three frames / open). The rows are added
to a copy of field_tiles.json and the art goes beside the other tiles, so
tools/make_field_hdpack.py keys them like any map tile (night, fades).
Art IDs DR01-DR12 are listed in hd/field/ids.json.

usage: door_frames.py FIELD_TILES DOORS_JSON ART_DIR OUT_FIELD_TILES
"""
import hashlib, json, os, sys
from PIL import Image
sys.path.insert(0, os.path.dirname(__file__))
from export_gaps import door_origin, DOOR_CELL

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    ft, dj, art, out = sys.argv[1:5]
    rows = json.load(open(ft)); doors = json.load(open(dj))
    sheet_p = os.path.join(HERE, 'hd', 'field', 'doors', 'DOOR1.png')
    ids = json.load(open(os.path.join(HERE, 'hd', 'field', 'ids.json')))['ids']
    by_fp = {v[0]: k for k, v in ids.items()}
    fp = lambda c: hashlib.sha1(bytes.fromhex(c)).hexdigest()[:16]
    # every palette each closed-door metatile is drawn with
    closed_rows = [[r for r in rows if r['chr'] == c] for c in doors['closed']]
    sheet = Image.open(sheet_p).convert('RGB').resize((1536, 1024), Image.LANCZOS) if os.path.exists(sheet_p) else None
    added = 0
    for f, frame in enumerate(doors['frames']):
        x0, y0 = door_origin(f + 1)
        for k, c in enumerate(frame):
            aid = by_fp.get(fp(c))
            if aid is None: continue                         # not registered in ids.json
            for n, cr in enumerate(closed_rows[k]):
                rows.append({'id': f'{aid}{chr(97 + n)}', 'item': aid, 'section': 'Castle door animation',
                             'used_in': cr['used_in'], 'nes_colors': cr['nes_colors'], 'chr': c})
            if sheet is not None:
                q = DOOR_CELL // 2
                cut = sheet.crop((x0 + (k % 2) * q, y0 + (k // 2) * q, x0 + (k % 2) * q + q, y0 + (k // 2) * q + q))
                cut.resize((160, 160), Image.LANCZOS).save(os.path.join(art, aid + '.png'))
            added += 1
    json.dump(rows, open(out, 'w'), indent=0)
    print(f'  castle doors: {added} animation tiles in {sum(len(c) for c in closed_rows)} palettes'
          + ('' if sheet is not None else ' (no art yet)'))

if __name__ == '__main__':
    main()
