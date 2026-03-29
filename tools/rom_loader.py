#!/usr/bin/env python3
"""
Virtua Cop ROM Loader & i960 Disassembler

Extracts ROM files from MAME ZIP, interleaves them into flat binaries,
and performs initial i960 disassembly to discover functions.

Usage:
    python rom_loader.py <vcop.zip> <output_dir>
"""

import os
import sys
import struct
import zipfile
from pathlib import Path


# ============================================================================
# ROM Layout for Virtua Cop (Model 2 Original)
# ============================================================================

# Program ROM: i960 code, 2MB total
# ROM_LOAD32_WORD interleaves two 16-bit halves
PROGRAM_ROM = {
    'size': 0x200000,  # 2MB
    'parts': [
        # (filename_revB, filename_revA, offset, file_size, word_offset)
        # word_offset: 0 = low 16 bits, 2 = high 16 bits
        ('epr-17166b.12', 'epr-17166a.12', 0x000000, 0x020000, 0),
        ('epr-17167b.13', 'epr-17167a.13', 0x000000, 0x020000, 2),
        ('epr-17160a.14', 'epr-17160a.14', 0x040000, 0x020000, 0),
        ('epr-17161a.15', 'epr-17161a.15', 0x040000, 0x020000, 2),
    ]
}

# Data ROM: game data, up to 32MB
DATA_ROM = {
    'size': 0x2000000,  # 32MB
    'parts': [
        ('mpr-17164.10', 0x000000, 0x200000, 0),
        ('mpr-17165.11', 0x000000, 0x200000, 2),
        ('mpr-17162.8',  0x400000, 0x200000, 0),
        ('mpr-17163.9',  0x400000, 0x200000, 2),
        ('epr-17168a.6', 0x800000, 0x080000, 0),
        ('epr-17169a.7', 0x800000, 0x080000, 2),
    ]
}

# Polygon model ROM
POLYGON_ROM = {
    'size': 0x1000000,  # 16MB
    'parts': [
        ('mpr-17159.16', 0x000000, 0x200000, 0),
        ('mpr-17156.20', 0x000000, 0x200000, 2),
    ]
}

# Texture ROM
TEXTURE_ROM = {
    'size': 0x1000000,  # 16MB
    'parts': [
        ('mpr-17158.25', 0x000000, 0x200000, 0),
        ('mpr-17157.24', 0x000000, 0x200000, 2),
    ]
}

# Sound CPU ROM (68000, big-endian 16-bit word-swapped)
SOUND_ROM = {
    'size': 0xC0000,
    'parts': [
        ('epr-17170.7', 0x000000, 0x020000),
        ('epr-17171.8', 0x020000, 0x020000),
    ]
}

# MultiPCM sample ROMs
SAMPLE_ROM_1 = {
    'size': 0x400000,
    'parts': [
        ('mpr-17172.32', 0x000000, 0x100000),
        ('mpr-17173.33', 0x200000, 0x100000),
    ]
}

SAMPLE_ROM_2 = {
    'size': 0x400000,
    'parts': [
        ('mpr-17174.4', 0x000000, 0x200000),
        ('mpr-17175.5', 0x200000, 0x200000),
    ]
}


def load_file_from_zip(zf, name):
    """Load a file from a ZIP, case-insensitive."""
    for info in zf.infolist():
        if info.filename.lower() == name.lower():
            return zf.read(info.filename)
    return None


