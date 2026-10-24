"""Start one of Dragon Warrior IV's fixed-formation battles from a save state.

Bank 24 function 1 ($A1AD) is the game's own fixed-battle setup: it reads an
8-byte record from the formation table (pointer at $A23F -> $A34C):
  bytes 0-3  monster IDs      -> $6E45-$6E48 ($FF = empty)
  bytes 4-7  counts (low nib) -> $6E49-$6E4C
  byte 7 bits 7-6             -> $6E44 = $C0 | (b7 >> 6)   ($C000 bit 5 is set)
then only picks battle music ($A123). This writes the same values into the
WRAM of an encounter save state taken just after the game filled the slots
(frame 8718 of the Chapter 1 route), so the battle that follows is drawn
exactly as the formation's real battle.

usage: force_formation.py IN.cycstate OUT.cycstate WRAM_OFFSET FORMATION
"""
import sys
ROM = open('rom/DragonWarriorIV.nes', 'rb').read()[16:]
def rd24(a): return ROM[24 * 0x4000 + (a - 0x8000)]
TABLE = rd24(0xA23F) | rd24(0xA240) << 8

def record(f):
    return [rd24(TABLE + 8 * f + k) for k in range(8)]

def patch(state, off, f):
    e = record(f); b = bytearray(state)
    b[off + 0xE45: off + 0xE49] = bytes(e[:4])
    b[off + 0xE49: off + 0xE4D] = bytes(x & 0x0F for x in e[4:])
    b[off + 0xE44] = 0xC0 | (e[7] >> 6)
    return bytes(b)

if __name__ == '__main__':
    src, dst, off, f = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    open(dst, 'wb').write(patch(open(src, 'rb').read(), off, f))
