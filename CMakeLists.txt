cmake_minimum_required(VERSION 3.20)
project(virtuacop C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Embed model2recomp as subdirectory
set(MODEL2RECOMP_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
add_subdirectory(ext/model2recomp)

# --- Recompiled game code library ---
add_library(vcop_game STATIC
    src/recomp/vcop_stubs.c
)

target_include_directories(vcop_game
    PUBLIC  ${CMAKE_CURRENT_SOURCE_DIR}/include
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
