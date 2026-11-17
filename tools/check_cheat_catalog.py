#!/usr/bin/env python3
"""Check cheats/catalog.txt (the launcher's built-in Game Genie codes) against the ROM.

    tools/check_cheat_catalog.py [rom/DragonWarriorIV.nes] [cheats/catalog.txt]

For every entry: each code decodes, and an 8-letter code's compare value is the
ROM's byte at its address in some bank (else the code does nothing). Codes on a
character's inventory slot (the `slot` lines) must give exactly the items the
entry's name lists, by the game's item names (the `item` lines, read from the
game's own item menu). Slots must be FF (empty) in the bank that holds the
starting inventories. Exit status 1 on any problem.
"""
import re
import sys

L = "APZLGITYEOXUKSVN"
INV_BANK = 18          # PRG bank (16 KiB) with the eight 8-byte starting inventories at $9191


def decode(code):
    n = [L.index(c) for c in code]
    a = (0x8000 | ((n[3] & 7) << 12) | ((n[5] & 7) << 8) | ((n[4] & 8) << 8) |
         ((n[2] & 7) << 4) | ((n[1] & 8) << 4) | (n[4] & 7) | (n[3] & 8))
    last = 7 if len(code) == 8 else 5
    v = ((n[1] & 7) << 4) | ((n[0] & 8) << 4) | (n[0] & 7) | (n[last] & 8)
    cmp = (((n[7] & 7) << 4) | ((n[6] & 8) << 4) | (n[6] & 7) | (n[5] & 8)) if len(code) == 8 else None
    return a, v, cmp


def main():
    rom_path = sys.argv[1] if len(sys.argv) > 1 else "rom/DragonWarriorIV.nes"
    cat_path = sys.argv[2] if len(sys.argv) > 2 else "cheats/catalog.txt"
    rom = open(rom_path, "rb").read()
    prg = rom[16:16 + rom[4] * 16384]
    entries, slots, items = [], [], {}
    for line in open(cat_path, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.strip() or line.startswith("#") or line.startswith("["):
            continue
        if line.startswith("slot "):
            _, a, b, name = line.split(None, 3)
            slots.append((int(a, 16), int(b, 16), name))
        elif line.startswith("item "):
            _, v, name = line.split(None, 2)
            items[int(v, 16)] = name
        else:
            codes, name = line.split(None, 1)
            entries.append((codes.split("+"), name))
    problems = 0

    def bad(msg):
        nonlocal problems
        problems += 1
        print("PROBLEM:", msg)

    slot_of = {}
    for a, b, name in slots:
        for i, addr in enumerate((a, b)):
            slot_of[addr] = (name, i)
            if prg[INV_BANK * 0x4000 + (addr & 0x3FFF)] != 0xFF:
                bad("slot $%04X (%s) is not empty in bank %d" % (addr, name, INV_BANK))
    for codes, name in entries:
        got = []
        for code in codes:
            if not re.fullmatch("[%s]{6}|[%s]{8}" % (L, L), code):
                bad("%s (%s): not a Game Genie code" % (code, name))
                continue
            a, v, cmp = decode(code)
            if cmp is not None and not any(prg[b * 0x4000 + (a & 0x3FFF)] == cmp for b in range(len(prg) // 0x4000)):
                bad("%s (%s): the ROM never holds %02X at $%04X, so it does nothing" % (code, name, cmp, a))
            if a in slot_of:
                if cmp != 0xFF:
                    bad("%s (%s): an inventory code should compare with FF" % (code, name))
                if v not in items:
                    bad("%s (%s): item value %02X has no name in the game" % (code, name, v))
                got.append(items.get(v, "?"))
        for item in got:
            if item.lower() not in name.lower():
                bad("%s: the codes give %s" % (name, ", ".join(got)))
                break
    print("%d entries, %d slots, %d items: %s" % (len(entries), len(slots), len(items),
                                                 "ok" if not problems else "%d problem(s)" % problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
