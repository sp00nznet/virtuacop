# The i960 Lifter

`tools/i960_lifter.py` turns Virtua Cop's i960 program ROM into C. It is about
800 lines and there is nothing clever in it — which is the point. What matters
is getting the instruction decode exactly right, because every mistake there
produces a program that *runs* and quietly computes the wrong thing.

```bash
python -m tools.i960_lifter roms/program.bin src/recomp
```

Run it from the repository root; it imports `tools.rom_loader` for the
disassembler.

## Output

| File | What |
|---|---|
| `src/recomp/vcop_code_000.c` … `_010.c` | The lifted functions, 200 per file |
| `src/recomp/vcop_funcs.h` | One declaration per function |
| `src/recomp/vcop_register.c` | `vcop_register_all()` — 2,095 `func_table_register` calls |

Each i960 function becomes a C function named for its address:

```c
/* Function at 0x0000B8FC */
void vcop_0000B8FC(void)
{
    I960_R(8) = 0x005158E0u;                    /* lda */
    I960_R(10) = I960_R(8) + 8;                 /* addo */
L_0000B928: ;
    I960_G(0) = I960_R(8);                      /* mov */
    i960_do_call(0x0000B7F0, 0x0000B930);
    func_table_call(0x0000B7F0);                /* call */
    op_st(I960_G(0), (I960_R(9) + 0x005158F4u));/* st */
    op_cmpi((int32_t)0, (int32_t)I960_G(0));
    if (i960_test_cc(COND_E)) goto L_0000BA50;  /* cmpibe */
    ...
    i960_do_ret();                              /* ret */
    return;
}
```

There is no local state. Every register is a slot in the global `g_i960`
context, reached through the `I960_R` / `I960_G` macros, so a function called
from anywhere sees the register file the caller left behind — exactly as the
hardware does. Branches inside a function become `goto`; calls become
`func_table_call`.

The operation macros live in [`include/vcop/i960_ops.h`](../../include/vcop/i960_ops.h)
— loads and stores go through the model2recomp bus, arithmetic is plain C,
compares set the i960 condition code.

## Finding functions

Three sources, and you need all three. `discover_functions()` unions them.

### 1. Call targets

Every `call` (opcode `0x09`) **and every `bal` (opcode `0x0B`)**. `bal` is
branch-and-link — a call that returns through `g14` — and the Sega runtime
library uses it constantly for leaf routines. Treating it as a plain branch
truncates the caller at the first one.

### 2. Post-return prologues

Code following a `ret` that looks like a function start. The subtlety:

```python
after_ret = False
while offset < max_size:
    ...
    is_padding = word == 0 or word == 0xFFFFFFFF
    if after_ret and not is_padding:
        post_ret.add(offset)
        after_ret = False
    if opcode == 0x0A:          # ret
        after_ret = True
```

The flag survives **alignment padding**. The original rule — "the very next
word after a `ret`" — gave up on the first zero pad word, which lost every
function that is only ever reached through a function pointer, since nothing in
the code names its address either. Virtua Cop's entire scene renderer hung off
one of those.

### 3. The interrupt table

Handlers are never the target of any instruction. Follow the processor's own
path:

```
SAT + 4  ->  PRCB  ->  PRCB + 0x14  ->  interrupt table  ->  handler per vector
```

Without this the VBlank handler at `0x720` is invisible, the game does no
per-frame work, and everything looks like it boots fine.

Finally, any candidate whose first word is `0x00000000` or `0xFFFFFFFF` is
dropped — that is padding, not code.

**A `ret` is not always the end of a function**, and assuming it is cost more
than anything else in this project. A conditional branch that skips over an
early return leaves a `ret` in the middle, and the code after it is a
*continuation* — reached by that branch, part of the same function.

Taking it for an entry point cuts the function in half. The second half gets
its own C function; the path through it falls off the end without ever reaching
the `ret` that pops the frame; and the stack it took is never given back. One
leaked frame per field is enough for the guest stack to climb into the
relocated PRCB within a minute, and from there into the game's own variables.
It is what made most of Virtua Cop's scenery draw black.

The rule that fixes it is a one-liner and reads as obviously true once seen:

```python
# A branch names a label. A call names a function.
post_ret -= branch_targets - calls
```

`0x00074E58` is a `ret` inside the printf routine, and `0x00074E5C` after it is
the target of a `cmpibne` a few instructions earlier. It is a label. Applying
the rule dropped the function count from 2,095 to 1,559 — those 536 were all
pieces of functions that had been sawn in half.

