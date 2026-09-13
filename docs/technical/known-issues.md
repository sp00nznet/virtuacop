# Known Issues

Three things stand between this and a playable port. The first now has a
root cause; none are solved.

---

## 1. Polygons draw too dark, many fully black

**Symptom.** The scene renders - geometry, textures, perspective, z-sorting all
correct - but most surfaces come out black. Buildings are solid silhouettes.

**Cause: found.** It is not the colour path, the palette upload, or the fade
logic. It is the interrupt frame.

The VBlank handler is dispatched at the field boundary, because recompiled code
has no instruction boundary to interrupt. On real hardware, taking an interrupt
pushes a stack frame and the handler's closing `ret` pops it. Called without
one, that `ret` unwinds a frame nobody pushed - every field. Watch the frame
pointer over a few hundred fields:

```
fp=00500500  fp=005004C0  fp=00500440  fp=00000000  fp=00000100  fp=0A0009C0
```

It leaves work RAM. From then on every frame-relative load in the guest reads
ROM. One of them is in `0x00009700`, which stores a zero to `0x44(fp)` and
reads it straight back to initialise the palette fade counter at `0x0050F364` -
and gets `0x000008A0` out of the i960 interrupt table in ROM instead.

That is a denormal float, so `0x00003BE0` (the fade) treats it as a live fade,
and `0x00003B68` - which turns a fade level into a pointer into the fade LUT -
has no case for the uninitialised selector at `0x0050F360` and returns the
*index* where a pointer should be. The fade then copies 455 u16 from address 1.
The result is visible in a palette dump: the i960 boot header, `0x000000B0` and
`0x000005D0` and all, sitting in the polygon palette.

```
[pal] 1000: 0000 0000 00B0 0000 0000 0000 05D0 0000 F980 FFFF ...
```

Polygons whose colorbase lands in that range select ramp 0 on every channel and
draw black. The ones that survive - grass, sky, road - are the ones whose
palette entries sit above `0x11C1`, where the bogus fade stopped writing.

**Why it is not fixed.** Both faithful models of the interrupt frame - push one
for the handler, or snapshot and restore the whole context - stop the game
submitting *any* display list, permanently, from the first field. It is not
stuck when they are used: it executes more distinct functions than the default
does, so it gets further into its own logic and then fails somewhere else.
`MODEL2_IRQMODE=0|1|2` selects between them, and the default is the one that
draws.

Finding what modes 1 and 2 expose is the next thing to do, and the highest
value work left in the project.

---

## 2. Coins do not become credits

**Symptom.** Input works - a coin or start press reaches the game's own input
word at `0x0050154C` as a clean edge, level then release - but the credit
counter stays at zero.

**What works.** The whole input path. The board's DPRAM is published every
field with the input ports at `0x08`/`0x09`/`0x0A`/`0x11` and the lightgun's
nine bytes at `0x80`, which is the layout the game reads: `0x00001300`
composes the first four into one word and inverts it, `0x000014F0` reads four
little-endian coordinates and a status byte. Mouse: left fires, right fires
off-screen (reload), middle drops a coin. Keyboard: 5 coin, 1 start, 9
service, F2 test.

**What is missing.** The I/O board's **93C46 EEPROM**, which holds coinage and
the game's settings. MAME runs the board's real Z80 firmware and that firmware
reads the EEPROM; model2recomp publishes DPRAM directly and has nothing to put
in the settings area, so the game has no coins-per-credit to apply.

Two ways forward: work out which DPRAM bytes carry the settings block and
publish a sane default, or emulate the board's Z80 (`epr-16891.6` is in the ROM
set) and let the firmware do it. The first is an afternoon; the second is the
honest one.

Worth knowing: the game has been seen to award itself credits, so the path
exists and is gated on something readable rather than absent.

---

## 3. No sound

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
