# Known Issues

Three things stand between this and a playable port. The first now has a
root cause; none are solved.

---

## 1. Polygons draw too dark (mostly fixed)

**Was:** most scenery drew as solid black silhouettes.

**Cause, in full.** Three bugs in a chain, and the middle one was hiding the
other two.

1. **Function discovery treated a `ret` as the end of a function.** A
   conditional branch that skips over an early return leaves a `ret` in the
   middle of a function; the code after it is a continuation, not an entry
   point. Splitting there cut real functions in half - most visibly the printf
   routine at `0x00074E20` - and left paths that fall off the end of their
   generated C without reaching the `ret` that pops the frame.
2. **Every such path leaked a stack frame**, about one per field. The guest
   stack climbed sixty bytes a field.
3. **The interrupt frame was unbalanced in the other direction.** The VBlank
   handler is dispatched at the field boundary without the frame the hardware
   pushes, so its `ret` unwinds one too far - which happened to cancel the leak
   and hide it, while walking the frame pointer down out of work RAM instead.

With the frame pointer in ROM, `0x00009700` stored a zero to `0x44(fp)` and
read back `0x000008A0` out of the i960 interrupt table. That denormal looked
like a live palette fade; `0x00003B68` had no case for the uninitialised
selector at `0x0050F360` and returned an index where a pointer belongs; and the
fade copied 455 words from address 1 - the i960 boot header - straight into the
polygon palette.

```
[pal] 1000: 0000 0000 00B0 0000 0000 0000 05D0 0000 F980 FFFF ...
```

**Fixed** by the discovery rule in [lifter.md](lifter.md): a post-`ret` address
that something *branches* to is a label, not a function. The leak is gone, the
stack high-water is back inside work RAM, the fade counter reads zero, and the
scenery has its colours:

![Attract mode with the palette intact](../attract_containers.png)

**Still open.** Some surfaces remain dark, and the faithful interrupt models
(`MODEL2_IRQMODE=1` or `2`) now get much further than they used to - far enough
to show the Sega warning screen correctly - but stall there instead of
continuing into the attract demo. The default mode reaches attract, so it is
still the default.

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
