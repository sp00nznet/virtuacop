#!/usr/bin/env python3
"""
i960 Static Recompiler (Lifter)

Reads an i960 program binary and generates C code that performs
the equivalent operations using the model2recomp i960_ops.h macros.

Usage:
    python i960_lifter.py <program.bin> <output_dir>
"""

import os
import sys
import re
import struct
from pathlib import Path
from collections import defaultdict


# Matches an emitted label line, e.g. "L_000005E4: ;"
_LABEL_RE = re.compile(r'^\s*L_([0-9A-Fa-f]{8})\s*:')
# Matches a goto referencing a label, e.g. "goto L_000005E4"
_GOTO_RE = re.compile(r'goto L_([0-9A-Fa-f]{8})')


# Register name mapping for C code
C_REG = {
    0: 'I960_R(0)/*pfp*/', 1: 'I960_SP', 2: 'I960_R(2)/*rip*/',
    **{i: f'I960_R({i})' for i in range(3, 16)},
    16: 'I960_G(0)', 17: 'I960_G(1)', 18: 'I960_G(2)', 19: 'I960_G(3)',
    20: 'I960_G(4)', 21: 'I960_G(5)', 22: 'I960_G(6)', 23: 'I960_G(7)',
    24: 'I960_G(8)', 25: 'I960_G(9)', 26: 'I960_G(10)', 27: 'I960_G(11)',
    28: 'I960_G(12)', 29: 'I960_G(13)', 30: 'I960_G(14)', 31: 'I960_FP',
}


def sign_extend(val, bits):
    if val & (1 << (bits - 1)):
        val -= 1 << bits
    return val


def get_reg_c(r):
    return C_REG.get(r, f'I960_R({r})')


def comment_safe(s):
    """Neutralize comment markers so an expression can be embedded inside a
    /* ... */ comment without prematurely closing it (C has no nested comments).
    Register annotations like I960_R(0)/*pfp*/ would otherwise break TODO lines."""
    return s.replace('/*', '(*').replace('*/', '*)')


def get_src_c(reg, is_literal):
    """Get C expression for a source operand (register or literal)."""
    if is_literal:
        return f'{reg}'  # literal value
    return get_reg_c(reg)