def interleave_32bit(output, parts, zf):
    """
    Interleave ROM_LOAD32_WORD parts into a flat buffer.
    Each part provides 16-bit words at alternating positions in 32-bit space.
    """
    for part in parts:
        if len(part) == 5:
            # Program ROM: (name_b, name_a, offset, size, word_off)
            name = part[0]
            offset = part[2]
            file_size = part[3]
            word_offset = part[4]
        else:
            # Data/polygon/texture ROM: (name, offset, size, word_off)
            name = part[0]
            offset = part[1]
            file_size = part[2]
            word_offset = part[3]

        data = load_file_from_zip(zf, name)
        if data is None:
            print(f"  WARNING: {name} not found in ZIP")
            continue

        print(f"  {name}: {len(data)} bytes -> offset 0x{offset:08X} word_offset {word_offset}")

        # Interleave: each 2 bytes from file go into the appropriate 16-bit half
        for i in range(0, min(len(data), file_size), 2):
            dst = offset + (i * 2) + word_offset
            if dst + 1 < len(output):
                output[dst] = data[i]
                output[dst + 1] = data[i + 1]


def load_sequential(output, parts, zf, word_swap=False):
    """Load ROMs sequentially (no interleaving)."""
    for part in parts:
        name = part[0]
        offset = part[1]
        size = part[2]

        data = load_file_from_zip(zf, name)
        if data is None:
            print(f"  WARNING: {name} not found in ZIP")
            continue

        actual_size = min(len(data), size)
        print(f"  {name}: {len(data)} bytes -> offset 0x{offset:08X}")

        if word_swap:
            # ROM_LOAD16_WORD_SWAP: swap every 2 bytes (big-endian to little-endian)
            for i in range(0, actual_size, 2):
                dst = offset + i
                if dst + 1 < len(output):
                    output[dst] = data[i + 1] if i + 1 < len(data) else 0
                    output[dst + 1] = data[i]
        else:
            for i in range(actual_size):
                if offset + i < len(output):
                    output[offset + i] = data[i]


def extract_roms(zip_path, output_dir):
    """Extract and interleave all ROM regions from a MAME ZIP."""
    os.makedirs(output_dir, exist_ok=True)

    with zipfile.ZipFile(zip_path) as zf:
        print(f"Extracting ROMs from {zip_path}")
        print(f"Output: {output_dir}")
        print()

        # Program ROM
        print("=== Program ROM (i960, 2MB) ===")
        prog = bytearray(PROGRAM_ROM['size'])
        interleave_32bit(prog, PROGRAM_ROM['parts'], zf)
        prog_path = os.path.join(output_dir, 'program.bin')
        with open(prog_path, 'wb') as f:
            f.write(prog)
        print(f"  -> {prog_path} ({len(prog)} bytes)")
        print()

        # Data ROM
        print("=== Data ROM (32MB) ===")
        data = bytearray(DATA_ROM['size'])
        interleave_32bit(data, DATA_ROM['parts'], zf)
        data_path = os.path.join(output_dir, 'data.bin')
        with open(data_path, 'wb') as f:
            f.write(data)
        print(f"  -> {data_path} ({len(data)} bytes)")
        print()

        # Polygon ROM
        print("=== Polygon ROM (16MB) ===")
        poly = bytearray(POLYGON_ROM['size'])
        interleave_32bit(poly, POLYGON_ROM['parts'], zf)
        poly_path = os.path.join(output_dir, 'polygons.bin')
        with open(poly_path, 'wb') as f:
            f.write(poly)
        print(f"  -> {poly_path} ({len(poly)} bytes)")
        print()

        # Texture ROM
        print("=== Texture ROM (16MB) ===")
        tex = bytearray(TEXTURE_ROM['size'])
        interleave_32bit(tex, TEXTURE_ROM['parts'], zf)
        tex_path = os.path.join(output_dir, 'textures.bin')
        with open(tex_path, 'wb') as f:
            f.write(tex)
        print(f"  -> {tex_path} ({len(tex)} bytes)")
        print()

        # Sound ROM (68000, word-swapped)
        print("=== Sound ROM (68000, 768KB) ===")
        snd = bytearray(SOUND_ROM['size'])
        load_sequential(snd, SOUND_ROM['parts'], zf, word_swap=True)
        snd_path = os.path.join(output_dir, 'sound_program.bin')
        with open(snd_path, 'wb') as f:
            f.write(snd)
        print(f"  -> {snd_path} ({len(snd)} bytes)")
        print()

        # Sample ROMs
        print("=== Sample ROM 1 (MultiPCM, 4MB) ===")
        smp1 = bytearray(SAMPLE_ROM_1['size'])
        load_sequential(smp1, SAMPLE_ROM_1['parts'], zf)
        smp1_path = os.path.join(output_dir, 'samples1.bin')
        with open(smp1_path, 'wb') as f:
            f.write(smp1)
        print(f"  -> {smp1_path} ({len(smp1)} bytes)")
        print()

        print("=== Sample ROM 2 (MultiPCM, 4MB) ===")
        smp2 = bytearray(SAMPLE_ROM_2['size'])
        load_sequential(smp2, SAMPLE_ROM_2['parts'], zf)
        smp2_path = os.path.join(output_dir, 'samples2.bin')
        with open(smp2_path, 'wb') as f:
            f.write(smp2)
        print(f"  -> {smp2_path} ({len(smp2)} bytes)")
        print()

    return prog


