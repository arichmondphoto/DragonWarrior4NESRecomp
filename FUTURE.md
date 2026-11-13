# FUTURE.md — what's left, and how we decided to do it

The running to-do list for the project. Each item says what is wrong or
missing, how we know, and the approach we agreed on. Move an item to "Done"
(with the commit) when it ships. Day-to-day state and game facts stay in the
project's STATUS doc; this file is only the plan.

Last reviewed: 2026-11-12 (after release v1.0.71).

## How we check the HD pack

`NESRECOMP_HDPACK_DEBUG=1` paints every background pixel without HD art magenta
and every sprite pixel without HD art cyan. The review of 2026-11-12 played
`routes/ch1_to_first_battles.txt` (the first ~5 minutes of Chapter 1) that way
and counted, every 16th frame and every frame around screen changes, the 8x8
cells that are magenta where the original picture is not one flat colour.

Two traps when reading the result:
- black-on-black is not a gap: a blank cell, or a sprite faded to pure black,
  is flagged but shows nothing;
- a magenta cell under a sprite is the blank background behind it, not a
  missing piece of the sprite.

**The route covers only the start of Chapter 1.** Nothing after the first
battles has been measured.

## Next up

### 1. Coverage sweep of the whole game
- **Why:** we know of missing graphics only where someone has looked. Chapters
  2-5, the ship, balloon and wagon, spell and attack effects, the casino's slot
  win and the ending have never been measured.
- **How:** turn the review's scratch scripts into `tools/hd_coverage.py`
  (debug render + the 8-bit screenshot, cells counted as above, a contact
  sheet of the flagged frames). Then drive it three ways, none needing a
  playthrough:
  1. every map, by the warp `tools/capture_field.py` already uses (day and night);
  2. every monster formation, by `tools/force_formation.py`;
  3. every walking character type, by the table patch of `tools/capture_types.py`.
- **Result:** one list of every graphic still drawn in 8-bit, which decides
  items 2 and 3.

### 2. Art for what is missing
Known today:
- the Enix logo (sprites) and the copyright screen at power-on;
- "(" and ")" on the name-entry screen; the "-" there is drawn like "=" (check
  the glyph);
- 9 overworld tiles, W036-W044 (the build prints "no art yet for");
- 4 characters in Necrosaro's Lair, C069-C072.

