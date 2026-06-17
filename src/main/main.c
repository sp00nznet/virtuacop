/*
 * Virtua Cop - Static Recompilation Launcher
 *
 * Sega Model 2 (Original), 1994
 * Intel i960KB @ 25 MHz
 * 5x Fujitsu MB86234 TGP geometry coprocessors
 * 68000 + YM3438 + 2x MultiPCM sound
 * Lightgun game (2 players)
 *
 * Usage: vcop [rom_directory]
 */

#include "model2recomp/model2recomp.h"
#include "model2recomp/i960.h"
#include "model2recomp/bus.h"
#include "model2recomp/func_table.h"
#include "vcop/functions.h"

#include <stdio.h>
#include <stdlib.h>

int main(int argc, char *argv[])
{
    const char *rom_dir = (argc > 1) ? argv[1] : "roms";

    printf("=== Virtua Cop - Static Recompilation ===\n");
    printf("Sega Model 2 (1994)\n\n");

    /* 1. Initialize Model 2 hardware */
    if (!model2recomp_init("Virtua Cop", 2, MODEL2_ORIGINAL)) {
        fprintf(stderr, "Failed to initialize model2recomp\n");
        return 1;
    }

    /* 2. Load ROM set */
    if (!model2recomp_load_rom(rom_dir)) {
        fprintf(stderr, "Failed to load ROMs from: %s\n", rom_dir);
        model2recomp_shutdown();
        return 1;
    }

    /* 3. Register all recompiled i960 functions */
    vcop_register_all();

    /*
     * 4. Boot the i960.
     *
     * The CPU resets to the entry point (IP) with the frame pointer and stack
     * pointer initialized from the Process Control Block. We reproduce that
     * documented boot state, then dispatch the entry function through the
     * function table. The reset routine performs hardware/memory init and
     * returns; this is the first real exercise of the recompiled code and the
     * model2recomp bus.
     */
    #define VCOP_ENTRY_POINT 0x000005D0u
    I960_FP = 0x00500C00u; /* Frame Pointer in Work RAM */
    I960_SP = 0x00500C40u; /* Stack Pointer */
    g_i960.IP = VCOP_ENTRY_POINT;

    printf("Booting i960 at entry point 0x%08X...\n", VCOP_ENTRY_POINT);
    if (!func_table_call(VCOP_ENTRY_POINT)) {
        fprintf(stderr, "Entry point 0x%08X is not registered!\n", VCOP_ENTRY_POINT);
    } else {
        printf("Entry routine returned (i960 reset/init complete).\n");
    }

    /* 5. Main frame loop.
     * VCOP_MAX_FRAMES (env) caps the run for automated boot tests; unset = run
     * until the window is closed. */
    const char *max_frames_env = getenv("VCOP_MAX_FRAMES");
    long max_frames = max_frames_env ? strtol(max_frames_env, NULL, 10) : 0;
    long frame = 0;

    printf("Starting main loop...\n");
    while (model2recomp_begin_frame()) {
        if (max_frames > 0 && frame++ >= max_frames) {
            printf("Reached VCOP_MAX_FRAMES=%ld, exiting loop.\n", max_frames);
            break;
        }

        /*
         * Per-frame game code would be dispatched here (the recompiled main
         * loop / VBlank handler) once the per-frame entry point is identified.
         * For now we drive the hardware frame cadence: raise VBlank and present.
         */

        /* Trigger VBlank interrupt */
        model2recomp_trigger_vblank();

        /* Render and present frame */
        model2recomp_end_frame();
    }

    /* 5. Shutdown */
    model2recomp_shutdown();

    printf("Virtua Cop exited cleanly.\n");
    return 0;
}
