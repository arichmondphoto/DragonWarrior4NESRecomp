# FUTURE.md — what's left, and how we decided to do it

The running to-do list for the project. Each item says what is wrong or
missing, how we know, and the approach we agreed on. Move an item to "Done"
(with the commit) when it ships. Day-to-day state and game facts stay in the
project's STATUS doc; this file is only the plan.

Last reviewed: 2026-11-13 (sweep findings fixed or explained, overscan trim, HD pack 0.15.0).

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
    tools/hd_coverage.py HOST MODS OUT battles    # each monster's battle played on, sampled every --every frames
    tools/hd_coverage.py HOST MODS OUT dusk       # the overworld at the four nightfall steps
    tools/hd_coverage.py HOST MODS OUT chars      # every walking character type (table patch), walking about
    tools/hd_coverage.py HOST MODS OUT report     # OUT/report.md, report.json, sheet_*.jpg

`maps --times N` samples each view N times (animated tiles). Sampled views
report the union of their samples' missing pieces and the worst frame.

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

### Second pass (2026-11-13, pack 0.14.0)

After items 1-3 below. The maps from the table above, sampled 3 times per
view: **maps 21, 40, 53, 62, 66 and 69 are clean.** Still in 8-bit there: the
map 18 fountain sparkle and the map 67 pillar base, both animation frames the
capture now finds but which have no art yet (item 4).

New checks:
- **Overworld nightfall** (4 palette steps, 26 samples each): clean.
- **Battles** (197 monsters, each played on for 320 frames, 21 samples):
  21 flagged. 10 were screen flashes, where the whole 8-bit screen is one flat
  colour (the check now ignores those). What's real:
  - ~~battles where another monster joins~~: a false alarm. The cells were
    blank tiles on the line where the game switches the battle backdrop's
    colour mid-screen; a blank tile looks the same either way. The check no
    longer counts blank tiles. One real crumb: a single cell of monster 138's
    spiked ball for a few frames late in its fade-in;
  - the Impostor's Transform (monster 153): the smoke-cloud sprites;
  - the Chapter 3 shop scene (173, known).
- **Walking characters** (108 types, 16 samples each): **all clean.** Three
  batches of 10 (the party heroes among them) overwrote the town's tile
  memory, garbling it even in 8-bit: an artefact of loading many big types
  into town people's slots. The check now re-runs such a batch one type at a
  time; every type alone is clean.

