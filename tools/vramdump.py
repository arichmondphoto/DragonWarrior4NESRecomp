"""Parse a nes_game --mem-out dump: CHR RAM tiles, palette RAM and the frame's palette indices."""
def load(path):
    regs = {}
    for ln in open(path):
        q = ln.split()
        if len(q) < 3 or not q[1].endswith(':'): continue
        regs.setdefault(q[0], []).append((q[1][:-1], q[2:]))
    out = {}
    for k in ('ram', 'ciram', 'oam', 'palette', 'chr_ram', 'wram'):
        if k in regs:
            b = bytearray()
            for _, vals in sorted(regs[k], key=lambda r: int(r[0], 16)): b += bytes(int(v, 16) for v in vals)
            out[k] = bytes(b)
    if 'frame' in regs:
        out['frame'] = [[int(v, 16) for v in vals] for _, vals in sorted(regs['frame'], key=lambda r: int(r[0]))]
    return out

def tile_pixels(chr_bytes, t):
    """8x8 list of 2-bit values for CHR tile t."""
    d = chr_bytes[16*t:16*t+16]
    return [[((d[y] >> (7-x)) & 1) | (((d[y+8] >> (7-x)) & 1) << 1) for x in range(8)] for y in range(8)]
