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

    /* 4. Main frame loop */
    printf("Starting main loop...\n");
    while (model2recomp_begin_frame()) {

        /*
         * Run one frame of recompiled game code.
         *
         * Once the ROM is analyzed and recompiled, this will call:
         *   1. The main game loop function
         *   2. Any per-frame update functions
         *   3. Geometry submission to TGP
         *
         * For now, the frame loop runs empty (black screen).
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