class I960Lifter:
    def __init__(self, data, base_addr=0):
        self.data = data
        self.base_addr = base_addr
        self.functions = {}   # addr -> list of C lines
        self.call_targets = set()
        self.branch_targets = defaultdict(set)  # func_addr -> set of label addrs

    def read32(self, offset):
        if offset + 4 <= len(self.data):
            return struct.unpack_from('<I', self.data, offset)[0]
        return 0

    def lift_function(self, func_addr, end_addr=None):
        """Lift one function starting at func_addr to C code."""
        lines = []
        offset = func_addr
        max_addr = end_addr if end_addr else min(func_addr + 0x10000, len(self.data))

        # First pass: find branch targets within this function
        local_labels = set()
        scan_offset = func_addr
        while scan_offset < max_addr:
            word = self.read32(scan_offset)
            opcode = (word >> 24) & 0xFF
            inst_size = 4

            # Check for 8-byte instructions (MEMB format with displacement)
            if 0x80 <= opcode <= 0xCF and (word & 0x1000):
                mode = (word >> 10) & 0xF
                if mode in (0x5, 0xC, 0xD, 0xE, 0xF):  # modes with disp32
                    inst_size = 8

            # Find branch targets
            target = None
            if 0x08 <= opcode <= 0x1F:  # CTRL
                disp = sign_extend(word & 0x00FFFFFC, 24)
                target = scan_offset + disp
            elif 0x20 <= opcode <= 0x3F:  # COBR
                disp = sign_extend(word & 0x1FFC, 13)
                target = scan_offset + disp

            if target is not None and func_addr <= target < max_addr:
                local_labels.add(target)

            # Without explicit bounds, the function ends at the first ret.
            # With bounds, lift the whole range so multi-block functions (a
            # conditional branch that skips over an early ret) keep all their
            # labels; trailing data past the final ret becomes dead code.
            if opcode == 0x0A and end_addr is None:
                max_addr = scan_offset + 4
                break

            scan_offset += inst_size

        # Second pass: generate C code
        while offset < max_addr:
            addr = offset
            word = self.read32(offset)
            opcode = (word >> 24) & 0xFF

            # Emit label if this is a branch target. The trailing ';' is an
            # empty statement so a label is valid even when the next line is a
            # comment or the closing brace of the function.
            if addr in local_labels:
                lines.append(f'L_{addr:08X}: ;')

            c_code, inst_size = self._lift_instruction(word, addr)
            if c_code:
                for line in c_code:
                    lines.append(f'    {line}')

            offset += inst_size

            # Without explicit bounds, stop at the first ret.
            if opcode == 0x0A and end_addr is None:
                break

        lines = self._fixup_dangling_gotos(lines)
        self.functions[func_addr] = lines
        return lines

    @staticmethod
    def _fixup_dangling_gotos(lines):
        """Rewrite any goto whose target label was never emitted.

        Out-of-range branches (and bytes misdecoded as code in data regions)
        produce gotos to addresses with no label in this function. Route them
        through the function table as a tail call so the output always compiles
        and inter-function transfers still dispatch correctly at runtime.
        """
        emitted = set()
        for ln in lines:
            m = _LABEL_RE.match(ln)
            if m:
                emitted.add(m.group(1).upper())

        def make_repl(is_bal):
            def repl(mm):
                tgt = mm.group(1).upper()
                if tgt in emitted:
                    return mm.group(0)
                if is_bal:
                    # bal is a leaf call: the callee returns via bx (g14) to the
                    # instruction after the bal, so fall through, don't tail-call.
                    return f'func_table_call(0x{tgt})'
                return f'{{ func_table_call(0x{tgt}); return; }}'
            return repl

        return [_GOTO_RE.sub(make_repl(ln.rstrip().endswith('/* bal */')), ln)
                for ln in lines]

    def _lift_instruction(self, word, addr):
        """Lift a single instruction to C code. Returns (list of C lines, inst_size)."""
        opcode = (word >> 24) & 0xFF
        lines = []
        ret_size = 4  # default, updated for 8-byte MEM instructions

        # ---- CTRL format ----
        if 0x08 <= opcode <= 0x1F:
            disp = sign_extend(word & 0x00FFFFFC, 24)
            target = (addr + disp) & 0xFFFFFFFF

            if opcode == 0x08:  # b (unconditional branch)
                lines.append(f'goto L_{target:08X}; /* b 0x{target:08X} */')
            elif opcode == 0x09:  # call
                self.call_targets.add(target)
                lines.append(f'i960_do_call(0x{target:08X}, 0x{addr+4:08X});')
                lines.append(f'func_table_call(0x{target:08X}); /* call 0x{target:08X} */')
            elif opcode == 0x0A:  # ret
                lines.append(f'i960_do_ret(); /* ret */')
                lines.append(f'return;')
            elif opcode == 0x0B:  # bal (branch and link)
                lines.append(f'I960_G(14) = 0x{addr+4:08X}; /* bal 0x{target:08X} */')
                lines.append(f'goto L_{target:08X}; /* bal */')
            elif opcode == 0x10:  # bno
                lines.append(f'/* bno 0x{target:08X} - branch if unordered (NaN) */')
            elif opcode == 0x11:  # bg
                lines.append(f'if (i960_test_cc(COND_G)) goto L_{target:08X}; /* bg */')
            elif opcode == 0x12:  # be
                lines.append(f'if (i960_test_cc(COND_E)) goto L_{target:08X}; /* be */')
            elif opcode == 0x13:  # bge
                lines.append(f'if (i960_test_cc(COND_GE)) goto L_{target:08X}; /* bge */')
            elif opcode == 0x14:  # bl
                lines.append(f'if (i960_test_cc(COND_L)) goto L_{target:08X}; /* bl */')
            elif opcode == 0x15:  # bne
                lines.append(f'if (i960_test_cc(COND_NE)) goto L_{target:08X}; /* bne */')
            elif opcode == 0x16:  # ble
                lines.append(f'if (i960_test_cc(COND_LE)) goto L_{target:08X}; /* ble */')
            elif opcode == 0x17:  # bo
                lines.append(f'/* bo 0x{target:08X} - branch if ordered */')
            else:
                lines.append(f'/* TODO: ctrl opcode 0x{opcode:02X} target 0x{target:08X} */')
            return lines, ret_size

        # ---- COBR format ----
        if 0x20 <= opcode <= 0x3F:
            src1_reg = (word >> 19) & 0x1F
            src2_reg = (word >> 14) & 0x1F
            m1 = (word >> 13) & 1
            disp = sign_extend(word & 0x1FFC, 13)
            target = (addr + disp) & 0xFFFFFFFF

            src1 = get_src_c(src1_reg, m1)
            src2 = get_reg_c(src2_reg)

            if opcode == 0x30:  # bbc (branch if bit clear)
                lines.append(f'if (!({src2} & (1u << ({src1} & 31)))) goto L_{target:08X}; /* bbc */')
            elif opcode == 0x37:  # bbs (branch if bit set)
                lines.append(f'if ({src2} & (1u << ({src1} & 31))) goto L_{target:08X}; /* bbs */')
            elif opcode == 0x31:  # cmpobg
                lines.append(f'op_cmpo({src1}, {src2});')
                lines.append(f'if (i960_test_cc(COND_G)) goto L_{target:08X}; /* cmpobg */')
            elif opcode == 0x32:  # cmpobe
                lines.append(f'op_cmpo({src1}, {src2});')
                lines.append(f'if (i960_test_cc(COND_E)) goto L_{target:08X}; /* cmpobe */')
            elif opcode == 0x33:  # cmpobge
                lines.append(f'op_cmpo({src1}, {src2});')
                lines.append(f'if (i960_test_cc(COND_GE)) goto L_{target:08X}; /* cmpobge */')
            elif opcode == 0x34:  # cmpobl
                lines.append(f'op_cmpo({src1}, {src2});')
                lines.append(f'if (i960_test_cc(COND_L)) goto L_{target:08X}; /* cmpobl */')
            elif opcode == 0x35:  # cmpobne
                lines.append(f'op_cmpo({src1}, {src2});')
                lines.append(f'if (i960_test_cc(COND_NE)) goto L_{target:08X}; /* cmpobne */')
            elif opcode == 0x36:  # cmpoble
                lines.append(f'op_cmpo({src1}, {src2});')
                lines.append(f'if (i960_test_cc(COND_LE)) goto L_{target:08X}; /* cmpoble */')
            elif opcode == 0x39:  # cmpibg
                lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2});')
                lines.append(f'if (i960_test_cc(COND_G)) goto L_{target:08X}; /* cmpibg */')
            elif opcode == 0x3A:  # cmpibe
                lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2});')
                lines.append(f'if (i960_test_cc(COND_E)) goto L_{target:08X}; /* cmpibe */')
            elif opcode == 0x3B:  # cmpibge
                lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2});')
                lines.append(f'if (i960_test_cc(COND_GE)) goto L_{target:08X}; /* cmpibge */')
            elif opcode == 0x3C:  # cmpibl
                lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2});')
                lines.append(f'if (i960_test_cc(COND_L)) goto L_{target:08X}; /* cmpibl */')
            elif opcode == 0x3D:  # cmpibne
                lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2});')
                lines.append(f'if (i960_test_cc(COND_NE)) goto L_{target:08X}; /* cmpibne */')
            elif opcode == 0x3E:  # cmpible
                lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2});')
                lines.append(f'if (i960_test_cc(COND_LE)) goto L_{target:08X}; /* cmpible */')
            else:
                lines.append(f'/* TODO: COBR opcode 0x{opcode:02X} */')
            return lines, ret_size

        # ---- REG format ----
        if 0x58 <= opcode <= 0x7F:
            ext = (word >> 7) & 0xF
            src1_reg = word & 0x1F
            src2_reg = (word >> 14) & 0x1F
            dst_reg = (word >> 19) & 0x1F
            # Operand mode flags: m1=bit11 (0x800), m2=bit12 (0x1000).
            # When set, the corresponding src field is a 5-bit literal rather
            # than a register. (Bit 5 is NOT m1 - that earlier decode silently
            # corrupted every REG op with a literal src1, e.g. "addo 4, ...".)
            m1 = (word >> 11) & 1
            m2 = (word >> 12) & 1
            m3 = (word >> 13) & 1

            src1 = get_src_c(src1_reg, m1)
            src2 = get_src_c(src2_reg, m2)
            dst = get_reg_c(dst_reg)

            # Real operands: a mode bit selects an fp register (literal form)
            # or an ordinary register holding IEEE bits. Resolved statically
            # here; mirrors get_1_rif / get_2_rif / set_rif in the MAME core.
            def f_src(reg, mode, long_real=False):
                if not mode:
                    if long_real:
                        return f'i960_u2d(g_i960.r[{reg & 0x1E}], g_i960.r[{(reg & 0x1E) + 1}])'
                    return f'i960_u2f(g_i960.r[{reg}])'
                if reg < 4:
                    return f'g_i960.fp[{reg}]'
                return '1.0' if reg == 0x16 else '0.0'

            def f_dst(expr, long_real=False):
                if m3:
                    return f'g_i960.fp[{dst_reg & 3}] = {expr};'
                if long_real:
                    pair = dst_reg & 0x1E
                    return f'i960_d2u({expr}, &g_i960.r[{pair}], &g_i960.r[{pair + 1}]);'
                return f'g_i960.r[{dst_reg}] = i960_f2u({expr});'

            key = (opcode, ext)

            # ---- 0x58: logical operations ----
            if key == (0x58, 0x00):    lines.append(f'{dst} = {src2} ^ (1u << ({src1} & 31)); /* notbit */')
            elif key == (0x58, 0x01):  lines.append(f'{dst} = {src1} & {src2}; /* and */')
            elif key == (0x58, 0x02):  lines.append(f'{dst} = {src2} & ~{src1}; /* andnot */')
            elif key == (0x58, 0x03):  lines.append(f'{dst} = {src2} | (1u << ({src1} & 31)); /* setbit */')
            elif key == (0x58, 0x04):  lines.append(f'{dst} = ~{src2} & {src1}; /* notand */')
            elif key == (0x58, 0x06):  lines.append(f'{dst} = {src1} ^ {src2}; /* xor */')
            elif key == (0x58, 0x07):  lines.append(f'{dst} = {src1} | {src2}; /* or */')
            elif key == (0x58, 0x08):  lines.append(f'{dst} = ~({src1} | {src2}); /* nor */')
            elif key == (0x58, 0x09):  lines.append(f'{dst} = ~({src1} ^ {src2}); /* xnor */')
            elif key == (0x58, 0x0A):  lines.append(f'{dst} = ~{src1}; /* not */')
            elif key == (0x58, 0x0B):  lines.append(f'{dst} = {src2} | ~{src1}; /* ornot */')
            elif key == (0x58, 0x0C):  lines.append(f'{dst} = {src2} & ~(1u << ({src1} & 31)); /* clrbit */')
            elif key == (0x58, 0x0D):  lines.append(f'{dst} = ~{src2} | {src1}; /* notor */')
            elif key == (0x58, 0x0E):  lines.append(f'{dst} = ~({src1} & {src2}); /* nand */')
            elif key == (0x58, 0x0F):  lines.append(f'{dst} = ({src2} & ~(1u << ({src1} & 31))) | (({dst} & 1) << ({src1} & 31)); /* alterbit */')

            # ---- 0x59: arithmetic + shifts ----
            elif key == (0x59, 0x00):  lines.append(f'{dst} = {src1} + {src2}; /* addo */')
            elif key == (0x59, 0x01):  lines.append(f'{dst} = {src1} + {src2}; /* addi */')
            elif key == (0x59, 0x02):  lines.append(f'{dst} = {src2} - {src1}; /* subo */')
            elif key == (0x59, 0x03):  lines.append(f'{dst} = {src2} - {src1}; /* subi */')
            elif key == (0x59, 0x08):  lines.append(f'{dst} = op_shro({src1}, {src2}); /* shro */')
            elif key == (0x59, 0x0A):  lines.append(f'/* shrdi - TODO */')
            elif key == (0x59, 0x0B):  lines.append(f'{dst} = (uint32_t)((int32_t){src2} >> ({src1} & 31)); /* shri */')
            elif key == (0x59, 0x0C):  lines.append(f'{dst} = op_shlo({src1}, {src2}); /* shlo */')
            elif key == (0x59, 0x0D):  lines.append(f'{dst} = op_rotate({src1}, {src2}); /* rotate */')
            elif key == (0x59, 0x0E):  lines.append(f'{dst} = op_shlo({src1}, {src2}); /* shli */')

            # ---- 0x5A: compare ----
            elif key == (0x5A, 0x00):  lines.append(f'op_cmpo({src1}, {src2}); /* cmpo */')
            elif key == (0x5A, 0x01):  lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2}); /* cmpi */')
            elif key == (0x5A, 0x02):  lines.append(f'op_cmpo({src1}, {src2}); /* concmpo */')
            elif key == (0x5A, 0x03):  lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2}); /* concmpi */')
            elif key == (0x5A, 0x04):  lines.append(f'op_cmpo({src1}, {src2}); {dst} = {src2} + 1; /* cmpinco */')
            elif key == (0x5A, 0x05):  lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2}); {dst} = {src2} + 1; /* cmpinci */')
            elif key == (0x5A, 0x06):  lines.append(f'op_cmpo({src1}, {src2}); {dst} = {src2} - 1; /* cmpdeco */')
            elif key == (0x5A, 0x07):  lines.append(f'op_cmpi((int32_t){src1}, (int32_t){src2}); {dst} = {src2} - 1; /* cmpdeci */')
            elif key == (0x5A, 0x0E):  lines.append(f'op_chkbit({src1}, {src2}); /* chkbit */')

            # ---- 0x5C: mov ----
            elif key == (0x5C, 0x0C):  lines.append(f'{dst} = {src1}; /* mov */')

            # ---- 0x5D: movl (64-bit move, register pair) ----
            elif key == (0x5D, 0x0C):
                dst_pair = dst_reg & 0x1E
                src1_pair = src1_reg & 0x1E
                lines.append(f'g_i960.r[{dst_pair}] = g_i960.r[{src1_pair}]; g_i960.r[{dst_pair}+1] = g_i960.r[{src1_pair}+1]; /* movl */')

            # ---- 0x5E: movt (96-bit move, register triple) ----
            elif key == (0x5E, 0x0C):
                dst_triple = dst_reg & 0x1C
                src1_triple = src1_reg & 0x1C
                lines.append(f'g_i960.r[{dst_triple}] = g_i960.r[{src1_triple}]; g_i960.r[{dst_triple}+1] = g_i960.r[{src1_triple}+1]; g_i960.r[{dst_triple}+2] = g_i960.r[{src1_triple}+2]; /* movt */')

            # ---- 0x5F: movq (128-bit) / test ----
            elif key == (0x5F, 0x0C):
                dst_quad = dst_reg & 0x1C
                src1_quad = src1_reg & 0x1C
                lines.append(f'g_i960.r[{dst_quad}] = g_i960.r[{src1_quad}]; g_i960.r[{dst_quad}+1] = g_i960.r[{src1_quad}+1]; g_i960.r[{dst_quad}+2] = g_i960.r[{src1_quad}+2]; g_i960.r[{dst_quad}+3] = g_i960.r[{src1_quad}+3]; /* movq */')
            elif key == (0x5F, 0x00):  lines.append(f'{dst} = 0; /* testno (always false) */')
            elif key == (0x5F, 0x01):  lines.append(f'{dst} = op_testg(); /* testg */')
            elif key == (0x5F, 0x02):  lines.append(f'{dst} = op_teste(); /* teste */')
            elif key == (0x5F, 0x03):  lines.append(f'{dst} = op_testge(); /* testge */')
            elif key == (0x5F, 0x04):  lines.append(f'{dst} = op_testl(); /* testl */')
            elif key == (0x5F, 0x05):  lines.append(f'{dst} = op_testne(); /* testne */')
            elif key == (0x5F, 0x06):  lines.append(f'{dst} = op_testle(); /* testle */')
            elif key == (0x5F, 0x07):  lines.append(f'{dst} = 1; /* testo (always true) */')

            # ---- 0x60: synmov/synmovl/synmovq ----
            elif key == (0x60, 0x00):
                lines.append(f'bus_write32({src1}, bus_read32({src2})); /* synmov */')
            elif key == (0x60, 0x02):
                lines.append(f'bus_write32({src1}, bus_read32({src2})); bus_write32({src1}+4, bus_read32({src2}+4)); bus_write32({src1}+8, bus_read32({src2}+8)); bus_write32({src1}+12, bus_read32({src2}+12)); /* synmovq */')

            # ---- 0x64: spanbit, scanbit, modac ----
            elif key == (0x64, 0x00):
                lines.append(f'{{ uint32_t _v = {src1}; {dst} = 0xFFFFFFFF; for (int _i = 31; _i >= 0; _i--) {{ if (!(_v & (1u << _i))) {{ {dst} = _i; break; }} }} }} /* spanbit */')
            elif key == (0x64, 0x01):
                lines.append(f'{{ uint32_t _v = {src1}; {dst} = 0xFFFFFFFF; for (int _i = 31; _i >= 0; _i--) {{ if (_v & (1u << _i)) {{ {dst} = _i; break; }} }} }} /* scanbit */')
            elif key == (0x64, 0x05):
                lines.append(f'{dst} = g_i960.AC; g_i960.AC = (g_i960.AC & ~{src1}) | ({src2} & {src1}); /* modac */')

            # ---- 0x65: modpc ----
            elif key == (0x65, 0x05):
                lines.append(f'{dst} = g_i960.PC; g_i960.PC = (g_i960.PC & ~{src2}) | (g_i960.r[{dst_reg}] & {src2}); /* modpc */')

            # ---- 0x66: calls ----
            elif key == (0x66, 0x00):
                lines.append(f'/* calls {comment_safe(src1)} - system call */')

            # ---- 0x67: emul, ediv ----
            elif key == (0x67, 0x00):
                dst_pair = dst_reg & 0x1E
                lines.append(f'{{ uint64_t _r = (uint64_t){src1} * (uint64_t){src2}; g_i960.r[{dst_pair}+1] = (uint32_t)(_r >> 32); g_i960.r[{dst_pair}] = (uint32_t)_r; }} /* emul */')
            elif key == (0x67, 0x01):
                dst_pair = dst_reg & 0x1E
                src2_pair = src2_reg & 0x1E
                lines.append(f'{{ uint64_t _d = ((uint64_t)g_i960.r[{src2_pair + 1}] << 32) | g_i960.r[{src2_pair}]; if ({src1}) {{ g_i960.r[{dst_pair}] = (uint32_t)(_d % {src1}); g_i960.r[{dst_pair}+1] = (uint32_t)(_d / {src1}); }} }} /* ediv */')

            # ---- 0x674-0x677, 0x6C0-0x6C3: integer <-> real conversion ----
            elif key == (0x67, 0x04):
                lines.append(f_dst(f'(double)(int32_t){src1}') + ' /* cvtir */')
            elif key == (0x67, 0x05):
                lines.append(f_dst(f'(double)(int32_t){src1}', True) + ' /* cvtilr */')
            elif key == (0x67, 0x06):
                lines.append(f_dst(f'{f_src(src2_reg, m2, True)} * pow(2.0, (double)(int32_t){src1})', True) + ' /* scalerl */')
            elif key == (0x67, 0x07):
                lines.append(f_dst(f'{f_src(src2_reg, m2)} * pow(2.0, (double)(int32_t){src1})') + ' /* scaler */')

            elif key == (0x6C, 0x00):
                lines.append(f'{dst} = (uint32_t)(int32_t)i960_round({f_src(src1_reg, m1)}); /* cvtri */')
            elif key == (0x6C, 0x02):
                lines.append(f'{dst} = (uint32_t)(int32_t){f_src(src1_reg, m1)}; /* cvtzri */')
            elif key in ((0x6C, 0x01), (0x6C, 0x03)):
                pair = dst_reg & 0x1E
                conv = 'i960_round(' + f_src(src1_reg, m1) + ')' if ext == 0x01 else f_src(src1_reg, m1)
                mnem = 'cvtril' if ext == 0x01 else 'cvtzril'
                lines.append(f'{{ int64_t _v = (int64_t){conv}; g_i960.r[{pair}] = (uint32_t)_v; g_i960.r[{pair + 1}] = (uint32_t)((uint64_t)_v >> 32); }} /* {mnem} */')

            # ---- 0x680-0x68E / 0x690-0x69E: transcendental (real / long real) ----
            elif opcode in (0x68, 0x69):
                lr = (opcode == 0x69)
                a = f_src(src1_reg, m1, lr)
                b = f_src(src2_reg, m2, lr)
                unary = {0x08: f'sqrt({a})', 0x09: f'pow(2.0, {a}) - 1.0',
                         0x0A: f'logb({a})', 0x0B: f'i960_round({a})',
                         0x0C: f'sin({a})', 0x0D: f'cos({a})', 0x0E: f'tan({a})'}
                binary = {0x00: f'atan2({b}, {a})', 0x01: f'{b} * log2({a} + 1.0)',
                          0x02: f'{b} * log2({a})', 0x03: f'fmod({b}, {a})'}
                suffix = 'rl' if lr else 'r'
                if ext == 0x05:
                    lines.append(f'i960_cmp_d({a}, {b}); /* cmp{suffix} */')
                elif ext in unary:
                    lines.append(f_dst(unary[ext], lr) + f' /* op{ext:X}{suffix} */')
                elif ext in binary:
                    lines.append(f_dst(binary[ext], lr) + f' /* op{ext:X}{suffix} */')
                else:
                    lines.append(f'/* TODO: REG opcode=(0x{opcode:02X}, 0x{ext:X}) word=0x{word:08X} */')

            # ---- 0x6C9 movr / 0x6D9 movrl / 0x6E1 movre ----
            elif key == (0x6C, 0x09):
                lines.append(f_dst(f_src(src1_reg, m1)) + ' /* movr */')
            elif key == (0x6D, 0x09):
                lines.append(f_dst(f_src(src1_reg, m1, True), True) + ' /* movrl */')
            elif key == (0x6E, 0x01):
                lines.append(f_dst(f_src(src1_reg, m1, True), True) + ' /* movre (as long real) */')

            # ---- 0x70: mulo, remo, divo ----
            elif key == (0x70, 0x01):  lines.append(f'{dst} = {src1} * {src2}; /* mulo */')
            elif key == (0x70, 0x08):  lines.append(f'{dst} = ({src1} != 0) ? ({src2} % {src1}) : 0; /* remo */')
            elif key == (0x70, 0x0B):  lines.append(f'{dst} = ({src1} != 0) ? ({src2} / {src1}) : 0; /* divo */')

            # ---- 0x74: muli, remi, divi ----
            elif key == (0x74, 0x01):  lines.append(f'{dst} = (uint32_t)((int32_t){src1} * (int32_t){src2}); /* muli */')
            elif key == (0x74, 0x08):  lines.append(f'{dst} = ({src1} != 0) ? (uint32_t)((int32_t){src2} % (int32_t){src1}) : 0; /* remi */')
            elif key == (0x74, 0x0B):  lines.append(f'{dst} = ({src1} != 0) ? (uint32_t)((int32_t){src2} / (int32_t){src1}) : 0; /* divi */')

            # ---- 0x78B-0x78F / 0x79B-0x79F: real arithmetic ----
            elif opcode in (0x78, 0x79) and ext in (0x0B, 0x0C, 0x0D, 0x0F):
                lr = (opcode == 0x79)
                a = f_src(src1_reg, m1, lr)
                b = f_src(src2_reg, m2, lr)
                op, mnem = {0x0B: ('/', 'div'), 0x0C: ('*', 'mul'),
                            0x0D: ('-', 'sub'), 0x0F: ('+', 'add')}[ext]
                lines.append(f_dst(f'{b} {op} {a}', lr) + f' /* {mnem}r{"l" if lr else ""} */')

            else:
                lines.append(f'/* TODO: REG opcode=(0x{opcode:02X}, 0x{ext:X}) word=0x{word:08X} */')
            return lines, ret_size

        # ---- MEM format ----
        if 0x80 <= opcode <= 0xCF:
            src_dst_reg = (word >> 19) & 0x1F
            abase_reg = (word >> 14) & 0x1F

            reg = get_reg_c(src_dst_reg)
            abase = get_reg_c(abase_reg)

            # Compute effective address using MAME's get_ea() logic
            ea = None
            inst_size = 4

            if not (word & 0x1000):
                # MEMA format (bit 12 = 0): 13-bit offset, optional abase
                offset_val = word & 0x1FFF
                if word & 0x2000:
                    # abase + offset
                    if offset_val == 0:
                        ea = f'{abase}'
                    else:
                        ea = f'({abase} + 0x{offset_val:X})'
                else:
                    # absolute offset (no abase)
                    ea = f'0x{offset_val:X}u'
            else:
                # MEMB format (bit 12 = 1): mode + index + scale
                mode = (word >> 10) & 0xF
                index_reg = word & 0x1F
                scale_bits = (word >> 7) & 0x7
                scale_val = 1 << scale_bits
                idx = get_reg_c(index_reg)

                if mode == 0x4:    # (abase) - register indirect
                    ea = f'{abase}'
                elif mode == 0x5:  # IP-relative: disp32 + (addr + 8)
                    disp = self.read32(addr + 4)
                    inst_size = 8
                    target = (disp + (addr + 8)) & 0xFFFFFFFF
                    ea = f'0x{target:08X}u /* IP-rel */'
                elif mode == 0x7:  # abase + index*scale (4-byte, no disp)
                    if scale_val == 1:
                        ea = f'({abase} + {idx})'
                    else:
                        ea = f'({abase} + ({idx} << {scale_bits}))'
                elif mode == 0xC:  # disp32 (absolute, 8-byte)
                    disp = self.read32(addr + 4)
                    inst_size = 8
                    ea = f'0x{disp:08X}u'
                elif mode == 0xD:  # disp32 + abase (8-byte)
                    disp = self.read32(addr + 4)
                    inst_size = 8
                    if disp == 0:
                        ea = f'{abase}'
                    else:
                        ea = f'({abase} + 0x{disp:08X}u)'
                elif mode == 0xE:  # disp32 + index*scale (8-byte)
                    disp = self.read32(addr + 4)
                    inst_size = 8
                    if scale_val == 1:
                        ea = f'(0x{disp:08X}u + {idx})'
                    else:
                        ea = f'(0x{disp:08X}u + ({idx} << {scale_bits}))'
                elif mode == 0xF:  # disp32 + abase + index*scale (8-byte)
                    disp = self.read32(addr + 4)
                    inst_size = 8
                    if scale_val == 1:
                        ea = f'(0x{disp:08X}u + {abase} + {idx})'
                    else:
                        ea = f'(0x{disp:08X}u + {abase} + ({idx} << {scale_bits}))'
                else:
                    ea = f'0 /* TODO: MEMB mode 0x{mode:X} */'

            # Generate load/store
            if opcode == 0x80:  # ldob
                lines.append(f'{reg} = op_ldob({ea}); /* ldob */')
            elif opcode == 0x82:  # stob
                lines.append(f'op_stob((uint8_t){reg}, {ea}); /* stob */')
            elif opcode == 0x84:  # bx (branch indirect)
                if ea == 'I960_G(14)':
                    # bx (g14) is how a bal-called leaf procedure returns.
                    # bal is lifted as a real call, so plain return is correct.
                    lines.append(f'return; /* bx (g14) - leaf return */')
                else:
                    lines.append(f'/* bx {comment_safe(ea)} - indirect branch */')
                    lines.append(f'func_table_call({ea});')
                    lines.append(f'return;')
            elif opcode == 0x85:  # balx
                lines.append(f'{reg} = 0x{addr + inst_size:08X}; /* balx */')
                lines.append(f'func_table_call({ea});')
            elif opcode == 0x86:  # callx (indirect call)
                lines.append(f'i960_do_call({ea}, 0x{addr + inst_size:08X});')
                lines.append(f'func_table_call({ea}); /* callx */')
            elif opcode == 0x88:  # ldos
                lines.append(f'{reg} = op_ldos({ea}); /* ldos */')
            elif opcode == 0x8A:  # stos
                lines.append(f'op_stos((uint16_t){reg}, {ea}); /* stos */')
            elif opcode == 0x8C:  # lda (load address)
                lines.append(f'{reg} = {ea}; /* lda */')
            elif opcode == 0x90:  # ld
                lines.append(f'{reg} = op_ld({ea}); /* ld */')
            elif opcode == 0x92:  # st
                lines.append(f'op_st({reg}, {ea}); /* st */')
            elif opcode == 0x98:  # ldl
                lines.append(f'op_ldl({ea}, {src_dst_reg}); /* ldl */')
            elif opcode == 0x9A:  # stl
                lines.append(f'op_stl({src_dst_reg}, {ea}); /* stl */')
            elif opcode == 0xA0:  # ldt
                lines.append(f'op_ldt({ea}, {src_dst_reg}); /* ldt */')
            elif opcode == 0xA2:  # stt
                lines.append(f'op_stt({src_dst_reg}, {ea}); /* stt */')
            elif opcode == 0xB0:  # ldq
                lines.append(f'op_ldq({ea}, {src_dst_reg}); /* ldq */')
            elif opcode == 0xB2:  # stq
                lines.append(f'op_stq({src_dst_reg}, {ea}); /* stq */')
            elif opcode == 0xC0:  # ldib
                lines.append(f'{reg} = (uint32_t)op_ldib({ea}); /* ldib */')
            elif opcode == 0xC2:  # stib
                lines.append(f'op_stob((uint8_t){reg}, {ea}); /* stib */')
            elif opcode == 0xC8:  # ldis
                lines.append(f'{reg} = (uint32_t)op_ldis({ea}); /* ldis */')
            elif opcode == 0xCA:  # stis
                lines.append(f'op_stos((uint16_t){reg}, {ea}); /* stis */')
            else:
                lines.append(f'/* TODO: MEM opcode 0x{opcode:02X} ea={comment_safe(ea)} */')
            ret_size = inst_size
            return lines, ret_size

        # Unknown instruction
        lines.append(f'/* UNKNOWN: 0x{word:08X} at 0x{addr:08X} */')
        return lines, ret_size


