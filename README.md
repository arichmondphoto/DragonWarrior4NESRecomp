# Dragon Warrior IV (USA) — NESRecomp port

Static recompilation of Dragon Warrior IV (NES) using [mstan/nesrecomp](https://github.com/mstan/nesrecomp), cycle backend.

## ROM (not included)
Dragon Warrior IV (USA), NES 2.0 header, 524,304 bytes.
- CRC32 (no header): `506E259D`
- SHA-1 (no header): `1b3dc265ba0d7e4b2cef9b3f8b0be0847df67c3c`
- Board: MMC1 SUROM — 512 KiB PRG, 8 KiB CHR-RAM, 8 KiB battery PRG-RAM

Place it at `rom/DragonWarriorIV.nes`.

## Play on macOS
Requires the Xcode command line tools and [Homebrew](https://brew.sh).
```sh
git clone https://github.com/arichmondphoto/DragonWarrior4NESRecomp.git   # private repo: sign in when prompted
cd DragonWarrior4NESRecomp
./build_macos.sh "/path/to/Dragon Warrior IV (USA).nes"   # first time: installs cmake/ninja/sdl2/python, builds
./play_macos.sh
```
Keyboard: arrows = D-pad, **Z** = A, **X** = B, **Return** = Start, `\` = Select. Gamepads work out of the box.
Esc = menu, F7 = save states, F8 = rewind, Tab = fast-forward, F11 = fullscreen (on a Mac keyboard you may need fn+F7 etc.).
Settings and bindings live in `build/config.ini`; battery saves in `build/saves/`.

## Build (headless baseline)
```sh
git submodule update --init
cmake -S nesrecomp/runner/cyc/project -B build-headless -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DNESRECOMP_ROM="$PWD/rom/DragonWarriorIV.nes" -DNESRECOMP_GAME_CONFIG="$PWD/game.toml" -DNESRECOMP_HEADLESS=ON
cmake --build build-headless
./build-headless/nes_game rom/DragonWarriorIV.nes --frames 600 --screenshot boot.png
```
Windowed build: `cmake -S . -B build` (needs SDL2 dev package).

## Test routes
| Route | Frames | Covers |
|---|---|---|
| `routes/boot_to_name_entry.txt` | 7,600 | intro, title, Begin a New Quest, name entry |
| `routes/ch1_to_first_battles.txt` | 18,000 | name/gender, Chapter 1 intro, King's briefing, Burland castle and town, world map, several battles (Slime, Giant Worm) |

Run: `./build-headless/nes_game rom/DragonWarriorIV.nes --frames 18000 --input routes/ch1_to_first_battles.txt`

Useful RAM (verified by stepping): `$40` map id (36 castle, 41 Burland town), `$44`/`$45` player X/Y tile in town/castle maps.

`tools/drive.py` steers tile-by-tile from a save state and checks each step against RAM; `tools/route.py` turns a simple tap/hold spec into an input file.

## Native coverage
`seeds.txt` is gathered with `--miss-log` along routes in `routes/`, then used as `cycle_seed_file`.
Re-run new routes with `--miss-log seeds.txt` to extend coverage.
`captures.txt` (RAM-resident code, e.g. the $0502 NMI trampoline) is gathered with `--capture-log` and used as `cycle_capture_file`.
