/*
 * Virtua Cop - Recompiled function declarations.
 *
 * Each function corresponds to a code entry point in the original
 * i960 program ROM. Functions are named vcop_XXXXXXXX where XXXXXXXX
 * is the original i960 address in hex.
 *
 * All functions operate on the global g_i960 context and use
 * bus_read/bus_write for memory access.
 */

#ifndef VCOP_FUNCTIONS_H
#define VCOP_FUNCTIONS_H

#include "model2recomp/i960.h"
#include "model2recomp/bus.h"
#include "model2recomp/func_table.h"

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Register all recompiled functions with the function table.
 * Called once during initialization.
 */
void vcop_register_all(void);

/*
 * Recompiled function declarations will go here as the ROM is analyzed.
 * Example:
 *   void vcop_00000100(void);  // Reset vector
 *   void vcop_000001A0(void);  // Main loop entry
 *   void vcop_00001000(void);  // VBlank handler
 */

/* TODO: Add function declarations as ROM analysis progresses */

#ifdef __cplusplus
}
#endif

#endif /* VCOP_FUNCTIONS_H */
