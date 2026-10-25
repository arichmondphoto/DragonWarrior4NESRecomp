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

**HD text, windows and monsters** (one pack — the Mods system allows one HD pack at a time):

- *Text and windows* — the font, window borders, cursors and arrows, smoothly
  upscaled 10x from the game's own 8x8 tiles (`tools/smooth_pixels.py`), so every
  letter keeps its Dragon Warrior IV shape. Generated from **your ROM** at build time.
- *Battle monsters* — the owner's artwork (`hd/monsters/source/DW4Sprites.jpg`)
  replacing the 8-bit monsters. `hd/monsters/mapping.json` maps each sheet sprite
  to a game monster ID; `boxes.json` holds each sprite's box on the sheet.

How the monsters are built (`tools/build_hd_pack.sh`):

1. `tools/capture_monsters.py` forces one battle per monster ID by writing a
   fixed battle (slots `$6E45-$6E48`, `$FF` = empty; counts `$6E49-$6E4C`; flags
   `$6E44`, as the game's own setup at bank 24 `$A1AD` does) into a save state
   taken just after the route's first encounter, and dumps each battle (tiles,
   palettes, sprites, name). `tools/force_formation.py` starts any of the game's
   34 fixed formations the same way.
2. `tools/capture_necrosaro.py` starts the Necrosaro battle (formation 25) and
   drives the real transformations: his HP (`$727E`) is set to 1 and Ragnar
   boosted, A is tapped until the form counter `$6E7E` goes up, and each of the
   8 forms is dumped.
