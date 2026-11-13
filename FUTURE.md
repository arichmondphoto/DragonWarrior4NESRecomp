# FUTURE.md — what's left, and how we decided to do it

The running to-do list for the project. Each item says what is wrong or
missing, how we know, and the approach we agreed on. Move an item to "Done"
(with the commit) when it ships. Day-to-day state and game facts stay in the
project's STATUS doc; this file is only the plan.

Last reviewed: 2026-11-13 (whole-game coverage sweep, HD pack 0.13.0).

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

`tools/hd_coverage.py` does this for the whole game without a playthrough:

    tools/hd_coverage.py HOST MODS OUT maps       # every submap, day + night, up to 3 extra viewpoints
    tools/hd_coverage.py HOST MODS OUT monsters   # every monster ID, settled and mid fade-in
    tools/hd_coverage.py HOST MODS OUT report     # OUT/report.md, report.json, sheet_*.jpg

(HOST = the headless build, MODS = a mod root with the pack installed and
on.) It also names each missing piece by its tile bytes and colours, so the
fix can be traced. A full run is about 3 hours on 2 cores and resumes if
stopped.

## Coverage sweep results (2026-11-13, pack 0.13.0)

1,222 views: 828 map views (279 areas, day and night, spread viewpoints) and
394 battle frames (197 monsters, settled and mid fade-in). 18 views still show
something in 8-bit; 0 failed. **Monsters are fully covered**, fade-in
included. What is left, grouped by cause:

| Where | What shows in 8-bit | Cause |
|---|---|---|
| Map 40 (outdoor area with orange ground) | almost all the ground (666 cells) | ordinary overworld tiles W017/W018 drawn in cycling lava colours (`0F062616`, `0F261606`) the map capture never saw |
| Map 53 sub 2 (a cave) | most of the floor and walls (594 cells) | known dungeon tiles in an all-red palette (`0F161616`): a flash or damage-floor effect caught mid-way |
| Map 69 subs 2-3 | strip of orange ground at the bottom | same lava colours as map 40 |
| Map 62 (castle in the sky) | the sky and the throne structure (34 cells) | known tiles (D233-D239, D100, S064) in colours (`0F001016`, `0F303C12`) not captured |
| Map 21 sub 3 (hall full of a crowd) | many crowd figures (76 cells by day, 146 at night) | the crowd tiles (T112, T113, T117) *were* captured in these exact colours, yet don't match: the pack's neighbour rules for the dense crowd fail; needs a closer look |
| Map 66 sub 2 | a golden statue | not in the map capture |
| Map 67 | the base of a golden pillar (4 cells) | not in the map capture (likely an animation frame) |
| Map 18 (a town) | one sparkle in the fountain | not in the map capture (water animation frame) |
| Chapter 3 shop scene (forcing "monster" 173) | the big picture of Torneko behind the counter | a special screen; needs art |

**Not covered by the sweep yet:** walking characters other than the ones
on each map at load (party members, vehicles: ship, balloon, wagon), the
overworld's dusk steps (W036-W044 are night-only overworld tiles), spell and
attack effects, event scenes (cutscenes, the ending), the Enix logo and
title-to-game screens, the casino's slot win.

## Next up

### 1. Fix the colour gaps (no new art)
- **Why:** most of the sweep's findings are tiles that have art but appear in
  colours the build never captured (maps 40, 53, 62, 69).
- **How:** in `tools/capture_field.py`, keep sampling each map for a few
  seconds after it loads and record every background palette it shows
  (cycling lava, flashes, sky effects), not just the one at the capture
  frame; `make_field_hdpack.py` then makes the recolours for all of them
  (it already shares one recolour between palettes that are reorderings of
  each other). Re-run the sweep on those maps to confirm.

### 2. Map 21's crowd
- **Why:** captured tiles in the right colours still don't match (see table).
- **How:** dump the cells with `hd_coverage.py --only 21:3`, compare each
  cell's neighbours with the `tileNearby` conditions the night-crowd sheet
  (`hd/field/sheets/N01`) generated, and loosen or extend them.

