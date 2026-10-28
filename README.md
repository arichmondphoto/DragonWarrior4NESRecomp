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

Map tiles generated with OpenAI's image API (like the characters):
`tools/export_chatgpt_tiles.py` packs every tile (pixel-exact, 15x, in the
palette its art is made for) onto 1536x1024 sheets of 24, by kind of area,
with prompts and `openai_sprites.py`; the results go in `hd/field/sheets/`
(with the export's `sheets.json`) and `tools/slice_field_sheets.py` lines each
sheet up with its input and cuts it into tiles, replacing the atlas art for
those tiles.

To redo art for some tiles: `tools/export_ai_tiles.py` exports every tile at
160x160 (pixel and smoothed versions, atlases, README), and
`tools/scenario_batch.py` runs them through Scenario in batch.

- *Walking characters* — the owner's artwork for every character that walks or
  stands on the maps (party, townspeople, soldiers, animals, ships, map
  monsters): `hd/sprites/source/<ID>.png`, one 4x2 sheet per character in the
  `tools/export_chatgpt_sprites.py` layout, generated with OpenAI's image API
  (`tools/openai_sprites.py`); `hd/sprites/ids.json` ties each ID to its frames.

How the characters are built (`tools/build_hd_pack.sh`):

1. `tools/capture_types.py` captures all 108 character types from the game's
   character table (bank 8 `$979B`, loaded by bank 28 `$9A37` → bank 8 `$85D3`):
   it points a town's people at other table entries (patched ROM, via patch
   0008) so every type is loaded, including the other chapters' heroes.
2. `tools/sprite_sheet.py --types` lists every character with its 8 frames
   (4 directions x 2 steps, WRAM `$7200+slot*64`), merged with what the map
   captures show (palettes, the party leader's own tiles).
3. `tools/check_ai_sprites.py` fits each sheet to the 8-bit outlines (whole
   sheet, then per frame) and reports frames that don't match.
4. `tools/make_sprite_hdpack.py` cuts each frame into its four 8x8 sprites,
   keyed by CHR bytes + colours, for every sprite palette set (day, special,
   night and fade steps). Shared tiles are told apart by `hmirror`/`vmirror` and
   neighbouring sprites (`spriteNearby`); people lying in bed (tiles the game
   turns 90/180/270 degrees) get the art turned the same way.
   The pack sets `<options>spriteCells` (patch 0009) so the art is drawn over
   the whole 8x8 sprite, not clipped to its 8-bit pixels.

- *Title screen* — the owner's painting in layers, `hd/title/layers/`
  (`layout.json` places them; painted on the guides from
  `tools/export_title_kit.py`). `tools/make_title_hdpack.py` draws the sky with
  the castle and the blank plate as still `<background>`s, the two cloud strips
  as backgrounds that scroll with the game's two cloud bands (`line:Y` + `wrap`,
  patch 0013), and reveals each painted letter as the game types it (8x8 cells,
  every other title cell almost transparent). The phase (blue sky / sunset and
  every fade step) is read from one castle cell and one plate cell
  (`tileAtPosition`). Without `*_day` layers the blue-sky look is recoloured from
  the sunset art along a light-to-colour ramp. `tools/capture_extras.py` records
  the intro every 4th frame (`title_seq.json`, with when each letter is finished).
- *Castle doors* — the three in-between frames of the big doors opening
  (drawn straight into the nametable, so not map tiles): `hd/field/doors/DOOR1.png`,
  cut by `tools/door_frames.py` into map tiles DR01-DR12 in every palette the
  closed door uses.
