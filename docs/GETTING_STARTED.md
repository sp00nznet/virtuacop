# Getting Started

You have a Virtua Cop ROM dump and you want the picture in the README on your
own screen. This is how, start to finish, with what to expect at each step.

## What you need

| | |
|---|---|
| **Windows 10/11** | MSVC is the tested compiler. Linux and macOS should work — SDL2 is the only platform dependency — but nobody has tried. |
| **Visual Studio 2022** | With the "Desktop development with C++" workload |
| **CMake ≥ 3.20** | Ships with VS 2022, or install separately |
| **vcpkg** | So `find_package(SDL2)` resolves. `vcpkg install sdl2:x64-windows` |
| **Python 3.10+** | For the ROM and lifting tools. No third-party packages needed. |
| **A Virtua Cop ROM set** | MAME `vcop` (Revision B) or `vcopa` (Revision A). **You must dump or own this.** Nothing here distributes it. |

Optional but genuinely useful:

- **MAME** with the same ROM set, to see what the game is supposed to look like.

## Step 1: Clone

```bash
git clone --recurse-submodules https://github.com/sp00nznet/virtuacop.git
cd virtuacop
```

The `--recurse-submodules` matters:
[model2recomp](https://github.com/sp00nznet/model2recomp) — the Model 2 board —
is a submodule at `ext/model2recomp`. If you forgot:

```bash
git submodule update --init
```

## Step 2: Turn your ROM set into flat images

Model 2 ROMs are 16-bit halves interleaved into 32-bit words. The runtime does
not read ROM sets; it reads flat, region-sized binary images. Put your `vcop.zip`
in the repository root and:

```bash
python tools/rom_loader.py vcop.zip roms
```

That writes into `roms/`:

| File | Size | What |
|---|---|---|
| `program.bin` | 2 MB | The i960 program — what gets recompiled |
| `data.bin` | 32 MB | Game data |
| `polygons.bin` | 16 MB | 3D models |
| `textures.bin` | 16 MB | Texture sheets |
| `copro_tables.bin` | 256 KB | Coprocessor sin/cos, atan, 1/x, 1/√x tables |
| `sound_program.bin` | 768 KB | 68000 program (unused — sound is a stub) |
| `samples1.bin`, `samples2.bin` | 4 MB each | MultiPCM samples (unused) |
| `disasm.txt` | — | Full i960 disassembly, for reference |
| `functions.txt` | — | Every discovered function entry point |

It also prints a summary of what it found. If it cannot find a ROM by name it
says so rather than silently writing zeros — a set with renamed files needs the
table at the top of `rom_loader.py` adjusted.

The images are **region-sized, not data-sized**: a 16 MB region holding 4 MB of
real data is a 16 MB file. This is deliberate. Masking to the data extent
instead folds high addresses back onto real geometry and produces vertices with
nonsense z values.

`roms/` is git-ignored. Nothing you produce here should ever be committed.

### Revision A

`tools/rom_loader.py` takes whichever of the two program ROM revisions the ZIP
actually contains, so `vcopa.zip` works the same way. The committed C in
`src/recomp/` was generated from **Revision B**, so a Revision A dump needs
step 3 — the two revisions differ in two chips and the addresses do not line
up.

## Step 3 (optional): Regenerate the recompiled C

`src/recomp/` is already committed — 1,747 functions, about 120,000 lines of
generated C across 9 files — so you can skip straight to building. Regenerate only if you
changed the lifter or you are on Revision A:

```bash
python -m tools.i960_lifter roms/program.bin src/recomp
```

Run it from the repository root (it imports `tools.rom_loader` for the
disassembler). It takes a few seconds and prints what it found:

```
Program size: 484228 bytes
Entry point: 0x000005D0
Initial FP: 0x00500C00
Discovering functions...
Found 1747 functions
Lifting functions to C...
Generated 109020 lines of C code
```

How it works, and what it gets wrong, is in
[technical/lifter.md](technical/lifter.md).

## Step 4: Build

```bash
cmake -B build -DCMAKE_TOOLCHAIN_FILE=C:/vcpkg/scripts/buildsystems/vcpkg.cmake \
               -DVCPKG_TARGET_TRIPLET=x64-windows
cmake --build build --config Release
```

Adjust the toolchain path to your vcpkg. On Linux or macOS, with SDL2 installed
from your package manager, plain `cmake -B build && cmake --build build` is
enough.

This builds three things: `model2recomp` (the board), `vcop_game` (the
recompiled i960 code), and `vcop.exe` (the launcher that ties them together).
Expect it to take a couple of minutes — 118,000 lines of generated C is a lot
of `switch` statements.

## Step 5: Run

```bash
./build/Release/vcop.exe ./roms
```

A 496×384 window at 2× scale opens. Boot output looks like:

```
=== Virtua Cop - Static Recompilation ===
Sega Model 2 (1994)

[bus] Memory bus initialized
[video] Initialized (496x384)
[geo] Geometry engine initialized
...
[bus] Program ROM loaded: 2097152 bytes @ 0x00000000
[copro] TGP math tables loaded: 65536 entries
Booting i960 at 0x000005D0 (PRCB 0x000000B0, FP 0x00500C00)...
  routine returned.
Booting i960 at 0x000006A0 (PRCB 0x00501000, FP 0x00500C00)...
[geo] Bound polygon and texture ROMs
[copro] Booting TGP, 2024 dwords of microcode
```

Two boot lines is correct — the reset stub hands over to the real firmware
entry through an IAC message. See
[technical/boot-sequence.md](technical/boot-sequence.md).

**The screen stays black for about 20 seconds of game time.** The game runs its
self-test and I/O initialisation before attract mode starts drawing. That is
normal, and it is why every bounded test below uses a large frame count.

### Bounded runs

The game never returns from `main`, so there is no natural place to stop. Cap it:

```bash
# 2000 fields, then exit cleanly and write the last frame
VCOP_MAX_FRAMES=2000 MODEL2_SCREENSHOT=out.ppm ./build/Release/vcop.exe ./roms

# sample the whole attract cycle: out.00000.ppm, out.00100.ppm, ...
VCOP_MAX_FRAMES=3000 MODEL2_SHOT_EVERY=100 MODEL2_SCREENSHOT=out \
    ./build/Release/vcop.exe ./roms
```

PPM is a plain RGB format that any image tool reads; `python -c "from PIL
import Image; Image.open('out.ppm').save('out.png')"` if you want a PNG.

**The attract sequence is not deterministic across runs.** The field boundary
is driven by wall-clock time, so two runs stopped at the same field number can
be in different scenes. Sample rather than trusting a single frame.

### Environment variables

| Variable | What |
|---|---|
| `VCOP_MAX_FRAMES=N` | Stop after N fields and exit 0 |
| `MODEL2_SCREENSHOT=path` | Write the final frame as a PPM |
| `MODEL2_SHOT_EVERY=N` | Also write `path.<field>.ppm` every N fields |
| `MODEL2_TRACE=N` | Print the first N function dispatches, indented by call depth |
| `MODEL2_INPUT=coin1,start1` | Drive buttons headlessly; each is pulsed, so edge-triggered inputs register |
| `MODEL2_POLYCOUNT=N` | Report the geometry engine's polygon count every N fields |
| `MODEL2_WATCH=0xADDR` | Print every 32-bit write to that address, with the guest function doing it |

## What you will and will not see

**You will see:** the attract sequence — stage geometry with textures,
perspective-correct mapping, z-sorting, the sky and ground, and the tilemap HUD
with "CREDIT 0" over the top.

**You will not see:** the 3D past the stage select. Attract renders in full
colour; once a game starts, the HUD draws over a white screen. That is the open
bug in [technical/known-issues.md](technical/known-issues.md).

**Controls:** the mouse is player 1's lightgun. Left button fires, right button
fires off-screen (which is how this game reloads), middle button drops a coin.
Keyboard: 5 coin, 1 start, 9 service, F2 test.

**You can start a game**, and the mouse aims and fires — but the 3D does not
draw once you are past the stage select, and there is no sound. The board
defaults to free play, because its settings EEPROM is not modelled.

## Troubleshooting

**`Could not find a package configuration file provided by "SDL2"`**
vcpkg toolchain path wrong, or SDL2 not installed for the triplet. Check
`vcpkg list | grep sdl2`.

**`MISSING REQUIRED ROM file: ./roms/program.bin`**
Step 2 did not run, or you pointed the executable at the wrong directory. The
argument is the directory, not a file.

**Black screen forever, no crash**
Let it run to 2000 fields first — 20 seconds of game time is longer than it
feels. If it is still black, `MODEL2_TRACE=200` and look at the last line: that
names the function the game is spinning in. The
[model2recomp debugging guide](https://github.com/sp00nznet/model2recomp/blob/main/docs/technical/debugging.md)
covers what each common spin means.

**`[func_table] MISS: no function at 0x...`**
Mostly harmless. `bx (gN)` leaf returns through a saved `g14` look like
indirect branches to non-function addresses; a miss returns to the caller,
which is correct. The log is capped at 20 lines.

**It runs at a few frames per second in busy scenes**
Expected. The rasterizer is a straightforward barycentric fill with no
optimisation. The coprocessor is not the bottleneck — it costs about 5,800 DSP
instructions per field.

## Where to go next

- [Boot Sequence](technical/boot-sequence.md) — what happens between power-on
  and `main`
- [The Lifter](technical/lifter.md) — how the i960 code becomes C
- [Known Issues](technical/known-issues.md) — what is broken and what is known
  about it
- [model2recomp docs](https://github.com/sp00nznet/model2recomp/tree/main/docs)
  — the board itself: memory map, graphics pipeline, coprocessor, execution
  model
