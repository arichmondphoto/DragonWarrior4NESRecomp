cmake_minimum_required(VERSION 3.20)
project(DragonWarrior4Recomp C CXX)

set(NESRECOMP_ROOT "${CMAKE_SOURCE_DIR}/nesrecomp" CACHE PATH "nesrecomp checkout")
set(DW4_ROM "${CMAKE_SOURCE_DIR}/rom/DragonWarriorIV.nes" CACHE FILEPATH "Dragon Warrior IV (USA) ROM")

# HD packs are authored at 10x (2560x2400, the presenter's ceiling), so offer
# Window Scale up to 10x in the recomp-ui launcher as well as the in-game menu
# (patches/recomp-ui/0001 makes the launcher limit configurable;
# patches/nesrecomp/0002 raises the host's own limit to 10).
add_compile_definitions(LNG_WINDOW_SCALE_MAX=10)

include("${NESRECOMP_ROOT}/runner/cyc/project.cmake")
nesrecomp_add_cycle_game(DragonWarrior4
    ROM "${DW4_ROM}"
    GAME_CONFIG "${CMAKE_SOURCE_DIR}/game.toml"
    # Mods runtime with the shared Mesen HD pack provider (off until a pack is
    # installed and enabled in the launcher's Mods screen).
    MODS HD_PACKS GAME_ID "dragon-warrior-4")
