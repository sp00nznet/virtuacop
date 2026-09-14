cmake_minimum_required(VERSION 3.20)
project(virtuacop C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

# SDL2 imported targets (SDL2::SDL2, SDL2::SDL2main) are directory-scoped when
# discovered. Find the package at top-level scope so the launcher executable
# below can link SDL2::SDL2main directly.
find_package(SDL2 REQUIRED)

# Embed model2recomp as subdirectory
set(MODEL2RECOMP_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
add_subdirectory(ext/model2recomp)

# --- Recompiled game code library ---
# Collect all generated recomp source files
# CONFIGURE_DEPENDS: the lifter can emit a different number of files than the
# last run did, and a stale glob links against declarations with no bodies.
file(GLOB VCOP_RECOMP_SOURCES CONFIGURE_DEPENDS src/recomp/vcop_code_*.c)

add_library(vcop_game STATIC
    src/recomp/vcop_register.c
    ${VCOP_RECOMP_SOURCES}
)

target_include_directories(vcop_game
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src/recomp
)

target_link_libraries(vcop_game
    PUBLIC model2recomp
)

# MSVC settings
if(MSVC)
    target_compile_options(vcop_game PRIVATE /W3)
    target_compile_definitions(vcop_game PRIVATE _CRT_SECURE_NO_WARNINGS)
else()
    target_compile_options(vcop_game PRIVATE -Wall -Wextra -Wno-unused-parameter)
endif()

# --- Launcher executable ---
add_executable(vcop
    src/main/main.c
)

target_link_libraries(vcop PRIVATE
    vcop_game
    model2recomp
    SDL2::SDL2main
)
