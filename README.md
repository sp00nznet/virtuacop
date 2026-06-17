# Virtua Cop — Static Recompilation

Static recompilation of **Virtua Cop** (Sega, 1994), a Sega Model 2 arcade lightgun
game. The i960KB main CPU program is lifted from machine code to native C and run
against [`model2recomp`](https://github.com/sp00nznet/model2recomp), a Model 2
hardware runtime library.

> Status: **builds and boots.** The recompiled i960 reset/init routine executes
> against the emulated Model 2 bus and returns; the host then drives the
> model2recomp frame loop. Rendering, sound, and the per-frame game loop are not
> yet wired up — see [Status](#status).

## Hardware

| Subsystem | Detail | In this project |
|-----------|--------|-----------------|
| CPU       | Intel i960KB @ 25 MHz | **Recompiled to C** (target) |
| Geometry  | 5× Fujitsu MB86234 TGP DSPs | Stub |
| Sound     | 68000 @ 10 MHz + YM3438 + 2× MultiPCM | Stub |
| Video     | Custom Sega/Lockheed-Martin rasterizer + System 24 tilemaps | Stub |
| I/O       | Model 1 I/O Board 2 (837-11694) with lightgun FPGA | Basic |

## Layout

- `ext/model2recomp/` — Model 2 hardware runtime library (git submodule)
- `include/vcop/` — game-specific headers (`functions.h`, `i960_ops.h`)
- `src/main/main.c` — entry point, i960 boot, and frame loop
- `src/recomp/` — recompiled i960 functions (generated; 1,493 functions, ~108K lines)
- `tools/rom_loader.py` — extracts MAME ZIP ROMs, interleaves 32-bit word pairs,
  emits flat binaries + disassembly
- `tools/i960_lifter.py` — static recompiler: lifts i960 machine code to C using
  the `i960_ops.h` macros

## Build

Requires CMake ≥ 3.20, a C17 compiler (MSVC tested), and SDL2.

```bash
git clone --recurse-submodules https://github.com/sp00nznet/virtuacop.git
cd virtuacop

# Windows / vcpkg (so find_package(SDL2) resolves):
cmake -B build -DCMAKE_TOOLCHAIN_FILE=C:/vcpkg/scripts/buildsystems/vcpkg.cmake \
               -DVCPKG_TARGET_TRIPLET=x64-windows
cmake --build build --config Release
```

Already cloned without `--recurse-submodules`? Run `git submodule update --init`.

## ROMs

Not distributed. Use the MAME `vcop` (Rev B) / `vcopa` (Rev A) set
(Game ID 833-11127, ROM board 834-11128). Generate the flat binaries the runtime
loads:

```bash
python tools/rom_loader.py vcop.zip roms
```

This produces `roms/program.bin`, `data.bin`, `polygons.bin`, `textures.bin`,
`samples*.bin`, `sound_program.bin`, plus `disasm.txt` / `functions.txt`.

Regenerate the recompiled C from the program ROM (run from the repo root):

```bash
python -m tools.i960_lifter roms/program.bin src/recomp
```

## Run

```bash
./build/Release/vcop.exe ./roms              # run until the window is closed
VCOP_MAX_FRAMES=120 ./build/Release/vcop.exe ./roms   # bounded boot test, exits 0
```

Expected boot output: model2recomp init → all three ROM images loaded into the bus
→ `Entry routine returned (i960 reset/init complete)` → frame loop.

## i960 boot sequence

| | |
|---|---|
| SAT (System Address Table) | `0x00000000` |
| PRCB (Process Control Block) | `0x000000B0` |
| Entry point (IP) | `0x000005D0` |
| Initial FP | `0x00500C00` |
| Initial SP | `0x00500C40` |

## Status

- [x] Project structure
- [x] model2recomp hardware library (subsystem stubs)
- [x] ROM loading/parsing (`tools/rom_loader.py`)
- [x] i960 disassembly + function discovery (1,493 functions)
- [x] Static recompilation (i960 → C lifting)
- [x] C ROM loader in model2recomp (flat binaries → bus memory)
- [x] Compiles (MSVC) and links against model2recomp + SDL2
- [x] First boot test: reset/init runs against the bus and returns; host drives
      the model2recomp frame loop (VBlank + present)
- [ ] Identify and dispatch the per-frame game main loop / VBlank handler
- [ ] TGP geometry coprocessor emulation
- [ ] 3D rasterizer (port from MAME `model2_v.cpp`)
- [ ] Sound subsystem (68000 + MultiPCM)
- [ ] System 24 tilemap rendering

## License / disclaimer

Recompilation and tooling only. No copyrighted ROM data is included. Provide your
own legally dumped ROMs.
