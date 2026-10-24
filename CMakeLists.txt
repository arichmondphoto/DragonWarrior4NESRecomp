cmake_minimum_required(VERSION 3.20)
project(DragonWarrior4Recomp C CXX)

set(NESRECOMP_ROOT "${CMAKE_SOURCE_DIR}/nesrecomp" CACHE PATH "nesrecomp checkout")
set(DW4_ROM "${CMAKE_SOURCE_DIR}/rom/DragonWarriorIV.nes" CACHE FILEPATH "Dragon Warrior IV (USA) ROM")

include("${NESRECOMP_ROOT}/runner/cyc/project.cmake")
nesrecomp_add_cycle_game(DragonWarrior4
    ROM "${DW4_ROM}"
    GAME_CONFIG "${CMAKE_SOURCE_DIR}/game.toml"
    # Mods runtime with the shared Mesen HD pack provider (off until a pack is
    # installed and enabled in the launcher's Mods screen).
    MODS HD_PACKS GAME_ID "dragon-warrior-4")