# ============================================================================
# i960 Disassembler
# ============================================================================

# i960 instruction formats:
#   CTRL: 8-bit opcode + 24-bit displacement
#   COBR: 8-bit opcode + condition bits + displacement
#   REG:  8-bit opcode + register operands
#   MEM:  8-bit opcode + memory addressing modes

# Register names
REG_NAMES = {
    0: 'pfp', 1: 'sp', 2: 'rip',
    **{i: f'r{i}' for i in range(3, 16)},
    16: 'g0', 17: 'g1', 18: 'g2', 19: 'g3',
    20: 'g4', 21: 'g5', 22: 'g6', 23: 'g7',
    24: 'g8', 25: 'g9', 26: 'g10', 27: 'g11',
    28: 'g12', 29: 'g13', 30: 'g14', 31: 'fp',
}

# CTRL format opcodes (bits 31-24)
CTRL_OPS = {
    0x08: 'b',      0x09: 'call',    0x0A: 'ret',     0x0B: 'bal',
    0x10: 'bno',     0x11: 'bg',      0x12: 'be',      0x13: 'bge',
    0x14: 'bl',      0x15: 'bne',     0x16: 'ble',     0x17: 'bo',
    0x18: 'faultno', 0x19: 'faultg',  0x1A: 'faulte',  0x1B: 'faultge',
    0x1C: 'faultl',  0x1D: 'faultne', 0x1E: 'faultle', 0x1F: 'faulto',
}

# REG format opcodes (bits 31-24 + bits 11-7 for extended)
REG_OPS = {
    (0x58, 0x00): 'notbit',   (0x58, 0x01): 'and',      (0x58, 0x02): 'andnot',
    (0x58, 0x03): 'setbit',   (0x58, 0x04): 'notand',   (0x58, 0x06): 'xor',
    (0x58, 0x07): 'or',       (0x58, 0x08): 'nor',      (0x58, 0x09): 'xnor',
    (0x58, 0x0A): 'not',      (0x58, 0x0B): 'ornot',    (0x58, 0x0C): 'clrbit',
    (0x58, 0x0D): 'notor',    (0x58, 0x0E): 'nand',     (0x58, 0x0F): 'alterbit',
    (0x59, 0x00): 'addo',     (0x59, 0x01): 'addi',     (0x59, 0x02): 'subo',
    (0x59, 0x03): 'subi',     (0x59, 0x08): 'shro',     (0x59, 0x0A): 'shrdi',
    (0x59, 0x0B): 'shri',     (0x59, 0x0C): 'shlo',     (0x59, 0x0D): 'rotate',
    (0x59, 0x0E): 'shli',
    (0x5A, 0x00): 'cmpo',     (0x5A, 0x01): 'cmpi',     (0x5A, 0x02): 'concmpo',
    (0x5A, 0x03): 'concmpi',  (0x5A, 0x04): 'cmpinco',  (0x5A, 0x05): 'cmpinci',
    (0x5A, 0x06): 'cmpdeco',  (0x5A, 0x07): 'cmpdeci',
    (0x5C, 0x00): 'mov',      (0x5C, 0x08): 'lda',
    (0x5D, 0x0C): 'scanbit',  (0x5D, 0x0E): 'spanbit',
    (0x60, 0x05): 'modac',
    (0x64, 0x00): 'modi',
    (0x65, 0x00): 'remo',     (0x65, 0x01): 'remi',
    (0x66, 0x00): 'divo',     (0x66, 0x01): 'divi',
    (0x67, 0x00): 'mulo',     (0x67, 0x01): 'muli',
    (0x70, 0x00): 'addono',   (0x70, 0x01): 'addino',   (0x70, 0x02): 'subono',
    (0x70, 0x03): 'subino',
    # Floating point
    (0x68, 0x01): 'addr',     (0x68, 0x05): 'movr',
    (0x69, 0x01): 'subr',     (0x69, 0x05): 'mulr',
    (0x6A, 0x01): 'divr',
    (0x6C, 0x09): 'cvtir',    (0x6C, 0x03): 'cvtri',
    (0x6E, 0x01): 'cmpr',     (0x6E, 0x05): 'cmpor',
    # Test
    (0x5F, 0x00): 'testno',   (0x5F, 0x01): 'testg',    (0x5F, 0x02): 'teste',
    (0x5F, 0x03): 'testge',   (0x5F, 0x04): 'testl',    (0x5F, 0x05): 'testne',
    (0x5F, 0x06): 'testle',   (0x5F, 0x07): 'testo',
}