def interrupt_handlers(data, max_size):
    """Entry points reachable only through the i960 interrupt table.

    An interrupt handler is never called or branched to by any instruction, so
    scanning the code finds nothing. It is reached because the hardware reads
    its address out of the interrupt table, which the boot ROM builds. Walk
    there the way the processor does: SAT+4 gives the PRCB, PRCB+0x14 the
    interrupt table. The table's first nine words are pending state; words 9
    onward hold the handler for vectors 8, 9, 10...

    Without this, Virtua Cop's VBlank handler at 0x720 was never lifted as a
    function - it sat as unreachable trailing code inside its predecessor - and
    the game did no per-frame work at all.
    """
    def rd(addr):
        if addr < 0 or addr + 4 > len(data):
            return 0
        return struct.unpack_from('<I', data, addr)[0]

    prcb = rd(4)
    itab = rd(prcb + 0x14)
    if not itab or itab >= max_size:
        return set()

    handlers = set()
    for word in range(9, 0x400 // 4):
        target = rd(itab + word * 4)
        if 0 < target < max_size:
            handlers.add(target)
    return handlers


def discover_functions(data, max_size):
    """Find all function entry points."""
    from tools.rom_loader import disasm_one
    calls = set()
    post_ret = set()

    offset = 0
    # Set once a ret is seen and cleared by the next real instruction, so that
    # alignment padding between functions is skipped rather than ending the
    # search. Virtua Cop's compiler pads with zero words, and the earlier
    # "the very next word after a ret" rule gave up on the first pad word -
    # which lost every function that is only ever reached through a function
    # pointer, since nothing in the code names its address either. The whole
    # scene renderer hung off one of them.
    after_ret = False
    while offset < max_size:
        text, size, is_call, is_branch, target = disasm_one(data, offset, offset)
        word = struct.unpack_from('<I', data, offset)[0]
        # call (0x09) and bal (0x0B) both name a procedure entry; bal is the
        # leaf-call form used heavily by the Sega runtime library.
        is_entry = is_call or ((word >> 24) & 0xFF) == 0x0B
        if is_entry and target is not None and 0 < target < max_size:
            calls.add(target)

        is_padding = word == 0 or word == 0xFFFFFFFF
        if after_ret and not is_padding:
            post_ret.add(offset)
            after_ret = False
        if ((word >> 24) & 0xFF) == 0x0A:
            after_ret = True
        offset += size

    all_funcs = sorted(calls | post_ret | interrupt_handlers(data, max_size))
    valid = []
    for addr in all_funcs:
        if addr < max_size - 4:
            word = struct.unpack_from('<I', data, addr)[0]
            if word != 0 and word != 0xFFFFFFFF:
                valid.append(addr)
    return valid


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <program.bin> <output_dir>")
        sys.exit(1)

    prog_path = sys.argv[1]
    output_dir = sys.argv[2]
    os.makedirs(output_dir, exist_ok=True)

    with open(prog_path, 'rb') as f:
        data = f.read()

    # Find program end
    prog_end = len(data)
    while prog_end > 0 and (data[prog_end - 1] in (0x00, 0xFF)):
        prog_end -= 1
    prog_end = (prog_end + 3) & ~3

    # Get entry point
    ip = struct.unpack_from('<I', data, 12)[0]
    prcb = struct.unpack_from('<I', data, 4)[0]
    fp = struct.unpack_from('<I', data, prcb + 24)[0]

    print(f'Program size: {prog_end} bytes')
    print(f'Entry point: 0x{ip:08X}')
    print(f'Initial FP: 0x{fp:08X}')

    # Discover functions
    print('Discovering functions...')
    func_addrs = discover_functions(data, prog_end)
    # Add entry point
    if ip not in func_addrs:
        func_addrs.append(ip)
    func_addrs.sort()
    print(f'Found {len(func_addrs)} functions')

    # Lift all functions
    lifter = I960Lifter(data)
    total_lines = 0

    # Determine function boundaries
    func_bounds = {}
    for i, addr in enumerate(func_addrs):
        end = func_addrs[i + 1] if i + 1 < len(func_addrs) else prog_end
        func_bounds[addr] = end

    print('Lifting functions to C...')
    for addr in func_addrs:
        end = func_bounds[addr]
        lines = lifter.lift_function(addr, end)
        total_lines += len(lines)

    print(f'Generated {total_lines} lines of C code')

    # Split into multiple output files (one per ~200 functions)
    FUNCS_PER_FILE = 200
    file_idx = 0
    funcs_in_file = 0
    current_file_lines = []
    all_func_addrs = sorted(lifter.functions.keys())

    # Write header with all declarations
    header_path = os.path.join(output_dir, 'vcop_funcs.h')
    with open(header_path, 'w') as f:
        f.write('/* Auto-generated - Virtua Cop recompiled function declarations */\n')
        f.write('#ifndef VCOP_FUNCS_H\n#define VCOP_FUNCS_H\n\n')
        f.write('#include "vcop/functions.h"\n\n')
        for addr in all_func_addrs:
            f.write(f'void vcop_{addr:08X}(void);\n')
        f.write('\n#endif\n')
    print(f'Wrote {header_path} ({len(all_func_addrs)} declarations)')

    # Write implementation files
    for addr in all_func_addrs:
        if funcs_in_file == 0:
            current_file_lines = []
            current_file_lines.append('/* Auto-generated - Virtua Cop recompiled i960 code */\n')
            current_file_lines.append('#include "vcop/i960_ops.h"\n')
            current_file_lines.append('#include "vcop_funcs.h"\n\n')

        lines = lifter.functions[addr]
        current_file_lines.append(f'/* Function at 0x{addr:08X} */\n')
        current_file_lines.append(f'void vcop_{addr:08X}(void)\n{{\n')
        for line in lines:
            current_file_lines.append(f'{line}\n')
        current_file_lines.append('}\n\n')
        funcs_in_file += 1

        if funcs_in_file >= FUNCS_PER_FILE or addr == all_func_addrs[-1]:
            file_path = os.path.join(output_dir, f'vcop_code_{file_idx:03d}.c')
            with open(file_path, 'w') as f:
                f.writelines(current_file_lines)
            print(f'Wrote {file_path} ({funcs_in_file} functions)')
            file_idx += 1
            funcs_in_file = 0

    # Write registration function
    reg_path = os.path.join(output_dir, 'vcop_register.c')
    with open(reg_path, 'w') as f:
        f.write('/* Auto-generated - Virtua Cop function registration */\n')
        f.write('#include "vcop/functions.h"\n')
        f.write('#include "vcop_funcs.h"\n\n')
        f.write('void vcop_register_all(void)\n{\n')
        for addr in all_func_addrs:
            f.write(f'    func_table_register(0x{addr:08X}, vcop_{addr:08X});\n')
        f.write('}\n')
    print(f'Wrote {reg_path} ({len(all_func_addrs)} registrations)')

    print(f'\nDone! {len(all_func_addrs)} functions lifted to {file_idx} C files')


if __name__ == '__main__':
    main()
