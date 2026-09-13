# Known Issues

Three things stand between this and a playable port. The first now has a
root cause; none are solved.

---

## 1. Polygons drew too dark — fixed

**Was:** most scenery drew as solid black silhouettes, and the game never got
past its attract loop.

**Cause.** Three bugs, and the middle one was hiding the other two.

1. **A `ret` is not the end of a function.** A conditional branch that skips
   over an early return leaves one in the middle; the code after it is a
   continuation, not an entry point. Discovery split real functions there and
   left paths that fall off the end of their generated C without reaching the
   `ret` that pops the frame.
2. **Switch jump tables were never discovered.** `ld table[gN*4], gM` followed
   by `bx (gM)` dispatches through code addresses nothing else names, so the
   dispatch missed, the switch did nothing, and the caller's frame leaked.
3. **The interrupt frame was unbalanced the other way.** The VBlank handler was
   dispatched without the frame the hardware pushes, so its `ret` unwound one
   too far - which cancelled the two leaks above and hid them, while walking
   the frame pointer down out of work RAM instead.

With the frame pointer in ROM, `0x00009700` stored a zero to `0x44(fp)` and
read back `0x000008A0` out of the i960 interrupt table. That denormal looked
like a live palette fade; `0x00003B68` had no case for the uninitialised
selector at `0x0050F360` and returned an index where a pointer belongs; and the
fade copied 455 words from address 1 — the i960 boot header — into the polygon
palette.

```
[pal] 1000: 0000 0000 00B0 0000 0000 0000 05D0 0000 F980 FFFF ...
```

**The trap was that fixing any one of the three alone made things worse**, which
is why the interrupt frame looked for a long time like a change that broke
rendering. Two errors were cancelling. Fixed together:

![Virtua Cop's attract demo](../attract_wharf.png)

Function count went 2,095 → 1,559 with the first rule, then → 1,747 with the
jump tables. Both live in [lifter.md](lifter.md).

---

## 2. The 3D does not finish drawing past the stage select

**Symptom.** Attract renders in full colour. Start reaches the stage select,
and from there on the HUD draws over a flat light grey.

**What the grey is.** Not the front tilemap pass, which draws nothing at all on
that screen — it is tilemaps 3 and 2 in the *back* pass, filling the screen with
palette word `0x8000`. That is a legitimate clear: `0x8000` selects ramp 0 on
every channel, and ramp 0 at the tilemap's fixed luma index reads about `0xFA`,
which gamma turns into the 248 grey you see. The back tilemap is supposed to be
covered by the 3D.

**What the 3D does.** It draws, but only about 48,000 of the screen's 190,464
pixels, so most of the clear survives. The polygons it does draw have sane
shading — `MODEL2_SHADE` shows proper palette entries, luma RAM and ramps,
identical in kind to the attract scene that renders correctly — and their
vertices are in normal ranges. So this is not the colour path and not the fill;
the scene is simply incomplete.

**The likely reason: the guest stack again.** In-game, `MODEL2_LEAK` still names
three functions — `0x0001C8D0`, `0x0000A500`, `0x00027860` — and the frame
pointer leaves work RAM shortly after a game starts. `0x0001C8D0` is the jump
table dispatcher: its targets *are* registered as functions, so `bx (g4)`
dispatches into one, that one returns with `ret`, and the dispatcher's own
fall-through path never reaches a `ret` of its own.

**Two fixes tried, both worse, both instructive:**

- **Treating jump-table targets as labels** (like branch targets) fixes
  `0x00074E20` — the printf routine, whose table entry `0x00074E4C` was
  truncating it — but breaks `0x0001C8D0`, whose targets then miss entirely.
  1,747 → 1,508 functions, and the game stops reaching the stage select.
- **Extending a function's extent to cover its own branch and jump targets**,
  so the targets can be labels *and* be inside the function. This regressed
  further: the game stalls on the Sega warning screen and the in-game polygon
  count falls to 1.

The shape of the right answer is clear — a jump-table target is a label inside
its dispatcher, and the dispatcher has to be lifted far enough to contain it —
but the extent calculation needs to be right about where functions actually end
rather than guessing, and guessing worse than the current guess makes things
worse. That is the next piece of work.

---

## 3. Coins do not become credits

The board defaults to **free play** without its settings EEPROM, so the game
starts on Start alone and never needs a credit. Input itself works end to end:
coin, start, service and test all reach the game's own input word at
`0x0050154C` as clean edges, and the mouse aims and fires.

What is missing is the I/O board's 93C46, which holds coinage and the game's
settings. MAME runs the board's real Z80 firmware and that firmware reads the
EEPROM; model2recomp publishes DPRAM directly and has nothing to put in the
settings area.

---

## 4. No sound

**Symptom.** Silence.

**Cause.** model2recomp's `src/sound.c` answers the UART handshake so the game
does not wait on it, and nothing else. The sound board is a 68000 at 10 MHz
with a YM3438 and two MultiPCM chips, on the other side of that UART.
`roms/sound_program.bin`, `samples1.bin` and `samples2.bin` are extracted and
unused.

This is a large job and it belongs in model2recomp rather than here — it is the
board, not the game.

---

## Smaller things

- **Texture filtering.** Point sampling only. No bilinear, no mipmaps, no
  microtexture blending. Texture LOD is computed per polygon and then not used.
  Lives in model2recomp.
- **Performance.** A few frames per second in busy scenes. The rasterizer is a
  straightforward barycentric fill over each triangle's bounding box with no
  optimisation. The coprocessor is *not* the bottleneck — about 5,800 DSP
  instructions per field.
- **Non-determinism.** The field boundary is driven by wall-clock time, so two
  runs stopped at the same field number can be in different parts of the
  attract sequence. This makes A/B comparison across runs unreliable; sample
  with `MODEL2_SHOT_EVERY` instead.
- **212 unimplemented REG opcodes** in the lifted output. Only four are inside
  functions that execute, and those are `flushreg` plus three in misdecoded
  data. See [lifter.md](lifter.md).