# COBR format opcodes
COBR_OPS = {
    0x20: 'testno', 0x21: 'testg',  0x22: 'teste',  0x23: 'testge',
    0x24: 'testl',  0x25: 'testne', 0x26: 'testle', 0x27: 'testo',
    0x30: 'bbc',    0x31: 'cmpobg', 0x32: 'cmpobe', 0x33: 'cmpobge',
    0x34: 'cmpobl', 0x35: 'cmpobne',0x36: 'cmpoble',0x37: 'bbs',
    0x38: 'cmpibno',0x39: 'cmpibg', 0x3A: 'cmpibe', 0x3B: 'cmpibge',
    0x3C: 'cmpibl', 0x3D: 'cmpibne',0x3E: 'cmpible',0x3F: 'cmpibo',
}

# MEM format opcodes
MEM_OPS = {
    0x80: 'ldob',   0x82: 'stob',   0x84: 'bx',     0x85: 'balx',
    0x86: 'callx',  0x88: 'ldos',   0x8A: 'stos',
    0x8C: 'lda',
    0x90: 'ld',     0x92: 'st',     0x98: 'ldl',     0x9A: 'stl',
    0xA0: 'ldt',    0xA2: 'stt',
    0xB0: 'ldq',    0xB2: 'stq',
    0xC0: 'ldib',   0xC2: 'stib',   0xC8: 'ldis',   0xCA: 'stis',
}


def sign_extend(val, bits):
    """Sign-extend a value from 'bits' width."""
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val


