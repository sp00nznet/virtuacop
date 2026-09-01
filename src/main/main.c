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
#include <stdint.h>

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

    /* VCOP_MAX_FRAMES (env) caps the run for automated boot tests; unset = run
     * until the window is closed. The game owns the frame loop and never
     * returns, so the limit is enforced at the field-sync point. */
    const char *max_frames_env = getenv("VCOP_MAX_FRAMES");
    model2recomp_set_frame_limit(max_frames_env ? strtol(max_frames_env, NULL, 10) : 0);

    /*
     * 4. Boot the i960.
     *
     * Reset enters at the SAT/PRCB-documented IP with FP/SP from the PRCB.
     * The reset stub at 0x5D0 relocates the PRCB and interrupt table into work
     * RAM and then issues an IAC "Reinitialize Processor" message, which hands
     * control to the real firmware entry (0x6A0 -> main at 0x2370). Follow that
     * chain rather than hardcoding the second entry point.
     */
    #define VCOP_ENTRY_POINT 0x000005D0u
    #define VCOP_RESET_PRCB  0x000000B0u

    uint32_t ip = VCOP_ENTRY_POINT;
    uint32_t prcb = VCOP_RESET_PRCB;

    for (int hop = 0; ip != 0 && hop < 8; hop++) {
        /* Initial FP comes from the PRCB stack-pointer field; SP sits one
         * register-save area above it. */
        I960_FP = bus_read32(prcb + 0x18);
        I960_SP = I960_FP + 0x40;
        g_i960.IP = ip;

        printf("Booting i960 at 0x%08X (PRCB 0x%08X, FP 0x%08X)...\n",
               ip, prcb, I960_FP);
        if (!func_table_call(ip)) {
            fprintf(stderr, "Entry point 0x%08X is not registered!\n", ip);
            break;
        }
        printf("  routine returned.\n");
        ip = bus_iac_take_reinit(&prcb);
    }

    /* 5. Fallback frame loop.
     *
     * Reaching here means the game returned from main instead of entering its
     * own loop - i.e. init bailed out early. Keep the window alive so the
     * failure is visible rather than exiting instantly. */
    printf("Game returned from main; running fallback frame loop.\n");
    while (model2recomp_begin_frame()) {
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
