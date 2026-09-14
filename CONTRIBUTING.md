# Contributing

## Before anything else

**No ROM data, and nothing derived from it.** `roms/`, `*.zip`, `*.bin` and
`src/recomp/` are gitignored. The lifter ships; its output never does. A patch
that adds generated C, a disassembly listing, a symbol map reconstructed from
the binary, or a test fixture embedding any of those cannot be merged, however
small.

Screenshots are fine — showing what the project renders is the point.

## What is useful

The honest answer is that the geometry is wrong and we do not yet know which
stage breaks it. `docs/technical/known-issues.md` is kept current with what has
been measured and, as importantly, what has been ruled out. Work that narrows
the search is worth more than work that adds features.

Board-level changes — the geometry engine, rasterizer, tilemaps, coprocessor —
belong in [model2recomp](https://github.com/sp00nznet/model2recomp). The test
is whether the sentence would still be true of Daytona USA.

## Measure before claiming

The flat-scene bug was attributed to the recompiled floating point for two
commits. It was a stubbed coprocessor. Say what you measured and how you
measured it; "this looks right" has been wrong here more than once.

`tools/mame/` runs the game under MAME and diffs our display list and
framebuffer against it frame by frame. If a change is meant to fix rendering,
that number should move.

## Ported from MAME

Both repositories are MIT with a `NOTICE` mapping MAME-derived files back to
their source and copyright. Attribution is a licence obligation: if you port
something new from MAME, update `NOTICE` in the same commit.

## Commits

Imperative-mood subjects that say what changed and, in the body, why. No `wip`
or `fix` on `main`. Feature branches for anything nontrivial.

Build and run before opening a PR:

```bash
cmake -B build -DCMAKE_TOOLCHAIN_FILE=C:/vcpkg/scripts/buildsystems/vcpkg.cmake \
               -DVCPKG_TARGET_TRIPLET=x64-windows
cmake --build build --config Release
VCOP_MAX_FRAMES=2000 MODEL2_SCREENSHOT=out.ppm ./build/Release/vcop.exe ./roms
```

Attract mode is not deterministic across runs — it is wall-clock driven — so
sample with `MODEL2_SHOT_EVERY=100` rather than comparing single frames.
