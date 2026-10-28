# CLAUDE.md — Dragon Warrior IV NES recompilation

Static recompilation of Dragon Warrior IV (USA, NES) with [mstan/nesrecomp](https://github.com/mstan/nesrecomp)
(cycle backend), plus one HD texture pack built mostly from the owner's own artwork.
README.md is the full reference; this file is the working summary.

## Layout
- `nesrecomp/`, `recomp-ui/` — git submodules (framework, launcher). **Never commit changes in them**:
  framework fixes live as `patches/<submodule>/NNNN-*.patch`, applied by `tools/apply_patches.sh`.
  Keep `nesrecomp/CLAUDE.md`'s rules in mind (fix the tool, never generated output).
- `rom/DragonWarriorIV.nes` — not in git (CRC32 `506E259D` without header).
- `game.toml`, `seeds.txt`, `captures.txt` — recompiler config / dispatch seeds.
- `hd/` — the owner's committed art and its metadata (see "Art" below).
- `tools/` — every capture/build script for the HD pack (Python, stdlib + numpy/Pillow/scipy).
- `routes/` — input scripts (`FRAME BUTTON` / `FRAME -` lines); `ch1_to_first_battles.txt` is the
  reference route most captures replay.
- `out/`, `build*/`, `hd/pack/`, `hd/text/` — generated, git-ignored.

## Building
- Owner (macOS): `./build_macos.sh` (installs deps, applies patches, builds, makes the app) and
  `./package_macos_app.sh` (rebuilds when patches changed, builds the HD pack and bundles it in the app's
  `Contents/Resources/mods`, found via `NESRECOMP_BUNDLED_MODS` set by the app's launch script, patch 0012).
  `./build_macos.sh --release` = shareable zip without the ROM (+ `release/READ_ME_FIRST.txt`, placeholders
  filled by package_macos_app.sh); the launch script finds the ROM (bundled → rom.cfg → *.nes in the data
  folder → launcher picker), writes mods/state.toml on first run, sets NESRECOMP_SAVE_NAME/STATE_DIR (0015).
- Linux headless host used for tests here (`build-hd/DragonWarrior4`, NESRECOMP_HEADLESS=ON, MODS + HD
  packs): `tools/apply_patches.sh && cmake --build build-hd`.
- HD pack: `tools/build_hd_pack.sh HOST OUTDIR [PYTHON] [JOBS]` (e.g. `build-hd/DragonWarrior4 out/build7/pack python3 2`).
  Captures are cached beside OUTDIR (`*-capture/.stamp` = hash of host, ROM, route, capture script).
  A full build takes ~25 min; peak RAM ~1.1 GB per host process with the pack.
- **Bump `HD_VERSION` in `package_macos_app.sh` whenever the pack's content changes** (the mod
  catalog keys on it). Current: 0.12.0. Pack name: "HD text, windows, monsters, maps, characters, title and casino".
- The nesmod package limit is 256 MiB; the pack is ~165 MiB — watch its size (`du -sb OUTDIR`). Never store
  recoloured or turned copies of art: emit `rgb:`/`rot:` tokens on the tile line (patch 0011) instead.

## Headless testing
- `HOST rom/DragonWarriorIV.nes --frames N [--input ROUTE] --no-save --mods-root MODS --present-out f.png`
  renders the 10x HD frame; `--screenshot` the 8-bit one; `--mem-frame N --mem-out f.mem` dumps
  RAM/WRAM/CIRAM/CHR/palette (read with `tools/vramdump.load`).
- `NESRECOMP_HDPACK_DEBUG=1`: unmatched BG pixels draw magenta, unmatched sprites cyan.
- Install a pack for the host: package it with `nesrecomp/tools/package_hdpack.py` into
  `MODS/packages/dragon-warrior-4.hd-text/<ver>/` and enable it in `MODS/state.toml`.
- Save states (`--save-state F:path`, `--load-state`) are fingerprinted to the installed pack:
  remake them after reinstalling. A state loaded at frame N continues at N+1.
- Battery saves: `--save-file COPY.sav` (it writes back — always use a copy; omit `--no-save`).
- Always pass an empty `--mods-root` to capture runs (the host otherwise opens the user's catalog).
- `tools/render_monsters_hd.py HOST MODS OUT ID...` forces battles to check monster art.

## Art (the owner's work is committed; ROM-derived art is generated at build time, never committed)
- Map tiles: `hd/field/source/*` atlases (keep them — the owner rejected AI-regenerated map tiles),
  `hd/field/sheets/` (night crowd N01), `hd/field/doors/DOOR1.png`; IDs pinned by CHR fingerprint in
  `hd/field/ids.json`.
- Walking characters: `hd/sprites/source/<ID>.png` (4x2 sheets), IDs in `hd/sprites/ids.json`.
- Battle monsters: `hd/monsters/source` + `mapping.json`, extras in `hd/monsters/extra/M###.png`.
- Title: layers in `hd/title/layers/` (sky+castle, plate, lettering, two cloud strips; `layout.json`), painted on
  the `tools/export_title_kit.py` guides. Blue-sky versions are recoloured at build time unless `*_day.png` exist.
- Endor casino: poker card sheets `hd/casino/cards/C01-C09.png` → one consistent deck composed from their
  parts (`deck.json`, `glyphs.png`; `tools/compose_deck.py`); slot machine `hd/casino/slots/SLOT.png` warped to
  the game's layout and reel symbols cut from its pay table (`layout.json`). Package: `tools/export_casino.py`;
  captures by warp: `capture_casino.py`, `capture_slots.py`.
- New art from OpenAI's image API goes through `tools/openai_sprites.py` with the export scripts
  (`export_chatgpt_sprites.py`, `export_gaps.py`); `.gitignore` has an `!` exception per art folder.
- All HD packs are authored at **10x** (`<scale>10`).

## HD pack mechanics worth knowing
- Mesen `hires.txt` format; keys are 16 CHR-RAM bytes + 4 palette colours. A passing conditional entry
  beats an unconditional one; `positionCheckX/Y` are per pixel in screen space.
- Project patches add: `memoryCheck` on WRAM (0007), `<options>spriteCells` (0009),
  `nametableColumn`/`nametableX` conditions (0010, for scrolling rows like the title clouds),
  `rgb:`/`rot:` tile transforms + shared decoded blocks (0011), read-only bundled mod packages (0012),
  `<background>` `line:Y` scroll + `wrap` (0013), Game Genie cheats (0014, `cyc_cheats.c`; launcher Cheats
  page = recomp-ui 0003; `cheats.txt` beside config.ini, `--cheats FILE` headless), faster multi-threaded
  compositing (0016: opaque-layer skipping, invisible-tile skip, bands on all cores; `NESRECOMP_HDPACK_THREADS`).
  The title is the heaviest screen: keep its layer count low and use fully opaque blocks where possible.
- Map tiles and characters: other palettes are affine recolours of the art (`rgb:` at load time); palettes that are only reorderings of each
  other (colour-cycling animations such as the overworld sea) share one recolour. Seamless smoothing
  is skipped where the painted edges differ (SEAM_MAX). Fades = the same art at lower brightness.
- Castle doors and the title are drawn straight into the nametable (no map tiles): see
  `capture_extras.py`, `door_frames.py`, `make_title_hdpack.py`.

## Editing a framework patch
1. `tools/apply_patches.sh` (restores touched files, applies every patch in order).
2. In the submodule: `git add -A runner && git stash create` → snapshot hash; `git reset -q`.
3. Edit, then `git add -A runner && git diff --cached <snapshot> > ../patches/nesrecomp/NNNN-name.patch && git reset -q`.
4. Re-run `tools/apply_patches.sh`, rebuild, test; before committing: `git -C nesrecomp checkout -- .`
   (and the same for `recomp-ui`) so the submodules stay pristine.
- `nesrecomp/runner/cyc/hw_ppu.c` uses CRLF line endings — edit it with `newline=''` / without converting.
- Keep HD save-state struct layouts unchanged (`cyc_hdpack_state.inc`): add fields only in padding.

## Conventions
- Commit messages end with the attribution lines given in the session; push to `main`.
- Checkpoint often (commit + update the project's STATUS doc); sessions can hit limits mid-task.
- Widescreen is deferred; no Scenario.
- Game facts (RAM addresses, banks, character table, intro timing) are in README.md and the
  project's STATUS doc — verify against the ROM/disassembly before relying on any.
