# Diffing against MAME

MAME runs Virtua Cop on the same ROM set this project recompiles, so it is an
oracle for everything the game computes. The strongest check available: run
both from reset and compare the **display list** — the command stream the i960
builds in buffer RAM and hands to the geometry engine. It is the entire output
of the game's computation, so if the recompiled CPU is wrong anywhere that
matters, the lists diverge.

## Capturing from MAME

`dump_display_list.lua` writes buffer RAM (`0x00900000`, 128KB) and a snapshot
at chosen frames.

```bash
mame vcop -rompath <dir with vcop.zip> -video none -sound none -nothrottle \
    -seconds_to_run 16 -autoboot_script tools/mame/dump_display_list.lua \
    -snapshot_directory snap -skip_gameinfo
```

`VCOP_DUMP_DIR` sets where the `.buf` files land. `hd44780_a00.bin` fails its
checksum in most ROM sets — it is the LCD character font on the I/O board,
MAME marks it `BAD_DUMP` itself, and it has nothing to do with the i960, so the
warning is safe to ignore.

Use `emu.register_frame`. It is deprecated in favour of
`emu.add_machine_frame_notifier`, which did not fire for us.

## Capturing from here

`MODEL2_SHOT_EVERY=N` with `MODEL2_SCREENSHOT=path` writes `path.<field>.ppm`
and `path.<field>.buf` together.

## Lining the two up

Our field counter is **not** the game's frame number. The field boundary sits
inside the guest's busy-wait on the video status register, which it polls a
varying number of times per frame, so the same field number lands on different
game frames from one run to the next. Match on content, not on number — but
match on the *active* part of the list, from `geo_read_start_address` for the
length of the stream. Most of the 128KB is static (MAME fills it with
`0x07800f0f` at reset) so comparing the whole region matches everything
against everything.

## What this found

At a matched moment, 32,765 of 32,768 dwords are identical. The three that
differ are the same float to the last four mantissa bits — `3E167FEF` against
`3E167FF8`. The recompiled i960 computes what the real one computes.
