# Boot Sequence

What happens between `vcop.exe` starting and Virtua Cop's `main` taking over,
and the five things that blocked it on the way there.

## The chain

```
  src/main/main.c
       |
       |  model2recomp_init(), model2recomp_load_rom(), vcop_register_all()
       v
  reset at 0x000005D0
       |  relocate PRCB and interrupt table into work RAM
       |  synmovq an IAC "reinitialize processor" message to 0xFF000010
       v
  firmware entry at 0x000006A0          (new PRCB: 0x00501000)
       |
       v
  main at 0x00002370
       |
       +--> never returns. Owns the frame loop, busy-waits on 0x0098000C bit 2.
```

## Reset state

The i960 does not start at a fixed address — it reads an initial memory image
at `0x00000000`. For Virtua Cop:

| | Value |
|---|---|
| SAT (system address table) | `0x00000000` |
| PRCB (process control block) | `0x000000B0` |
| Reset IP | `0x000005D0` |
| Initial FP (`PRCB + 0x18`) | `0x00500C00` |
| Initial SP | `FP + 0x40` = `0x00500C40` |

`src/main/main.c` reads the PRCB for the frame pointer rather than hardcoding
it, then calls the reset routine.

## The IAC handoff

The routine at `0x5D0` is a stub, not the firmware. It:

1. copies a table from `0x00000590` to `0x00E00000` (CPU control / wait states),
2. copies the PRCB from `0x000000B0` to `0x00501000`,
3. copies the interrupt table from `0x00000D00` to `0x005010B0`,
4. builds a message at `0x00000580` and `synmovq`s it to `0xFF000010`.

That message is `[0x93000000, 0, 0x00501000, 0x000006A0]`. Type `0x93` is the
i960's **reinitialize processor** IAC: new PRCB `0x00501000`, new instruction
pointer `0x000006A0`. That is the real firmware entry.

model2recomp models this in `bus_iac_take_reinit()`, so `main.c` *follows* the
chain rather than hardcoding the second entry point:

```c
uint32_t ip = 0x000005D0, prcb = 0x000000B0;
for (int hop = 0; ip && hop < 8; hop++) {
    I960_FP = bus_read32(prcb + 0x18);
    I960_SP = I960_FP + 0x40;
    if (!func_table_call(ip)) break;
    ip = bus_iac_take_reinit(&prcb);   /* 0 once no reinit was issued */
}
```

Two "Booting i960 at ..." lines in the startup output is therefore correct and
expected. A single line means the IAC was not seen, and the game is running
code that was only meant to configure the processor.

## After the handoff

`0x6A0` is the firmware entry. It calls `main` at `0x2370`, which never
returns: Virtua Cop owns its frame loop and busy-waits on bit 2 of the video
status register at `0x0098000C`. Reads of that register are routed to
`model2recomp_field_sync()`, which is where a frame actually happens — see
[model2recomp's execution model](https://github.com/sp00nznet/model2recomp/blob/main/docs/technical/execution-model.md).

The fallback frame loop at the end of `main.c` only runs if init bails out
early and *does* return. If you see "Game returned from main", something went
wrong before the game reached its loop.

## Interrupts

Virtua Cop's interrupt control register is `0x0F0E0D0C`, which maps external
line 0 to vector 12. The handler for vector 12 is at
`interrupt_table + 36 + (12 - 8) * 4`, which for this game resolves to
**`0x00000720`** — the VBlank handler.

That handler is not called or branched to by any instruction anywhere in the
ROM, which is why the lifter has to seed discovery from the interrupt table
(see [lifter.md](lifter.md)).

## Blockers cleared on the way here

In order, because the order is instructive — each one looked like a different
kind of problem than it was.

### 1. `bal` was not treated as a call

`bal` is branch-and-link: a call that returns through `g14`, and the Sega
runtime library uses it heavily for leaf routines. The lifter treated it as a
tail branch, which both **truncated the calling function** at the first `bal`
and **never registered the target** as a function. Symptom: immediate wrong
behaviour everywhere, with no obvious pattern.

### 2. The I/O board had no command handshake

`0x2928` writes the magic string `SEGA` into I/O board DPRAM at `0x34`, raises
command 1 at `0x40`, and spins until the board writes it back to zero. With no
board behind the DPRAM it spun forever. Commands now complete the moment they
are issued, and `0x42` reports "ready" (bit 6). Symptom: a clean hang very
early, before any video.

### 3. `fifo_control_read` had the wrong polarity

MAME returns **1 when the coprocessor output FIFO is empty**. Returning the
opposite deadlocks the game, which polls this before uploading TGP microcode.
Symptom: another clean hang, slightly later.

### 4. The lifter's floating point was garbage

Two separate faults. The REG-format **operand mode bits** were ignored, so
every real-number instruction read `fp[reg & 3]` regardless of whether the
operand was a floating-point register, an ordinary register holding IEEE bits,
or a literal. And several opcode mappings were simply wrong — `0x674` (`cvtir`),
the `0x68x`, `0x6Cx` and `0x6Ex` groups. Rewritten against the opcode table
extracted from MAME's `cpu/i960/i960.cpp`.

Symptom: the game ran. It just drew nonsense. This is the worst failure mode
there is, and it is why the lifter is now written against MAME's table rather
than the manual.

### 5. Interrupt handlers were never discovered

Handlers are not the target of any call or branch, so a scan that looks for
call targets cannot find them. Virtua Cop's VBlank handler at `0x720` sat as
unreachable trailing code inside its predecessor. Symptom: the game booted, the
frame counter advanced, and the game did *nothing* — because its per-frame work
all hangs off VBlank.

The lifter now seeds discovery from the interrupt table the way the processor
reaches it: `SAT + 4` → PRCB → `PRCB + 0x14` → handler per vector.
