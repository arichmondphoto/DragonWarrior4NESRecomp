cmake_minimum_required(VERSION 3.20)
project(DragonWarrior4Recomp C CXX)

set(NESRECOMP_ROOT "${CMAKE_SOURCE_DIR}/nesrecomp" CACHE PATH "nesrecomp checkout")
set(DW4_ROM "${CMAKE_SOURCE_DIR}/rom/DragonWarriorIV.nes" CACHE FILEPATH "Dragon Warrior IV (USA) ROM")

# HD packs are authored at 10x (2560x2400, the presenter's ceiling), so offer
# Window Scale up to 10x in the recomp-ui launcher as well as the in-game menu
# (patches/recomp-ui/0001 makes the launcher limit configurable;
# patches/nesrecomp/0002 raises the host's own limit to 10).
add_compile_definitions(LNG_WINDOW_SCALE_MAX=10)

# A cross build (windows/build_in_env.sh: Windows from Linux) can't run the
# recompiler it would build, so it passes one built for the machine doing the build.
set(DW4_RECOMPILER "" CACHE FILEPATH "Runnable NESRecomp for cross builds (empty: build one)")
set(DW4_RECOMPILER_ARG)
if(DW4_RECOMPILER)
    set(DW4_RECOMPILER_ARG RECOMPILER "${DW4_RECOMPILER}")
endif()

include("${NESRECOMP_ROOT}/runner/cyc/project.cmake")
nesrecomp_add_cycle_game(DragonWarrior4
    ROM "${DW4_ROM}"
    ${DW4_RECOMPILER_ARG}
    GAME_CONFIG "${CMAKE_SOURCE_DIR}/game.toml"
    # Mods runtime with the shared Mesen HD pack provider (off until a pack is
    # installed and enabled in the launcher's Mods screen).
    MODS HD_PACKS GAME_ID "dragon-warrior-4"
    # Map edges drawn from the game's map at the full 256x240 picture
    # (src/dw4_edges.c; needs nesrecomp patch 0021).
    HOST_EXTRAS "${CMAKE_SOURCE_DIR}/src/dw4_edges.c")

# The Cheats page's catalog of known Game Genie codes (cheats/catalog.txt,
# checked by tools/check_cheat_catalog.py) goes beside the program with the
# launcher's assets, which every package carries (nesrecomp patch 0032 points
# the launcher at it).
if(TARGET DragonWarrior4)
    add_custom_command(TARGET DragonWarrior4 POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E make_directory $<TARGET_FILE_DIR:DragonWarrior4>/assets
        COMMAND ${CMAKE_COMMAND} -E copy_if_different ${CMAKE_SOURCE_DIR}/cheats/catalog.txt
                $<TARGET_FILE_DIR:DragonWarrior4>/assets/cheats_catalog.txt)
endif()