The map capture now also finds **13 animation-frame tiles with no art**:
T127-T128 (Endor), T129-T133 (the fountain in Izmit and Konenber), T134
(Konenber's pillar base), D358-D361 (Birdsong Tower), D362 (Loch Tower). The
build prints them with W036-W044 under "no art yet for".

**Still not covered by the sweep:** vehicles (ship, balloon, wagon), spells
the party casts (the Chapter 1 route's party casts none), damage-floor
flashes on other maps than the Final Cave (fixed generically, see Done), event scenes (cutscenes, the ending),
the Enix logo and title-to-game screens, the casino's slot win.

## Next up

### 4. Art for what is missing
**Done (pack 0.18.0, 2026-11-14):** the owner's art for everything the
package held is imported: map tiles M01 (`hd/field/sheets`), the demon
C069-C072 (`hd/sprites/source`, fit "ok"), the shop merchant
(`hd/monsters/extra/M173.png`, pipe-smoke rings removed so the figure fits),
the Transform smoke and sparkles (`hd/battle_effects`, `tools/make_effects_hdpack.py`).
Checked in a forced Impostor battle and the shop scene. **The Impostor's
Double stays 8-bit on purpose** (owner's choice: a nod to the original), so
coverage checks will flag it; that's expected.
Left: the overworld definitions W036-W044 are still printed under "no art yet"
but are never drawn. Endor crowd frames T128-T129 were regenerated (R01, facing the viewer) and C057
(a dragon drawn as four facings of one character) redone as one picture (C057W), pack 0.19.0. Party spells and cutscenes
are still unreached (chapter 1 save).

### 4b. Endor arena floor in the wrong colour: done (pack 0.20.0)
Palettes that turn the tile's hue more than 45 degrees are coloured by the
art's brightness (`rgbl:`, nesrecomp patch 0024) when that fits clearly better
(error under 0.64x the per-channel map's): 133 tile versions, checked by eye
(grey stone that came out pink or gold, snowy trees that came out purple, the
arena's sand). Above that ratio tiles mixing two hues (gold trim, orange grass
with blue dots) lost a hue, so they keep the per-channel map. The arena
floor's edge strips (top and right) still look more orange than the 8-bit.

### 4c. Tiles that don't blend: done (pack 0.24.0)
Shared ground, seamless repeats and the owner's matched-set repaints: P01-P06,
then every remaining seam tile in one package (381 tiles, Q01-Q18; the inn sign
T024 keeps its earlier painting via sheets.json "only"). Seams between
different tiles: 1.28M -> 1.07M by `tools/seam_check.py`; what it still counts
is mostly mortar lines and bush rims that sit on the tile border, which look
continuous. Closed: no more rounds.

### 5. Character art: done (pack 0.25.0)
Sparkle fields drawn as glows (C090, C091, C101); the waterfall C048 clipped to
the game's outline (`CLIP`); six characters checked by eye (`REVIEWED`).
Frames the game draws identically (statues and bosses that face front every
way, C075, C100, C060, C068 ...) now use one painting: the direction whose
paintings match the game's colours best (a back view was showing). Pieces
shared by both walking steps come from the step that matches best, so they
join their neighbours. The report now counts only pieces drawn with a
painting that doesn't fit their frame: 10 left, all harmless (plain water in
the waterfall, one piece just over the threshold).

## Later

### 6. Cheats page: codes that can't combine: done
Two enabled codes that replace the same cartridge byte (same address; one
without a compare value, or equal compare values) can't both work. The
launcher's Cheats page (recomp-ui patch 0005, rule in `launcher_cheats.h`,
`tests/launcher_cheats_test.cpp`): turning a code on or adding one turns the
codes it clashes with off and says which; clashing codes both on (cheats.txt
edited by hand) are marked in the list. Checked in the real launcher under
Xvfb (warning, click, add).
**Known codes (2026-11-17):** the Dragon's Den list as a built-in catalog
(`cheats/catalog.txt`, recomp-ui 0006, nesrecomp 0032) and an item picker for
every item and chapter character. Item names and the inventory table read from
the game (item menu for values 00-7E; bank 18 $9191, 8 bytes per character);
`tools/check_cheat_catalog.py` checks every entry.

### 6b. In-game menu (Esc): done (2026-11-17)
The arrow keys / D-pad seemed dead whenever the mouse pointer sat over the
menu (it put the selection back on the row under it every frame), clicks could
land on another row (mouse events came in the picture's logical units), and
rows that could not be used in game (the Controls list, the HD pack's
restart-only toggle) looked broken. The menu now holds only live settings
(README "In-game menu (Esc)"); VSync and the rewind settings were added, View
mode is called Widescreen as in the launcher. recomp-ui 0007, nesrecomp 0033.
Checked on Xvfb with XTest keys and clicks, HD pack loaded.
**Left:** the owner tries it with a controller (left stick, A / B).

### 6c. Shudder with VSync and the HD pack (2026-11-18)
Cause found: two clocks (the game's deadline and the display's blocking
present) dropping pictures; fixed by display-locked pacing (nesrecomp 0035).
Owner's log (Linux, 60 Hz, cheats on the interpreter): pictures took 11.6 ms
at 10x and a quarter were still dropped. 0036: the pack drawn at the display's
scale (7x there: half the work) and drops only when slow for a while.
**Left:** owner tries it; if a screen still shudders, run with
`NESRECOMP_PACING_LOG=1` there: "picture N ms" near or over 16 ms means the HD
picture itself is too slow on that screen (next step then: compose the HD
picture at the window's size instead of 10x, or upload only changed rows).
0037 (2026-11-18): the HD picture's work a third less (popcount table), MMC1
re-maps only on a CHR bank change, code cheats block only the 1 KB of compiled
code they touch, audio stretch up to 3% when the queue runs low. 0038: launcher
**HD detail** (Auto / Full / Balanced / Fast).
Owner (v1.0.158): worse than before: the sound slowed down and sped up with
the game, and the title (fine in 1.0.153) stuttered. Cause: 0035's locked
clock forgave lateness (the game slowed instead of catching up) and the
3% audio stretch made that audible. 0039: catch up by dropping pictures, as
the game clock always did; stretch at most 0.5%; 75 ms sound queue.
**Owner confirmed (v1.0.159): sound fixed, no more jitter.** Overlap HD
drawing is not needed for now; only worth revisiting if a screen shudders
again.
**Option offered, owner to decide after a new pacing log:** overlap HD drawing
(compose the next picture on another thread while the game runs the next
frame; +1 frame of display latency, about 17 ms).

### 7. Windows build
- **Done (untested on Windows):** `./build_windows.sh` cross-compiles on Linux
  with MinGW-w64 in a container (README "Build for Windows"). The owner keeps
  the ROM off GitHub, so no cloud build.
- **Builds** on the owner's Linux PC (2026-11-16, fd170da): compiled clean;
  fixes were only in the script (SDL2 setup file, pipefail check, DLL copy).
- Widescreen battle spiral checked by the owner in a dungeon battle (2026-11-17).
- **Left:** run check with Wine (launcher, HD on, sound/pad, widescreen,
  battery save + states, ROM remembered), then once on a real Windows PC.

### 8. Release polish
- The macOS app is ad-hoc signed: players need "Open Anyway". Removing that
  needs Apple notarization (paid developer account).
- macOS builds are Apple Silicon only (owner's decision: no Intel builds).
- The HD pack's licence line says "MIT License" (pack 0.28.0).
- Releases are created on GitHub's website (the cloud session can't create
  releases or push tags). The version is `1.0.<commit count>`: build both
  platforms from the same commit.

### 9. Smaller ideas
- Widescreen: see item 10.

### 10. Widescreen
- Done (phases 1-2): Widescreen Off / On (16:9) in the in-game menu, saved in
  config.ini; map sides drawn from the map, in 8-bit and HD (README
  "Widescreen (16:9)"); other screens pillarboxed.
- Done (phase 3): characters in the sides of towns, castles, dungeons and
  the overworld (the game's own draw rule, real facing, own walking progress),
  vehicles tested without a save (types pointed at wagon/ship/balloon); fades,
  the battle flash and spiral, damage flash; rooms, roofs and dark rooms;
  windows; map borders by pattern; plain fields; HD art in the sides of every
  area (README). 21:9 and Fit would exceed the 8192-pixel HD picture limit at 10x.
- **Title (2026-11-17): done.** The title goes on sideways in 16:9, in 8-bit
  (`title_sides`) and HD (sky 426 columns, nesrecomp 0034 keeps hires.txt
  positions native in wide pictures). The owner's wide sky and 512 px seamless
  cloud strips (`tools/export_title_ai.py` -> OpenAI -> `tools/import_title_ai.py`,
  joins cut along the rows' best seams) replace the old blended join. HD pack
  0.29.0. Optional: wider battle art.

## Done

- **2026-11-13 — Fades follow the NES colours; no title flash after battles.**
  The screen-fade steps of map tiles and walking characters were the art
  dimmed evenly; they are now the art recoloured to each step's own NES
  colours (deep blues and greens, darker colours going black first), applied
  while drawing (nesrecomp patch 0022, no extra memory). Pieces of the title
  art flashed on the first black frame after a battle: the title's layers now
  need the title's own RAM values. Text, windows and cursors (white art matched
  for any palette) now take the colour the game gives them, so they fade too
  and hidden text stays hidden (nesrecomp patch 0023). HD pack 0.16.0.
  Checked: every fade-up of the reference route, HD vs 8-bit per frame; the
  only difference left is approximation (stone whose main colour goes black
  first stays dark grey for 3 frames).

- **2026-11-13 — Full 256x240 picture without edge artifacts.** The game now
  shows the raw picture by default; the rows a TV's overscan hid (written late
  by the game, in stale colours) and the masked left column are drawn from the
  map: towns and dungeons from WRAM, the overworlds decoded from the ROM
  (`src/dw4_edges.c`, nesrecomp patch 0021). "Trim borders (overscan)" stays
  as an option, now off by default. Checked in 8-bit and HD on the reference
  route and in the Underworld.

- **2026-11-13 — Overscan trim, damage-floor flash, sweep false alarms.**
  The "Trim side borders" setting is now **Trim borders (overscan)** and
  also hides the top 8 and bottom 16 lines, where the game draws the next
  map row with half-updated colours (nesrecomp patch 0020, recomp-ui 0004;
  240x216 picture). Each step on a damage floor turns every background
  colour red for 3 frames; the map art is now drawn tinted red then instead
  of dropping to 8-bit (HD pack 0.15.0). The "window when a monster joins"
  and "odd character runs" findings were false alarms; `hd_coverage.py` now
  skips both.

- **2026-11-13 — Colour gaps, map 21's crowd, wider sweep.** HD pack 0.14.0.
  The map capture now lets the hero stand 2 seconds after each map loads and
  keeps every palette held 8+ frames (cycling lava), every later moment
  whose tile pictures are new (animated tiles: the Monbaraba crowd swaps
  poses every few frames, so day and night had each seen only one pose), and
  by day up to 3 more spots on large maps (colours that change by area: map
  40's lava corner, the sky castle). nesrecomp patch 0019 (`--palette-log`,
  `--mem-every`). `hd_coverage.py` gained `battles`, `dusk`, `chars` and
  `maps --times`. Results: "Second pass" above.

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
