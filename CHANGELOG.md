# Changelog

Follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Nothing is released yet: the game boots, plays and draws, but the 3D geometry
is visibly wrong, so there is no version worth tagging. Everything below is
unreleased.

## [Unreleased]

### Added

- i960KB lifter (`tools/i960_lifter.py`): recursive function discovery from the
  reset vector, switch-table harvesting, and translation to C against
  `model2recomp`'s runtime. 1,747 functions across the 2MB program ROM.
- ROM loader (`tools/rom_loader.py`): a Model 2 ROM set to the flat images the
  runtime maps, plus a standalone i960 disassembler used by the lifter and for
  reading the game by hand.
- A decode cross-check against IDA (`tools/check_decode_vs_ida.py`), which loads
  the flat program ROM through a synthesised ELF wrapper (`EM_960`) because
  idalib will not take a headerless i960 image.
- A differential harness against MAME (`tools/mame/`): a Lua script that dumps
  MAME's display list and framebuffer per frame, and a diff that aligns our
  frames against MAME's and reports per-frame pixel disagreement.
- Mouse input: left button fires, right fires off-screen to reload, middle
  inserts a credit.

### Fixed

- Boot, in five stages — MEM addressing modes, REG opcode mapping, the `g14 = 0`
  invariant after `bal`, register-frame handling on a branch with nowhere to
  land, and function discovery past alignment padding.
- `ret` was treated as the end of a function, which truncated bodies and left
  scenery black; a function ends where discovery says it ends.
- A `switch` dispatched through `bx` was being discovered as a dozen separate
  functions.
- The COBR `test` family (0x20-0x27) was not emitted at all — 460 instructions.
  The compiler uses `testl`/`subo`/`and` as a branchless select, so dropping it
  silently corrupted conditionals rather than crashing.
- The disassembler named a dozen REG opcodes wrongly and read bit 5 rather than
  bit 11 as the src1 literal flag. Replaced the table with MAME's.
- `shrdi` (rounding signed shift) was emitted as a plain shift.
- Stale generated files from a previous, larger lifter run were still matched by
  the CMake glob, so every function was defined twice and every measurement
  taken against the run was meaningless.
- Guest stack leaks: leaks are now 0 with a 0x00500C80 high-water mark.

### Known issues

The 3D scene draws but is wrong — walls render as triangles, flat surfaces as
slabs, and bodies have gaps. The CPU is not the cause: the display list our
recompiled code produces matches MAME's 32,765 of 32,768 dwords. See
`docs/technical/known-issues.md`.
