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
./build_macos.sh "/path/to/Dragon Warrior IV (USA).nes"
```
The first run installs cmake/ninja/sdl2/python, builds the game, packages it as
**Dragon Warrior IV.app** and installs it in `/Applications` (or `~/Applications`).
Open it from Launchpad, Spotlight or the Applications folder. After pulling updates,
run `./build_macos.sh` again to rebuild and reinstall.

- Settings, battery saves and save states: `~/Library/Application Support/DragonWarrior4Recomp`
  (kept across rebuilds; anything in the old `build/saves` is copied over once).
- The app bundles SDL2, the launcher assets and **your ROM** — don't share the app.
- `DW4_NO_INSTALL=1 ./build_macos.sh` leaves the app in `dist/`; `./play_macos.sh` still runs the unpackaged build.

Keyboard: arrows = D-pad, **Z** = A, **X** = B, **Return** = Start, `\` = Select. Gamepads work out of the box.
Esc = menu, F7 = save states, F8 = rewind, Tab = fast-forward, F11 = fullscreen (on a Mac keyboard you may need fn+F7 etc.).

## Build (headless baseline)
```sh
git submodule update --init
cmake -S nesrecomp/runner/cyc/project -B build-headless -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DNESRECOMP_ROM="$PWD/rom/DragonWarriorIV.nes" -DNESRECOMP_GAME_CONFIG="$PWD/game.toml" -DNESRECOMP_HEADLESS=ON
cmake --build build-headless
./build-headless/nes_game rom/DragonWarriorIV.nes --frames 600 --screenshot boot.png
```
Windowed build: `cmake -S . -B build` (needs SDL2 dev package).

## HD texture packs
HD packs (Mesen format) are enabled in the build (`MODS HD_PACKS`). Packs are
presentation-only: the game runs identically with them on or off (frame hashes
match over the Chapter 1 route).

**Project standard: every HD pack is authored at 10x** (`<scale>10`, 80x80
pixels per tile, a 2560x2400 picture — the presenter's ceiling), so it stays
sharp at every Window Scale from 1x to 10x.

**HD text and windows** — the font, window borders, cursors and arrows,
smoothly upscaled 10x from the game's own 8x8 tiles (`tools/smooth_pixels.py`),
so every letter keeps its Dragon Warrior IV shape. Covers dialog, menus, window
titles, the status window and battle text; maps and sprites stay original.
The art is generated from **your ROM** at build time and is not stored in the repo.

- macOS: `./build_macos.sh` (or `./package_macos_app.sh`) generates the pack and
  installs it in the Mods catalog. In the launcher open **Mods**, turn on
  **HD text and windows**, then start. `DW4_NO_HD=1` skips it.
- Elsewhere: `tools/build_hd_text.sh HOST OUTDIR [PYTHON]` (needs Pillow), then
  `nesrecomp/tools/package_hdpack.py` to make a `.nesmod`.
- `tools/make_font_hdpack.py --style font --font X.ttf` instead re-renders the
  letters from any font (window pieces stay smoothed).
- Tiles are matched by their 16 CHR-RAM bytes with `default=Y` (any palette).
  Bump `HD_VERSION` in `package_macos_app.sh` when the generator changes.

## Framework patches
`patches/nesrecomp/*.patch` are fixes to the pinned nesrecomp checkout, applied
by `tools/apply_patches.sh` (run automatically by `build_macos.sh`; idempotent).
They are framework bugs, kept here until they can go upstream:

- `0001-cyc_sdl-hd-window-native-size.patch` — with an HD pack the window was
  sized from the 4x HD picture (3072x2880 at Window Scale 3, clamped by macOS) and
  integer scaling stepped in HD-picture units, so the game drew small inside an
  oddly sized window. Window, logical size and integer steps now use native
  256x240 pixels; HD textures are sampled linearly.
- `0002-cyc-window-scale-max-10.patch` — Window Scale was clamped to 8 in
  config.ini, the launcher bridge and the in-game menu; one `CYC_WINDOW_SCALE_MAX`
  (10) now applies everywhere.

`patches/recomp-ui/*.patch` likewise apply to the launcher checkout:

- `0001-launcher-configurable-window-scale-max.patch` — the launcher offered
  1x-6x only; `LNG_WINDOW_SCALE_MAX` is now a compile-time override (default 6),
  which this project's `CMakeLists.txt` sets to 10.

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
