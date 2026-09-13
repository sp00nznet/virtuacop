# Known Issues

Three things stand between this and a playable port. All are well characterised;
none are solved.

---

## 1. Polygons draw too dark, many fully black

**Symptom.** The scene renders — geometry, textures, perspective, z-sorting all
correct — but most surfaces come out black. Buildings are solid silhouettes.
Only the brightest surfaces (grass, sky, road) have colour, and even those look
dim.

**The colour path is not the problem.** It matches MAME line for line:

```
polygon texheader[3] -> colorbase (10 bits)
                     -> palram[0x1000 + colorbase]        15-bit, 5 bits/channel
                     -> one of 32 ramps per channel in colour-translate RAM
                     -> indexed by luma (6 bits)
                     -> gamma
```

**What differs is the data.** Palette RAM in the polygon range
`0x1000`–`0x13FF` is largely zero in the affected scenes, so those polygons
select ramp 0 for all three channels and resolve to black. A polygon with
`colorbase = 0x026` reads `palram[0x1026]`, which is `0x0000`.

### What is known

Two functions write that range:

| Function | Writes | What it is |
|---|---|---|
| `0x000029B0` | all 1,024 entries, `0x1000`–`0x13FF` | the scene's full polygon palette, once per scene |
| `0x00003BE0` | 455 entries, `0x1000`–`0x11C1` | a **palette fade** |

`0x3BE0` is the suspect. It copies 455 `u16` entries out of a fade lookup table
the game builds in work RAM at `0x00501710`, `index * 0x38E` bytes in:

```
index   = 30 - counter          counter is the float at 0x0050F364
source  = 0x00501710 + index * 0x38E     (or 0x005081C0, chosen by 0x0050F360)
dest    = 0x01802000             palette RAM, polygon range
```

In a 2,600-field capture it ran **twice** — counter `1` then `0` — writing a
nearly-black level and then a dim one, and then stopped. The palette is left
part-way through a fade-in that never completes.

Two candidate explanations, neither confirmed:

- **The fade is not being stepped.** Something should call `0x3BE0` once per
  field until the counter reaches 0; it is being called twice in 43 seconds.
- **The completion path does nothing.** `0x3BE0` opens with
  `cmpr g5, 0.0` / `be 0x3D44`. `0x3D44` is a small state machine on
  `0x0050F35C` that dispatches to `0x3D78`, `0x3D9C`, `0x3DE4`, `0x3E2C` or
  `0x3E68`. One of those should install the fully-lit palette. If the state
  machine picks the wrong arm — or the lifted `cmpr`/`be` pair does not branch
  when it should — the palette stays dim.

### Ruled out by measurement

- **The rasterizer.** Textures sample correctly; bright texels show through on
  black surfaces, which means the texel fetch and luma path work and only the
  base colour is wrong.
- **Palette writes being lost.** `bus_write16` does a read-modify-write through
  `bus_write32`, which makes a 16-bit store show up as two `palette_write`
  calls. That looks like a duplicate write in a trace and is not one.
- **Lighting.** Polygon luma values across a frame are varied and plausible
  (0, 64, 80, 200, 255), and the lighting code matches MAME's
  `geo_parse_np_ns` exactly.

### Where to start

Trace calls to `0x00003BE0` per field, and read `0x0050F35C` (the fade state)
and `0x0050F364` (the counter) alongside. If the counter is not being stepped
every field, find the caller. If it is, the bug is in the completion arm.

---

## 2. Input does not reach the game

**Symptom.** No button does anything, including inserting a coin. `MODEL2_HOLD`
is inert.

**Cause.** Two halves that were never joined. model2recomp's platform layer
collects keyboard and mouse state and calls `io_set_input()` and
`io_set_lightgun()`, which store it in `s_input_ports` and `s_lightgun`. The
game reads its inputs out of **I/O board dual-port RAM** — Virtua Cop composes
one word from DPRAM offsets `0x10`, `0x12`, `0x14` and `0x22` and inverts it,
around `0x0000BC00`. Nothing copies the stored state into DPRAM.

**Why it is the highest-value fix.** Everything else about the port works well
enough to look at; this is what stands between it and being usable. The change
is small and the test is obvious: press a key, watch the credit counter.

The I/O board is a Model 1 I/O Board 2 (837-11694) — MAME's `model1io2.cpp`
describes the DPRAM layout, including where the lightgun FPGA reports
coordinates.

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
