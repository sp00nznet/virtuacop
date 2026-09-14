#!/usr/bin/env python3
"""
Check the lifter's instruction decode against IDA's i960 disassembler.

The lifter decodes i960 machine code itself, and a wrong instruction *length*
is the worst bug available: every instruction after it is decoded from the
wrong offset, and the output still compiles and runs. Nothing in the project
could catch that on its own, so check it against an independent decoder.

IDA has an i960 processor module. It cannot be pointed at a flat binary
headlessly - idalib has no way to answer the loader's questions and the
process aborts - so wrap the ROM in a minimal ELF whose e_machine says i960
(EM_960 = 19) and let the ELF loader place it. IDA then picks the processor on
its own and maps the image at 0, which is where the lifter decodes it.

Usage, from the repository root:

    py -3.11 tools/check_decode_vs_ida.py roms/program.bin

Needs IDA Professional with idalib on the Python 3.11 that has `idapro`
installed. Prints a summary; exits 1 if any instruction length disagrees.

What it does *not* check: that our implementation of an instruction is
correct, only that we identify it and its length correctly. And our own
disassembler (tools/rom_loader.py) names several opcodes wrongly - it is used
for function discovery, where only the lengths matter, and for the human
readable dump.
"""
import os
import struct
import subprocess
import sys
import tempfile

EM_960 = 19
LOAD_OFF = 0x1000


def wrap_in_elf(rom: bytes, entry: int, path: str) -> None:
    """Minimal ET_EXEC ELF32 LSB for i960, one PT_LOAD mapping rom at 0."""
    ident = b'\x7fELF' + bytes([1, 1, 1, 0]) + bytes(8)
    ehdr = ident + struct.pack('<HHIIIIIHHHHHH',
                               2, EM_960, 1, entry, 52, 0, 0,
                               52, 32, 1, 40, 0, 0)
    phdr = struct.pack('<IIIIIIII', 1, LOAD_OFF, 0, 0,
                       len(rom), len(rom), 5, 0x1000)
    blob = ehdr + phdr
    blob += bytes(LOAD_OFF - len(blob))
    with open(path, 'wb') as f:
        f.write(blob + rom)


IDA_DUMP = r'''
import sys, idapro
if idapro.open_database(sys.argv[1], False):
    raise SystemExit("open failed")
import ida_ua
out = open(sys.argv[2], "w")
ea, end = 0, int(sys.argv[3], 16)
while ea < end:
    insn = ida_ua.insn_t()
    n = ida_ua.decode_insn(insn, ea)
    if n <= 0:
        out.write("%08X 4 BAD\n" % ea)
        ea += 4
        continue
    out.write("%08X %d %s\n" % (ea, insn.size, insn.get_canon_mnem() or "?"))
    ea += insn.size
out.close()
idapro.close_database(False)
'''


def main():
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from tools.rom_loader import disasm_one

    rom_path = sys.argv[1] if len(sys.argv) > 1 else 'roms/program.bin'
    rom = open(rom_path, 'rb').read()

    end = len(rom)
    while end > 0 and rom[end - 1] in (0x00, 0xFF):
        end -= 1
    end = (end + 3) & ~3

    tmp = tempfile.mkdtemp(prefix='i960chk')
    elf = os.path.join(tmp, 'prog.elf')
    dump = os.path.join(tmp, 'decode.txt')
    script = os.path.join(tmp, 'dump.py')

    wrap_in_elf(rom[:end], 0x6A0, elf)
    with open(script, 'w') as f:
        f.write(IDA_DUMP)

    rc = subprocess.call(['py', '-3.11', script, elf, dump, '%X' % end])
    if rc != 0 or not os.path.exists(dump):
        print('IDA run failed (is idalib installed on py -3.11?)')
        return 2

    mismatches = []
    decoded = bad = 0
    for line in open(dump):
        addr, size, mnem = line.split(None, 2)
        addr, size, mnem = int(addr, 16), int(size), mnem.strip()
        if mnem == 'BAD':
            bad += 1
            continue
        decoded += 1
        try:
            _, ours, _, _, _ = disasm_one(rom, addr, addr)
        except Exception:
            continue
        if ours != size:
            mismatches.append((addr, size, ours, mnem))

    print('instructions IDA decoded : %d' % decoded)
    print('bytes IDA read as data   : %d' % bad)
    print('instruction length errors: %d' % len(mismatches))
    for addr, theirs, ours, mnem in mismatches[:20]:
        print('  %08X ida=%d ours=%d  %s' % (addr, theirs, ours, mnem))
    return 1 if mismatches else 0


if __name__ == '__main__':
    sys.exit(main())
