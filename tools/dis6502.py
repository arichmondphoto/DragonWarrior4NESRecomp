"""Minimal 6502 disassembler for the DW4 ROM (16 KiB banks, file bank N at $8000,
fixed bank 31 at $C000). usage: dis6502.py BANK ADDR [COUNT]"""
import sys
ROM = open('rom/DragonWarriorIV.nes', 'rb').read()[16:]
M = {}
def op(code, name, mode): M[code] = (name, mode)
for c,n in [(0x00,'BRK'),(0x08,'PHP'),(0x18,'CLC'),(0x28,'PLP'),(0x38,'SEC'),(0x40,'RTI'),(0x48,'PHA'),(0x58,'CLI'),(0x60,'RTS'),(0x68,'PLA'),(0x78,'SEI'),(0x88,'DEY'),(0x8A,'TXA'),(0x98,'TYA'),(0x9A,'TXS'),(0xA8,'TAY'),(0xAA,'TAX'),(0xB8,'CLV'),(0xBA,'TSX'),(0xC8,'INY'),(0xCA,'DEX'),(0xD8,'CLD'),(0xE8,'INX'),(0xEA,'NOP'),(0xF8,'SED'),(0x0A,'ASL A'),(0x2A,'ROL A'),(0x4A,'LSR A'),(0x6A,'ROR A')]: op(c,n,'imp')
groups = {'ORA':0x00,'AND':0x20,'EOR':0x40,'ADC':0x60,'STA':0x80,'LDA':0xA0,'CMP':0xC0,'SBC':0xE0}
for n,b in groups.items():
    for off,mode in [(1,'izx'),(5,'zp'),(9,'imm'),(0xD,'abs'),(0x11,'izy'),(0x15,'zpx'),(0x19,'aby'),(0x1D,'abx')]:
        if n=='STA' and mode=='imm': continue
        op(b+off,n,mode)
for n,b in {'ASL':0x00,'ROL':0x20,'LSR':0x40,'ROR':0x60,'DEC':0xC0,'INC':0xE0}.items():
    for off,mode in [(6,'zp'),(0xE,'abs'),(0x16,'zpx'),(0x1E,'abx')]: op(b+off,n,mode)
for c,n,mo in [(0x86,'STX','zp'),(0x8E,'STX','abs'),(0x96,'STX','zpy'),(0x84,'STY','zp'),(0x8C,'STY','abs'),(0x94,'STY','zpx'),
               (0xA2,'LDX','imm'),(0xA6,'LDX','zp'),(0xAE,'LDX','abs'),(0xB6,'LDX','zpy'),(0xBE,'LDX','aby'),
               (0xA0,'LDY','imm'),(0xA4,'LDY','zp'),(0xAC,'LDY','abs'),(0xB4,'LDY','zpx'),(0xBC,'LDY','abx'),
               (0xE0,'CPX','imm'),(0xE4,'CPX','zp'),(0xEC,'CPX','abs'),(0xC0,'CPY','imm'),(0xC4,'CPY','zp'),(0xCC,'CPY','abs'),
               (0x24,'BIT','zp'),(0x2C,'BIT','abs'),(0x20,'JSR','abs'),(0x4C,'JMP','abs'),(0x6C,'JMP','ind')]: op(c,n,mo)
for c,n in [(0x10,'BPL'),(0x30,'BMI'),(0x50,'BVC'),(0x70,'BVS'),(0x90,'BCC'),(0xB0,'BCS'),(0xD0,'BNE'),(0xF0,'BEQ')]: op(c,n,'rel')
SIZE = {'imp':1,'imm':2,'zp':2,'zpx':2,'zpy':2,'izx':2,'izy':2,'rel':2,'abs':3,'abx':3,'aby':3,'ind':3}
def rd(bank, a): return ROM[(31 if a >= 0xC000 else bank) * 0x4000 + (a & 0x3FFF)]
def dis(bank, a, n):
    out = []
    for _ in range(n):
        c = rd(bank, a)
        if c not in M: out.append(f'{a:04X}  .db ${c:02X}'); a += 1; continue
        name, mode = M[c]; sz = SIZE[mode]
        b = [rd(bank, a + i) for i in range(1, sz)]
        w = b[0] | (b[1] << 8) if sz == 3 else None
        arg = {'imp':'','imm':f'#${b[0]:02X}' if sz>1 else '','zp':f'${b[0]:02X}' if sz>1 else '','zpx':f'${b[0]:02X},X' if sz>1 else '',
               'zpy':f'${b[0]:02X},Y' if sz>1 else '','izx':f'(${b[0]:02X},X)' if sz>1 else '','izy':f'(${b[0]:02X}),Y' if sz>1 else '',
               'rel':f'${(a + 2 + ((b[0] ^ 0x80) - 0x80)) & 0xFFFF:04X}' if sz>1 else '',
               'abs':f'${w:04X}' if w is not None else '','abx':f'${w:04X},X' if w is not None else '',
               'aby':f'${w:04X},Y' if w is not None else '','ind':f'(${w:04X})' if w is not None else ''}[mode]
        out.append(f'{a:04X}  {" ".join(f"{x:02X}" for x in [c]+b):9s} {name} {arg}'); a += sz
    return out
if __name__ == '__main__':
    print('\n'.join(dis(int(sys.argv[1]), int(sys.argv[2], 16), int(sys.argv[3]) if len(sys.argv) > 3 else 30)))
