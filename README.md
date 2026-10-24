# Dragon Warrior IV (USA) — NESRecomp port

Static recompilation of Dragon Warrior IV (NES) using [mstan/nesrecomp](https://github.com/mstan/nesrecomp), cycle backend.

## ROM (not included)
Dragon Warrior IV (USA), NES 2.0 header, 524,304 bytes.
- CRC32 (no header): `506E259D`
- SHA-1 (no header): `1b3dc265ba0d7e4b2cef9b3f8b0be0847df67c3c`
- Board: MMC1 SUROM — 512 KiB PRG, 8 KiB CHR-RAM, 8 KiB battery PRG-RAM

Place it at `rom/DragonWarriorIV.nes`.

## Build (headless baseline)
```sh
git submodule update --init
cmake -S nesrecomp/runner/cyc/project -B build-headless -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DNESRECOMP_ROM="$PWD/rom/DragonWarriorIV.nes" -DNESRECOMP_GAME_CONFIG="$PWD/game.toml" -DNESRECOMP_HEADLESS=ON
cmake --build build-headless
./build-headless/nes_game rom/DragonWarriorIV.nes --frames 600 --screenshot boot.png
```
Windowed build: `cmake -S . -B build` (needs SDL2 dev package).

## Native coverage
`seeds.txt` is gathered with `--miss-log` along routes in `routes/`, then used as `cycle_seed_file`.
Re-run new routes with `--miss-log seeds.txt` to extend coverage.