### 3. Widen the sweep
- Walking characters and vehicles: a mode using `tools/capture_types.py`'s
  table patch (needs the pack to load with a patched ROM:
  `NESRECOMP_ALLOW_PRG_MISMATCH`), or warps with each party member leading.
- The overworld at each dusk step (`capture_field.py`'s nightfall walk).
- Spell effects: forced battles where the party casts (a battle input script).
- Animation frames: sample each map over several seconds (fountains, pillars,
  flames), the same change as item 1.

### 4. Art for what is missing
Known today:
- the Enix logo (sprites) and the copyright screen at power-on;
- "(" and ")" on the name-entry screen; the "-" there is drawn like "=" (check
  the glyph);
- 9 overworld tiles, W036-W044 (the build prints "no art yet for");
- 4 characters in Necrosaro's Lair, C069-C072;
- from the sweep: the Chapter 3 shop scene (Torneko behind the counter), the
  map 66 golden statue, the map 67 pillar base and the map 18 fountain
  sparkle (the last three may only need capturing, see item 1).

Plus whatever the widened sweep (item 3) finds.
- **How:** the same route as before. Export a package for OpenAI's image API
  (`tools/export_gaps.py`, `tools/openai_sprites.py`), the owner generates and
  returns the art, it is committed under `hd/` and the pack rebuilt. Text
  glyphs and the logo can be smoothed from the ROM instead (as the poker
  screen's digits are) if painted art isn't wanted.
- **Watch:** the pack is 188 MiB of the 256 MiB package limit.

### 5. Character art that doesn't line up
- **Why:** the sprite builder's fit report says "redo" for C007, C011, C043,
  C048, C062, C065, C090, C091, C092 and C101 (the art doesn't sit on the
  game's frames; C048, C091 and C101 are far off). 976 sprite pieces are shared
  between characters in a way the pack can't tell apart ("unresolved"), so the
  wrong character's piece, or the 8-bit one, can show.
- **How:** look at each "redo" sheet with `tools/review_sheet.py` and either
  re-fit or regenerate it. For the shared pieces, first measure how many are
  ever on screen together (item 3's character sweep); then widen the
  neighbour search in `tools/make_sprite_hdpack.py` or gate on the character
  slot (memoryCheck) for the ones that are.

## Later

### 6. Cheats page: warn about codes that can't combine
- **Why:** two codes that patch the same address can't both apply (the last one
  wins), which looked like "only one code works". All the "Start with ..."
  gold codes share one address, the HP codes another, and so on.
- **How:** in the launcher's Cheats page (recomp-ui patch 0003) mark enabled
  codes that decode to the same address, with a one-line explanation. Decide
  then whether ticking one should untick the other.

### 7. Windows build
- **Why:** asked about, not started. The owner builds on macOS; the result must
  run on Windows.
- **How:** cross-compile with MinGW-w64 from the Mac (or try it first in the
  cloud sandbox, which has the same compiler). Known work: a toolchain file;
  whatever MinGW rejects in code written for Visual Studio; a Windows version
  of the multi-threaded compositing (patch 0016 is pthread-only and falls back
  to one core); `mods/state.toml` shipped in the zip so the HD pack starts on;
  a Windows read-me (SmartScreen: "More info > Run anyway"). Testing needs a
  Windows PC or VM.

### 8. Release polish
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

### 9. Smaller ideas
- Capture a slot-machine win (lamp and palette blinks) and check it in HD.
- A setting to trim the top and bottom edges like the side trim, for players
  who want the TV-style picture; the edge fix below makes it optional.
- Widescreen: see item 10.

### 10. Widescreen (deferred by decision; this is the suggested method)
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

- **2026-11-13 — Whole-game coverage sweep.** `tools/hd_coverage.py` (maps by
  warp, monsters by forced battle, merged report). Results above.

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