def disasm_one(data, offset, addr):
    """Disassemble one i960 instruction. Returns (text, size, is_call, is_branch, target)."""
    if offset + 4 > len(data):
        return ('???', 4, False, False, None)

    word = struct.unpack_from('<I', data, offset)[0]
    opcode = (word >> 24) & 0xFF

    # CTRL format (opcodes 0x08-0x1F)
    if 0x08 <= opcode <= 0x1F:
        mnem = CTRL_OPS.get(opcode, f'ctrl_{opcode:02X}')
        disp = sign_extend(word & 0x00FFFFFC, 24)
        target = addr + disp

        is_call = (opcode == 0x09)  # call
        is_branch = opcode in (0x08, 0x0B, 0x10, 0x11, 0x12, 0x13, 0x14, 0x15, 0x16, 0x17)
        is_ret = (opcode == 0x0A)

        if opcode == 0x0A:  # ret
            return (f'{mnem}', 4, False, False, None)
        else:
            return (f'{mnem} 0x{target:08X}', 4, is_call, is_branch, target)

    # COBR format (opcodes 0x20-0x3F)
    if 0x20 <= opcode <= 0x3F:
        mnem = COBR_OPS.get(opcode, f'cobr_{opcode:02X}')
        src1 = (word >> 19) & 0x1F
        src2 = (word >> 14) & 0x1F
        disp = sign_extend(word & 0x1FFC, 13)
        target = addr + disp

        m1 = (word >> 13) & 1  # src1 is literal if set
        s2_flag = (word >> 12) & 1

        src1_str = f'{src1}' if m1 else REG_NAMES.get(src1, f'r{src1}')
        src2_str = REG_NAMES.get(src2, f'r{src2}')

        if 0x20 <= opcode <= 0x27:
            # test instructions - only src1
            return (f'{mnem} {src1_str}', 4, False, False, None)
        else:
            return (f'{mnem} {src1_str}, {src2_str}, 0x{target:08X}', 4, False, True, target)

    # REG format (opcodes 0x58-0x7F)
    if 0x58 <= opcode <= 0x7F:
        ext = (word >> 7) & 0xF
        src1 = word & 0x1F
        src2 = (word >> 14) & 0x1F
        dst = (word >> 19) & 0x1F
        m1 = (word >> 5) & 1  # src1 is literal if set
        m2 = (word >> 12) & 1
        m3 = (word >> 13) & 1  # dst mode

        mnem = REG_OPS.get((opcode, ext), f'reg_{opcode:02X}_{ext:X}')

        src1_str = f'{src1}' if m1 else REG_NAMES.get(src1, f'r{src1}')
        src2_str = f'{src2}' if m2 else REG_NAMES.get(src2, f'r{src2}')
        dst_str = REG_NAMES.get(dst, f'r{dst}')

        # Determine number of operands
        if mnem in ('not', 'mov', 'movr', 'scanbit', 'spanbit',
                     'testno', 'testg', 'teste', 'testge', 'testl', 'testne', 'testle', 'testo',
                     'cvtir', 'cvtri'):
            return (f'{mnem} {src1_str}, {dst_str}', 4, False, False, None)
        elif mnem in ('cmpo', 'cmpi', 'concmpo', 'concmpi', 'cmpr', 'cmpor'):
            return (f'{mnem} {src1_str}, {src2_str}', 4, False, False, None)
        elif mnem == 'modac':
            return (f'{mnem} {src1_str}, {src2_str}, {dst_str}', 4, False, False, None)
        else:
            return (f'{mnem} {src1_str}, {src2_str}, {dst_str}', 4, False, False, None)

    # MEM format (opcodes 0x80-0xCF)
    if 0x80 <= opcode <= 0xCF:
        mnem = MEM_OPS.get(opcode, f'mem_{opcode:02X}')
        src_dst = (word >> 19) & 0x1F
        abase = (word >> 14) & 0x1F
        mode = (word >> 10) & 0xF

        reg_str = REG_NAMES.get(src_dst, f'r{src_dst}')
        abase_str = REG_NAMES.get(abase, f'r{abase}')

        inst_size = 4
        addr_str = ''

        if mode == 0x0:
            # offset
            offset_val = word & 0xFFF
            addr_str = f'0x{offset_val:X}({abase_str})'
        elif mode == 0x4:
            # (abase)
            addr_str = f'({abase_str})'
        elif mode == 0x5:
            # disp32
            if offset + 8 <= len(data):
                disp = struct.unpack_from('<I', data, offset + 4)[0]
                inst_size = 8
                addr_str = f'0x{disp:08X}'
            else:
                addr_str = '???'
                inst_size = 8
        elif mode == 0x7:
            # disp32(abase)
            if offset + 8 <= len(data):
                disp = struct.unpack_from('<I', data, offset + 4)[0]
                inst_size = 8
                addr_str = f'0x{disp:08X}({abase_str})'
            else:
                addr_str = '???'
                inst_size = 8
        elif mode == 0xC:
            # index(abase)
            index = word & 0x1F
            index_str = REG_NAMES.get(index, f'r{index}')
            scale = (word >> 7) & 0x7
            scale_val = 1 << scale if scale else 1
            addr_str = f'({abase_str})[{index_str}*{scale_val}]'
        elif mode == 0xD:
            # disp32[index*scale]
            if offset + 8 <= len(data):
                disp = struct.unpack_from('<I', data, offset + 4)[0]
                index = word & 0x1F
                index_str = REG_NAMES.get(index, f'r{index}')
                scale = (word >> 7) & 0x7
                scale_val = 1 << scale if scale else 1
                inst_size = 8
                addr_str = f'0x{disp:08X}[{index_str}*{scale_val}]'
            else:
                addr_str = '???'
                inst_size = 8
        elif mode == 0xE:
            # disp32(abase)[index*scale]
            if offset + 8 <= len(data):
                disp = struct.unpack_from('<I', data, offset + 4)[0]
                index = word & 0x1F
                index_str = REG_NAMES.get(index, f'r{index}')
                scale = (word >> 7) & 0x7
                scale_val = 1 << scale if scale else 1
                inst_size = 8
                addr_str = f'0x{disp:08X}({abase_str})[{index_str}*{scale_val}]'
            else:
                addr_str = '???'
                inst_size = 8
        else:
            addr_str = f'mode{mode:X}({abase_str})'

        is_call = (opcode == 0x86)  # callx
        is_branch = (opcode == 0x84)  # bx

        if opcode in (0x82, 0x8A, 0x92, 0x9A, 0xA2, 0xB2, 0xC2, 0xCA):
            # Store: st src, addr
            return (f'{mnem} {reg_str}, {addr_str}', inst_size, is_call, is_branch, None)
        else:
            # Load/branch: ld addr, dst
            return (f'{mnem} {addr_str}, {reg_str}', inst_size, is_call, is_branch, None)

    return (f'.word 0x{word:08X}', 4, False, False, None)