- *Endor casino* — captured without a playthrough by warping from the route
  (the exit table at `$05A0` pointed at map 4, submap 1; coins in WRAM `$62AD`).
  Poker: `tools/capture_casino.py` writes chosen cards into the deck (WRAM
  `$7600`, rank*4+suit, `$34` = joker) and deals them, so all 53 cards and the
  back are recorded; `tools/make_casino_hdpack.py` cuts the owner's card sheets
  `hd/casino/cards/C01-C09.png` into 5x7-tile cards (shared tiles told apart by
  `tileNearby`). Slot machine: `tools/capture_slots.py` plays three rounds (stand
  below a machine, step up to face it); `tools/make_slots_hdpack.py` draws the
  owner's painting `hd/casino/slots/SLOT.png` as a still `<background>` (read from
  the JACKPOT sign, with the fade steps; its text window is always blanked, since
  the text tiles are partly transparent) and the seven reel symbols (8x8 sprites
  in 16x16 groups) from `hd/casino/slots/SYMBOLS.png`; lamps and coin digits are
  smoothed. `tools/export_casino.py` makes the art package for OpenAI's image
  API. Without the art only the smoothed tiles are added. The arena needs nothing
  extra (HD monsters and text).
- *Night town crowd* — `hd/field/sheets/N01.png` (tiles T118-T127), cut by
  `tools/slice_field_sheets.py`.
- *More monsters* — `hd/monsters/extra/M###.png` (monsters the atlases didn't cover).

- macOS: `./build_macos.sh` (or `./package_macos_app.sh`) generates the pack and
  bundles it inside the app (`Contents/Resources/mods`; nothing is copied to
  your Library folder). In the launcher open **Mods**, turn on
  **HD text, windows, monsters, maps, characters and title** (once — the setting
  is kept in your Mods catalog), then start. `DW4_NO_HD=1` skips it.
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
  states made with the original, and a mod catalog made for the original). Only `tools/capture_types.py` uses it: it
  patches Dragon Warrior IV's character table (bank 8 `$979B`) so a town's
  people load every character type in turn. Without the variable nothing
  changes.
- `0009-hdpack-sprite-cells.patch` — a new pack option, `<options>spriteCells`:
  sprite HD art is drawn over the sprite's whole 8x8 cell with the art's own
  alpha (the PPU side channel now also records the sprite on its transparent
  pixels; empty OAM slots are excluded), instead of only on the 8-bit sprite's
  opaque pixels, which clipped smooth art to a stair-stepped silhouette. A
  transparent pixel of a sprite with no HD art draws nothing. Packs without the
  option behave as before.
- `0010-hdpack-nametable-column-condition.patch` — new pack conditions
  `nametableColumn` (0-31) and `nametableX` (0-63, with the nametable select):
  the column of the nametable the background pixel was fetched from. Mesen's
  `positionCheckX` is screen space, so art keyed to a cell slides off when a
  row scrolls (the title's parallax clouds). The column is kept in padding
  bytes of the HD record, so save states are unchanged.
- `0011-hdpack-tile-recolour-turn-shared-blocks.patch` — `<tile>` lines may end
  with `rgb:GR/OR/GG/OG/GB/OB` (per-channel colour map, out = in*G + O) and
  `rot:N` (the block turned N*90 degrees counter-clockwise). The pack stores each
  picture once and the player derives palette versions (other towns, night) and
  turned forms (people in bed) at load time; identical blocks are decoded once
  and shared. The pack went from 241 to 165 MiB and peak memory from ~2 GB to ~1.1 GB.
- `0012-mods-bundled-read-only-packages.patch` — with `NESRECOMP_BUNDLED_MODS`
  set to a folder laid out like the Mods catalog (`packages/<id>/<version>/`),
  its packages are listed as well (read-only, not removable; a copy installed in
  the catalog wins). The macOS app's launch script points it at the pack inside
  the app. Selections stay in the catalog's `state.toml`.
- `0013-hdpack-background-scanline-scroll-wrap.patch` — `<background>` lines may
  end with `line:Y` (scroll horizontally with the background drawn on scanline
  Y — its nametable position, so a split-screen band such as the title's
  parallax clouds is followed exactly) and `wrap` (repeat the image sideways).

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
