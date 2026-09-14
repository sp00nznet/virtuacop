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

# TGP coprocessor math tables (CPU board): sin/cos, atan, 1/x, 1/sqrt(x)
COPRO_TABLES_ROM = {
    'size': 0x40000,
    'parts': [
        ('opr-14742a.45', 0x000000, 0x020000, 0),
        ('opr-14743a.46', 0x000000, 0x020000, 2),
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
            # Program ROM: (name_b, name_a, offset, size, word_off). Revision B
            # and Revision A differ only in these two chips, so take whichever
            # the ZIP actually has rather than demanding one set.
            names = [part[0], part[1]]
            offset = part[2]
            file_size = part[3]
            word_offset = part[4]
        else:
            # Data/polygon/texture ROM: (name, offset, size, word_off)
            names = [part[0]]
            offset = part[1]
            file_size = part[2]
            word_offset = part[3]

        data = None
        for name in names:
            data = load_file_from_zip(zf, name)
            if data is not None:
                break
        if data is None:
            print(f"  WARNING: {' / '.join(names)} not found in ZIP")
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

        # TGP coprocessor tables
        print("=== Copro TGP tables (256KB) ===")
        ctab = bytearray(COPRO_TABLES_ROM['size'])
        interleave_32bit(ctab, COPRO_TABLES_ROM['parts'], zf)
        ctab_path = os.path.join(output_dir, 'copro_tables.bin')
        with open(ctab_path, 'wb') as f:
            f.write(ctab)
        print(f"  -> {ctab_path} ({len(ctab)} bytes)")
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
#
# The i960 is the Model 2's CPU, not this game's, so the disassembler and the
# function discovery that rides on it live in the submodule and are shared with
# every other game built on it. Re-exported here because this file's main()
# uses them and because reading the ROM by hand is what they are for.

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ext' / 'model2recomp' / 'tools'))
from i960_disasm import (  # noqa: E402
    disasm_one, find_functions, disassemble_region, sign_extend,
    REG_NAMES, CTRL_OPS, REG_OPS, COBR_OPS, MEM_OPS,
)

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