def find_functions(data, base_addr=0, max_size=None):
    """
    Discover functions by following calls and branches.
    Uses recursive descent starting from known entry points.
    """
    if max_size is None:
        max_size = len(data)

    functions = {}       # addr -> {'name': str, 'size': int, 'calls': set, 'callers': set}
    visited = set()      # addresses already disassembled
    call_targets = set() # addresses that are call targets
    work_queue = []      # addresses to explore

    # i960 boot: first 12 words at address 0 are the Initial Boot Record (IBR)
    # Word 0-3: initial bus configuration
    # Word 8: first instruction pointer (IP)
    # Word 12: initial system address table pointer (PRCB)
    if len(data) >= 48:
        # Read the IBR
        ibr = struct.unpack_from('<12I', data, 0)
        print(f"\n=== i960 Initial Boot Record (IBR) ===")
        for i, val in enumerate(ibr):
            print(f"  IBR[{i:2d}] = 0x{val:08X}")

        # The first IP is typically at IBR[8] for i960KB
        # But Model 2 uses a different boot sequence
        # Let's look for the PRCB and SAT
        print()

    # Look for function prologues: common i960 patterns
    # Pattern 1: The first code after IBR
    # Pattern 2: Targets of CALL instructions
    # Pattern 3: Entries in jump tables

    # Start by scanning for common prologue patterns
    # i960 functions often start with:
    #   - Saving registers (stl, stq)
    #   - Setting up frame (lda sp, ...)
    #   - Or just direct code

    # First, find all CALL/BAL targets by linear scan
    print("=== Linear scan for CALL/BRANCH targets ===")
    offset = 0
    instruction_count = 0
    while offset < max_size and offset < len(data):
        text, size, is_call, is_branch, target = disasm_one(data, offset, base_addr + offset)
        instruction_count += 1

        if target is not None and (is_call or is_branch):
            if 0 <= target < len(data):
                if is_call:
                    call_targets.add(target)

        offset += size

    print(f"  Total instructions scanned: {instruction_count}")
    print(f"  Call targets found: {len(call_targets)}")

    # Find additional functions via prologue detection
    # Common i960KB prologue: starts right after previous ret or at aligned address
    prologue_addrs = set()
    offset = 0
    prev_was_ret = False
    while offset < max_size and offset < len(data):
        word = struct.unpack_from('<I', data, offset)[0]
        opcode = (word >> 24) & 0xFF

        if prev_was_ret and word != 0:
            prologue_addrs.add(base_addr + offset)

        prev_was_ret = (opcode == 0x0A)  # ret
        offset += 4

    # Combine all discovered function addresses
    all_funcs = sorted(call_targets | prologue_addrs)

    # Filter out addresses that point to zero/invalid data
    valid_funcs = []
    for addr in all_funcs:
        if addr < len(data) - 4:
            word = struct.unpack_from('<I', data, addr)[0]
            if word != 0 and word != 0xFFFFFFFF:
                valid_funcs.append(addr)

    print(f"  Post-ret prologues: {len(prologue_addrs)}")
    print(f"  Total unique functions: {len(valid_funcs)}")

    return valid_funcs