### 4. Switch jump tables

```
ld   0x0001C918[g4*4], g4
bx   (g4)
```

The entries are code addresses and **nothing else in the program names them**:
no call, no branch, no relocation. Without harvesting the table they are never
discovered, the dispatch misses at runtime, the entire switch does nothing, and
the frame the caller allocated is never given back.

The lifter watches for a `ld` with a 32-bit displacement and a scaled index
followed by a `bx` on the same register, then reads entries out of the ROM
image while they still look like code addresses in this program. The table is
unbounded in the instruction stream — what limits it is a `cmpobl` a few
instructions earlier — so the heuristic stops at the first entry that is not
4-aligned and inside the program.

That found 188 more functions, and unblocked the game's own state machine: the
routine at `0x0001C8D0` dispatches on `0x0050F2D8` through exactly this shape,
and until the table was harvested none of it ran.

Function *ends* are implicit: each function runs to the start of the next
discovered one.

## Decoding: the parts that bite

### REG operand mode bits

The REG format packs two source operands and a destination, and three mode bits
decide what they mean:

| Bit | Meaning when set |
|---|---|
| 11 (`0x800`) | `src1` is a 5-bit **literal**, not a register |
| 12 (`0x1000`) | `src2` is a 5-bit **literal**, not a register |
| 13 (`0x2000`) | the destination is a **floating-point register** |

Getting these wrong is the single most expensive mistake available. An earlier
version read bit 5 as the src1 mode, which silently corrupted every REG
instruction with a literal operand — `addo 4, g1, g2` became `addo g4, g1, g2`.
The game still ran.

### Floating-point operands

Real-number instructions resolve their operands differently again, mirroring
MAME's `get_1_rif` / `get_2_rif` / `set_rif`:

- **mode clear** — an ordinary register holding IEEE bits. Single precision for
  the `r` forms, a register *pair* for the `rl` (long real) forms.
- **mode set, index < 4** — floating-point register `fp[index]`.
- **mode set, index `0x16`** — the literal `1.0`.
- **mode set, anything else** — the literal `0.0`.

So `subr 22, g4, g4` is `g4 = g4 - 1.0`, not a subtraction involving `g6`. A
disassembler that does not know the instruction is a float op prints it as a
register name, which is confusing exactly when you least want to be confused.

The lifter resolves all of this **statically**, at lift time, and emits a direct
expression:

```c
g_i960.r[20] = i960_f2u(i960_u2f(g_i960.r[20]) - 1.0);  /* subr */
```

### MEM addressing

MEMA (bit 12 clear) is a 13-bit offset with an optional base register. MEMB is
the rest: register indirect, scaled index, 32-bit displacement, and the
index-with-displacement forms that make the instruction 8 bytes. The lifter
follows MAME's `get_ea()` rather than the manual's table, because the
instruction length depends on the mode and getting it wrong desynchronises the
decoder for everything after it.

### Where the opcode table came from

MAME's `cpu/i960/i960.cpp`, read directly. Not the i960 manual. The manual and
the silicon disagree in places, MAME follows the silicon, and MAME is what the
game was tested against for twenty years.

## Known limitations

- **212 REG opcodes are unimplemented** across the whole ROM. Only four are
  inside functions that actually execute, and those are `flushreg` plus three
  in misdecoded data. Each emits a `/* TODO: REG opcode=... */` comment, so
  they are greppable.
- **No control-flow reconstruction.** Every branch is a `goto` to a label.
  MSVC and GCC handle 2,000 labels per translation unit without complaint, but
  the output is not pleasant reading.
- **No calling convention recovery.** Every function is `void f(void)` and all
  argument passing happens through the global register file. This is correct —
  it is what the hardware does — and it also means no optimiser will ever keep
  a register in a register.
- **Self-modifying code would break it.** Virtua Cop has none.

## Is it faithful?

The honest answer is "it is faithful enough that the game boots, runs its own
frame loop, and renders its attract mode". The one class of bug that survives
this far is arithmetic that is subtly wrong in code that runs rarely — and the
project has been bitten by exactly that once already, when the floating-point
mode bits were wrong and the game ran fine while computing garbage.

If you are chasing something that looks like a hardware bug, check the lifted C
for the function in question before you blame the board. It is usually the
board. It is not always the board.