3. `tools/make_monster_hdpack.py` cuts each sprite from the sheet (transparency
   rebuilt from the black background), fits it to the original monster's pixels at
   10x and slices it along the original's pieces: background cells (keyed by CHR
   bytes + exact palette) and 8x8 sprites (pattern table `$0000`, stored
   un-flipped). Repeated tiles inside a monster are told apart by a neighbouring
   tile (`tileNearby`) or by `hmirror`/`vmirror`. Necrosaro's forms share most of
   their tiles, so each form's tiles are gated on `$6E7E` (`when` in mapping.json).
   The presenter draws a sprite's HD slice only where the 8-bit sprite pixel is
   opaque, so for these gated sprites the art is also keyed onto the blank
   background cells beneath them (gated on the cell's position), which keeps
   it from being clipped to the 8-bit silhouette.
4. `tools/render_monsters_hd.py` + `tools/score_hd_sweep.py` render every monster
   with `NESRECOMP_HDPACK_DEBUG=1` and report any original pixels still showing.

To change a pairing, edit `hd/monsters/mapping.json` (sheet index → monster ID;
`captures` for sprites keyed on a special capture) and rebuild;
`tools/review_sheet.py` draws side-by-side review pages. `no_art` lists the game
monsters with no sprite on the sheet (sea monsters and two recolours); they keep
their 8-bit art.

- *Map tiles* — the owner's artwork for every 16x16 map tile of the overworld,
  towns, castles and dungeons (`hd/field/source/*.png`, 6x6-cell atlases with a
  `.json` cell list each; `hd/field/ids.json` ties each tile ID to its tile).

How the map tiles are built (`tools/build_hd_pack.sh`):

1. `tools/capture_field.py` loads every map (279 areas + the overworld) by
   rewriting the exit table at `$05A0` one step from Burland Castle's exit, and
   dumps each map's metatiles (`$7600`), sub-palettes (`$76C0`), CHR and palette.
2. `tools/field_sheet.py` lists every unique map tile and each palette it is
   drawn with (`field_tiles.json`; without `--json-only` it also draws the
   numbered artwork sheets).
3. `tools/slice_field_atlases.py` cuts the atlases into 160x160 tiles (finding
   each atlas's gutters, which image generators shift slightly).
4. `tools/make_field_hdpack.py` keys each tile's four 8x8 quarters by CHR bytes +
   palette for every palette version. A quarter shared by several map tiles is
   told apart by its neighbouring quarter (`tileNearby`); repeating ground tiles
   get their edges evened out so they tile without seams.
   - *Palettes and night:* the art is made for one palette per tile (stored in
     `hd/field/ids.json`); every other palette the game draws it with (other
     towns and dungeons, and night, captured with `capture_field.py --night`,
     which sets the clock at `$62ED` past `$78`) gets a recoloured copy fitted
     from the palette colours.
   - *Fades:* screen transitions step every colour down by `$10` three times;
     each version also gets entries for those three palettes, with the same art
     at the matching brightness, so the HD art fades instead of flashing 8-bit.

To redo art for some tiles: `tools/export_ai_tiles.py` exports every tile at
160x160 (pixel and smoothed versions, atlases, README), and
`tools/scenario_batch.py` runs them through Scenario in batch.

- macOS: `./build_macos.sh` (or `./package_macos_app.sh`) generates the pack and
  installs it in the Mods catalog. In the launcher open **Mods**, turn on
  **HD text, windows, monsters and maps**, then start. `DW4_NO_HD=1` skips it.
- Tiles are matched by their 16 CHR-RAM bytes and exact palettes.
  Bump `HD_VERSION` in `package_macos_app.sh` when the pack's content changes.

## Framework patches
`patches/nesrecomp/*.patch` are fixes to the pinned nesrecomp checkout, applied
by `tools/apply_patches.sh` (run automatically by `build_macos.sh`). It restores the files the
patches touch to the pinned commit, then applies every patch in order, so any earlier state is fine.
They are framework bugs, kept here until they can go upstream:

- `0001-cyc_sdl-hd-window-native-size.patch` — with an HD pack the window was
  sized from the 4x HD picture (3072x2880 at Window Scale 3, clamped by macOS) and
  integer scaling stepped in HD-picture units, so the game drew small inside an
  oddly sized window. Window, logical size and integer steps now use native
  256x240 pixels; HD textures are sampled linearly.
- `0002-cyc-window-scale-max-10.patch` — Window Scale was clamped to 8 in
  config.ini, the launcher bridge and the in-game menu; one `CYC_WINDOW_SCALE_MAX`
  (10) now applies everywhere.

- `0003-cyc_sdl-fit-window-to-display.patch` — Window Scale is in points on
  macOS, so large scales (e.g. 10x = 2560x2400 points) ran off the screen. The
  window now uses the largest whole scale that fits the display (the setting is
  kept for bigger screens). On a Retina display Window Scale 5 already shows a
  10x pack at full detail (2 pixels per point).

- `0004-cyc-trim-side-borders.patch` — Dragon Warrior IV (like many NES games)
  masks the leftmost 8 pixels, leaving a black bar. New setting **Trim side
  borders** (in-game menu > Display; `CropSides` in config.ini; on by default)
  trims 8 pixels from both sides so the picture stays centred (240x240).
- `0005-cyc-launcher-trim-side-borders.patch` — also offers that setting in the
  launcher's Display settings (needs recomp-ui patch 0002).

- `0006-cyc_ui_imgui-hidpi-menu-scale.patch` — on a Retina display the in-game
  menu drew at half size in the top-left with its text clipped: Dear ImGui lays
  out in points but nesrecomp never set the renderer's HiDPI scale (as ImGui's
  SDL example does). Ratio 1 (Windows/Linux) is unchanged.
- `0007-hdpack-memory-conditions-read-wram.patch` — `memoryCheck` /
  `memoryCheckConstant` conditions only read the 2KB internal RAM, so a condition
  on `$6000-$7FFF` was always false. They now read the cartridge work RAM, where
  Dragon Warrior IV keeps its battle state (the pack gates Necrosaro's forms on
  `$6E7E`).
- `0008-allow-prg-mismatch-env-for-tools.patch` — with the environment variable
  `NESRECOMP_ALLOW_PRG_MISMATCH` set, the host accepts a modified ROM (and save
  states made with the original). Only `tools/capture_types.py` uses it: it
  patches Dragon Warrior IV's character table (bank 8 `$979B`) so a town's
  people load every character type in turn. Without the variable nothing
  changes.

`patches/recomp-ui/*.patch` likewise apply to the launcher checkout:

- `0001-launcher-configurable-window-scale-max.patch` — the launcher offered
  1x-6x only; `LNG_WINDOW_SCALE_MAX` is now a compile-time override (default 6),
  which this project's `CMakeLists.txt` sets to 10.
- `0002-launcher-trim-side-borders-setting.patch` — an optional "Trim side
  borders" checkbox in Display settings (`Settings.crop_sides`,
  `GameInfo.has_crop_sides`, appended ABI-additively).

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
