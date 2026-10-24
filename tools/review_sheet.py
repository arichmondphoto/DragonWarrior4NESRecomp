"""Side-by-side review pages: sheet sprite | game monster, with IDs and names."""
import json, sys, math
from PIL import Image, ImageDraw

def page(pairs, names, path, cols=6):
    CW, CH = 300, 170
    rows = math.ceil(len(pairs) / cols)
    im = Image.new('RGB', (cols * CW, rows * CH), (28, 28, 38)); d = ImageDraw.Draw(im)
    for k, (s, n) in enumerate(pairs):
        x, y = (k % cols) * CW, (k // cols) * CH
        d.rectangle([x + 2, y + 2, x + CW - 3, y + CH - 3], outline=(70, 70, 90))
        if s is not None:
            sp = Image.open(f'out/sheet/{s:03d}.png'); sp.thumbnail((140, 120))
            im.paste(sp, (x + 6 + (140 - sp.width) // 2, y + 26 + (120 - sp.height) // 2), sp)
        if n is not None:
            nm = Image.open(f'out/nes/{n:03d}.png'); f = min(140 / nm.width, 120 / nm.height, 4)
            nm = nm.resize((max(1, int(nm.width * f)), max(1, int(nm.height * f))), Image.NEAREST)
            im.paste(nm, (x + 152 + (140 - nm.width) // 2, y + 26 + (120 - nm.height) // 2), nm)
        label = f"sheet {s if s is not None else '-'}  ->  ID {n if n is not None else '-'}  {names.get(str(n), '') if n is not None else ''}"
        d.text((x + 6, y + 6), label, fill=(255, 220, 120))
    im.save(path)

if __name__ == '__main__':
    match = json.load(open(sys.argv[1])); names = json.load(open(sys.argv[2]))
    pairs = [(int(s), v['id']) for s, v in sorted(match.items(), key=lambda kv: int(kv[0]))]
    for p in range(0, len(pairs), 36):
        page(pairs[p:p + 36], names, f'out/review_{p // 36}.png')
    print('pages', (len(pairs) + 35) // 36)
