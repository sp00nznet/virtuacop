# Roadmap

## Now

**The geometry is wrong and the CPU is not why.** Our display list matches
MAME's to 32,765 of 32,768 dwords, so the recompiled i960 is producing very
nearly the right commands — the fault is in how `model2recomp` turns them into
pixels. The MAME harness (`tools/mame/`) gives a reference frame to diff
against; the next step is finding which pipeline stage first disagrees, one
stage at a time, rather than reasoning about the rendering as a whole.

## Next

- **Sound.** The Model 2 sound board is a 68000 with a SCSP. It belongs in
  `model2recomp`, not here.
- **Revision A.** The lifter works from whichever program ROM the dump
  contains, but the two revisions differ in two chips, so nothing about
  Revision B's addresses carries over. Untested.
- **A conformance number in the README.** The MAME harness reports per-frame
  pixel disagreement; that figure should be tracked over time and fail CI on
  regression, per the house style.

## Deferred

- **Linux and macOS.** The runtime is SDL and the lifted C is portable; nothing
  is known to block it, but nothing has been tried either.
- **Performance.** Roughly 22% of real speed. The dispatch table is the obvious
  suspect, but correctness comes first — optimising a wrong renderer wastes the
  measurement.

## Out of scope

- **Distributing anything derived from the ROM.** The lifter ships; its output
  does not. You supply your own dump.
- **A general Model 2 frontend.** Board-level work belongs in `model2recomp`;
  this repository is Virtua Cop and the ways it is peculiar.
- **Dynamic recompilation.** This is a static recompiler. If a game needs a JIT,
  it needs an emulator, and MAME is already excellent at being one.