def disassemble_region(data, start, end, base_addr=0):
    """Disassemble a region and return lines."""
    lines = []
    offset = start
    while offset < end and offset < len(data):
        addr = base_addr + offset
        text, size, is_call, is_branch, target = disasm_one(data, offset, addr)
        lines.append(f'{addr:08X}:  {text}')
        offset += size
    return lines


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <vcop.zip> <output_dir>")
        sys.exit(1)

    zip_path = sys.argv[1]
    output_dir = sys.argv[2]

    # Extract ROMs
    prog_data = extract_roms(zip_path, output_dir)

    # Find the actual program size (skip trailing zeros/FF)
    prog_end = len(prog_data)
    while prog_end > 0 and (prog_data[prog_end - 1] == 0x00 or prog_data[prog_end - 1] == 0xFF):
        prog_end -= 1
    prog_end = (prog_end + 3) & ~3  # Align to 4
    print(f"\n=== i960 Program ROM Analysis ===")
    print(f"  Total size: {len(prog_data)} bytes ({len(prog_data) / 1024:.0f} KB)")
    print(f"  Used size: {prog_end} bytes ({prog_end / 1024:.0f} KB)")

    # Discover functions
    functions = find_functions(prog_data, max_size=prog_end)

    # Write function list
    func_list_path = os.path.join(output_dir, 'functions.txt')
    with open(func_list_path, 'w') as f:
        f.write(f"# Virtua Cop i960 Function List\n")
        f.write(f"# {len(functions)} functions discovered\n")
        f.write(f"# Format: address\n\n")
        for addr in functions:
            f.write(f"0x{addr:08X}\n")
    print(f"\n  Function list: {func_list_path}")

    # Full disassembly
    print(f"\n=== Generating full disassembly ===")
    disasm_path = os.path.join(output_dir, 'disasm.txt')
    with open(disasm_path, 'w') as f:
        f.write(f"; Virtua Cop i960 Disassembly\n")
        f.write(f"; {prog_end} bytes of code\n\n")

        func_set = set(functions)
        offset = 0
        while offset < prog_end:
            addr = offset
            if addr in func_set:
                f.write(f"\n; ---- Function at 0x{addr:08X} ----\n")
                f.write(f"vcop_{addr:08X}:\n")

            text, size, is_call, is_branch, target = disasm_one(prog_data, offset, addr)
            hexbytes = ' '.join(f'{prog_data[offset + i]:02X}' for i in range(min(size, 8)))
            f.write(f"  {addr:08X}:  {hexbytes:24s} {text}\n")
            offset += size

    print(f"  Disassembly: {disasm_path}")
    print(f"\nDone!")


if __name__ == '__main__':
    main()