Plus whatever item 1 finds.
- **How:** the same route as before. Export a package for OpenAI's image API
  (`tools/export_gaps.py`, `tools/openai_sprites.py`), the owner generates and
  returns the art, it is committed under `hd/` and the pack rebuilt. Text
  glyphs and the logo can be smoothed from the ROM instead (as the poker
  screen's digits are) if painted art isn't wanted.
- **Watch:** the pack is 188 MiB of the 256 MiB package limit.

### 3. Character art that doesn't line up
- **Why:** the sprite builder's fit report says "redo" for C007, C011, C043,
  C048, C062, C065, C090, C091, C092 and C101 (the art doesn't sit on the
  game's frames; C048, C091 and C101 are far off). 976 sprite pieces are shared
  between characters in a way the pack can't tell apart ("unresolved"), so the
  wrong character's piece, or the 8-bit one, can show.
- **How:** look at each "redo" sheet with `tools/review_sheet.py` and either
  re-fit or regenerate it. For the shared pieces, first measure how many are
  ever on screen together (item 1's character sweep); then widen the
  neighbour search in `tools/make_sprite_hdpack.py` or gate on the character
  slot (memoryCheck) for the ones that are.

## Later

### 4. Cheats page: warn about codes that can't combine
- **Why:** two codes that patch the same address can't both apply (the last one
  wins), which looked like "only one code works". All the "Start with ..."
  gold codes share one address, the HP codes another, and so on.
- **How:** in the launcher's Cheats page (recomp-ui patch 0003) mark enabled
  codes that decode to the same address, with a one-line explanation. Decide
  then whether ticking one should untick the other.

### 5. Windows build
- **Why:** asked about, not started. The owner builds on macOS; the result must
  run on Windows.
- **How:** cross-compile with MinGW-w64 from the Mac (or try it first in the
  cloud sandbox, which has the same compiler). Known work: a toolchain file;
  whatever MinGW rejects in code written for Visual Studio; a Windows version
  of the multi-threaded compositing (patch 0016 is pthread-only and falls back
  to one core); `mods/state.toml` shipped in the zip so the HD pack starts on;
  a Windows read-me (SmartScreen: "More info > Run anyway"). Testing needs a
  Windows PC or VM.

### 6. Release polish
- The macOS app is ad-hoc signed: players need "Open Anyway". Removing that
  needs Apple notarization (paid developer account).
- macOS builds are Apple Silicon only; Intel or universal needs a universal
  SDL2.
- The HD pack's own licence line says "Personal use; generated from your ROM"
  while the repository is public under MIT. Decide what the pack's line should
  say. The downloads contain ROM-derived material (recompiled code, graphics
  upscaled from ROM tiles) even though the ROM itself is not included.
- Releases are created on GitHub's website (the cloud session can't create
  releases or push tags). The version is `1.0.<commit count>`: build both
  platforms from the same commit.

### 7. Smaller ideas
- Capture a slot-machine win (lamp and palette blinks) and check it in HD.
- A setting to trim the top and bottom edges like the side trim, for players
  who want the TV-style picture; the edge fix below makes it optional.
- Widescreen: see item 8.

### 8. Widescreen (deferred by decision; this is the suggested method)
- **What the engine gives us:** nesrecomp already has wide picture modes
  (`cyc_video.h`: 16:9 = 426 px wide, 21:9 = 560, or fit the window) and a
  per-game "compositor" hook (`cyc_render.h`): the game keeps drawing its
  256x240 picture, and our code paints the extra columns left and right, or
  returns "pillarbox this screen". Nothing feeds back into the game, so it
  cannot break gameplay or saves. The HD pack path knows nothing about it yet.
- **Why the game can't just show more:** the console's off-screen tile memory
  only holds stale columns; the game writes each new column just before it
  scrolls in. But the game keeps the whole decoded map in memory (WRAM `$7800`
  map cells, `$7600` the 32 map tiles' four 8x8 pieces, `$76C0` their
  palettes - the data `capture_field.py` and the scratch `maprender.py`
  already read), so the margins can be drawn from the map itself.
- **Method, in phases (each one is usable on its own):**
  1. *8-bit wide maps.* A compositor for towns, dungeons and the overworld:
     from the camera position and the map in WRAM, draw the extra map columns
     each side with the game's own tiles and palettes (night and fades come
     free: they are just the current palette). Past the map's edge use the
     map's border tile; the overworld wraps. Every other screen (title, battles,
     menus-only screens, casino, name entry) is pillarboxed and centred;
     battles are on black, so their side bars are invisible.
  2. *HD in the margins.* A project patch so the compositor hands the HD
     presenter the margin as tile cells (the 8x8 tile's bytes + palette), the
     same record the presenter gets for on-screen tiles. The pack then matches
     them with the entries it already has: no new art for maps.
  3. *People in the margins.* The game only makes sprites for characters near
     the screen. Read the map's character table and draw the ones standing in
     the margins (position, type, facing, walk frame) with the pack's character
     art; find out whether they keep moving off-screen or freeze until they
     come near.
  4. *Wide art for fixed screens (optional).* The title's layers painted wider;
     a framed or wider battle backdrop. Needs new art from the owner.
- **Known hard parts:** map-change effects (fades are fine; any wipe or
  shake would need the margins to follow); doors, chests and other tiles the
  game changes on screen must be read from the live map, not the ROM; windows
  and text stay in the middle 256 columns; rewind and save states are
  unaffected (the compositor only reads). More pixels per frame: at 16:9 the HD
  frame is 4260x2400, about 1.7x the compositing work of today.
- **First step when we start:** phase 1 for one town, headless, compared
  against `maprender.py`'s picture of the same map. That proves the camera
  maths before anything else is built.

## Done

- **2026-11-12 — Monsters fade in as 8-bit, then pop to HD.** At the start of
  a battle the game brings the monsters up from black in three colour steps;
  the pack had entries only for the final colours. `tools/make_monster_hdpack.py`
  now writes a copy of every monster entry per fade step, drawn at the
  matching brightness. HD pack 0.13.0.
- **2026-11-12 — 8-bit strip at the top/bottom edge while the map scrolls.**
  The game draws each new row of map tiles at the edge one step before their
  colours, in the lines a TV's overscan hid; those tiles matched no pack entry.
  nesrecomp patch 0018 (`<options>edgePaletteFallback`): an unmatched
  background tile in the top 16 / bottom 24 lines is looked up again with the
  screen's other palettes, so its HD art is drawn. HD pack 0.13.0.
- **Checked and not a bug:** characters "missing" for ~3 frames at each map
  change (they are pure black on a black screen at that fade step); one
  "missing" cell on the Giant Worm (blank background behind its sprite).
