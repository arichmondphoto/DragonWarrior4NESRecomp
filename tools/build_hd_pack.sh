#!/usr/bin/env bash
# Generate the complete HD pack (text, windows, battle monsters) from your ROM.
#
#   tools/build_hd_pack.sh HOST OUTDIR [PYTHON] [JOBS]
#
# HOST is a headless or windowed build of this project. PYTHON needs Pillow,
# NumPy and SciPy. Steps:
#   1. text + window tiles (tools/build_hd_text.sh, smoothed from the ROM)
#   2. capture every battle monster from the running game
#      (tools/capture_monsters.py, cached in OUTDIR/../monster-capture)
#      and Necrosaro's eight forms (tools/capture_necrosaro.py, driving the
#      real transformations; cached in OUTDIR/../monster-capture/necro)
#   3. the owner's monster art (hd/monsters/) sliced and keyed onto the
#      captured tiles (tools/make_monster_hdpack.py)
#   4. map tiles (hd/field/) and walking characters (hd/sprites/), keyed onto
#      every map and every character type captured from the game
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="$1"; OUT="$2"; PY="${3:-python3}"; JOBS="${4:-4}"
[ -x "$HOST" ] || { echo "host not found: $HOST" >&2; exit 1; }

echo "  text and windows"
rm -rf "$OUT"
tools/build_hd_text.sh "$HOST" "$OUT" "$PY"

CAP="$(dirname "$OUT")/monster-capture"
STAMP="$CAP/.stamp"
want="$(shasum "$HOST" rom/DragonWarriorIV.nes routes/ch1_to_first_battles.txt tools/capture_monsters.py tools/capture_necrosaro.py 2>/dev/null | shasum | cut -d' ' -f1)"
if [ ! -f "$STAMP" ] || [ "$(cat "$STAMP")" != "$want" ]; then
    echo "  capturing battle monsters from the game (one forced battle each)"
    rm -rf "$CAP"
    "$PY" tools/capture_monsters.py "$HOST" "$CAP" --jobs "$JOBS"
    echo "  capturing Necrosaro's forms (one driven boss battle)"
    "$PY" tools/capture_necrosaro.py "$HOST" "$CAP/necro"
    echo "$want" > "$STAMP"
else
    echo "  battle monsters: using cached capture"
fi

echo "  battle monsters"
"$PY" tools/make_monster_hdpack.py "$CAP" "$OUT" --report "$(dirname "$OUT")/monster-report.json"
cat >> "$OUT/NOTICE.txt" <<'NOTE'

Battle monsters: the project owner's artwork (hd/monsters/source), fitted
and sliced onto the game's own monster tiles by tools/make_monster_hdpack.py.
NOTE

# ---- title screen and castle door animation (captured from the route) ----
XCAP="$(dirname "$OUT")/extra-capture"
xwant="$(shasum "$HOST" rom/DragonWarriorIV.nes routes/ch1_to_first_battles.txt tools/capture_extras.py 2>/dev/null | shasum | cut -d' ' -f1)"
if [ ! -f "$XCAP/.stamp" ] || [ "$(cat "$XCAP/.stamp")" != "$xwant" ]; then
    echo "  capturing the title screen and the castle door animation"
    rm -rf "$XCAP"
    "$PY" tools/capture_extras.py "$HOST" "$XCAP"
    echo "$xwant" > "$XCAP/.stamp"
fi

# ---- map tiles (towns, castles, dungeons, overworld) ---------------------
for js in hd/field/source/*.json; do
    [ -e "$js" ] || continue
    [ -f "${js%.json}.png" ] || { echo "ERROR: map-tile atlas ${js%.json}.png is missing (git pull?)" >&2; exit 1; }
done
FCAP="$(dirname "$OUT")/field-capture"
if ls hd/field/source/*.png >/dev/null 2>&1; then
    FSTAMP="$FCAP/.stamp"
    fwant="$(shasum "$HOST" rom/DragonWarriorIV.nes routes/ch1_to_first_battles.txt tools/capture_field.py 2>/dev/null | shasum | cut -d' ' -f1)"
    if [ ! -f "$FSTAMP" ] || [ "$(cat "$FSTAMP")" != "$fwant" ]; then
        echo "  capturing every map from the game (warping into each of 279 areas, day and night; several minutes)"
        rm -rf "$FCAP"
        "$PY" tools/capture_field.py "$HOST" "$FCAP/maps" --jobs "$JOBS"
        echo "  capturing every map again at night"
        "$PY" tools/capture_field.py "$HOST" "$FCAP/maps" --jobs "$JOBS" --night
        "$PY" tools/field_sheet.py "$FCAP/maps" "$FCAP" --json-only
        echo "$fwant" > "$FSTAMP"
    else
        echo "  maps: using cached capture"
    fi
    echo "  map tiles"
    rm -rf "$FCAP/art"
    "$PY" tools/slice_field_atlases.py "$FCAP/art"
    # sheets generated with the API (tools/export_chatgpt_tiles.py) replace atlas art per tile
    "$PY" tools/slice_field_sheets.py "$FCAP/field_tiles.json" "$FCAP/art"
    # the castle doors' in-between frames, as extra map tiles (hd/field/doors)
    "$PY" tools/door_frames.py "$FCAP/field_tiles.json" "$XCAP/doors.json" "$FCAP/art" "$FCAP/field_tiles_all.json"
    "$PY" tools/make_field_hdpack.py "$FCAP/field_tiles_all.json" "$FCAP/art" "$OUT" --report "$(dirname "$OUT")/field-report.json"
    cat >> "$OUT/NOTICE.txt" <<'NOTE'

Map tiles: the project owner's artwork (hd/field/source atlases), cut per
8x8 tile and keyed onto the game's own map tiles by tools/make_field_hdpack.py.
NOTE
fi

# ---- title screen ---------------------------------------------------------
if [ -f hd/title/layers/layout.json ]; then
    echo "  title screen"
    "$PY" tools/make_title_hdpack.py "$XCAP" "$OUT"
    cat >> "$OUT/NOTICE.txt" <<'NOTE'

Title screen: the project owner's artwork in layers (hd/title/layers/), drawn
by tools/make_title_hdpack.py.
NOTE
fi

# ---- Endor casino: the poker table (captured by warping to it) -------------
CCAP="$(dirname "$OUT")/casino-capture"
cwant="$(shasum "$HOST" rom/DragonWarriorIV.nes routes/ch1_to_first_battles.txt tools/capture_casino.py 2>/dev/null | shasum | cut -d' ' -f1)"
if [ ! -f "$CCAP/.stamp" ] || [ "$(cat "$CCAP/.stamp")" != "$cwant" ]; then
    echo "  capturing the Endor casino's poker table"
    rm -rf "$CCAP"
    "$PY" tools/capture_casino.py "$HOST" "$CCAP"
    echo "$cwant" > "$CCAP/.stamp"
fi
echo "  casino"
"$PY" tools/make_casino_hdpack.py "$CCAP" "$OUT"
cat >> "$OUT/NOTICE.txt" <<'NOTE'

Endor casino: the poker cards are the project owner's artwork (hd/casino/cards);
the poker screen's other tiles are smoothly upscaled from your ROM.
NOTE

# ---- walking characters (party, townspeople, animals, ships, ...) ---------
if ls hd/sprites/source/C*.png >/dev/null 2>&1; then
    [ -f "$FCAP/.stamp" ] || { echo "ERROR: characters need the map capture (hd/field/source art)" >&2; exit 1; }
    SCAP="$(dirname "$OUT")/sprite-capture"
    SSTAMP="$SCAP/.stamp"
    swant="$(shasum "$HOST" rom/DragonWarriorIV.nes routes/ch1_to_first_battles.txt tools/capture_types.py 2>/dev/null | shasum | cut -d' ' -f1)"
    if [ ! -f "$SSTAMP" ] || [ "$(cat "$SSTAMP")" != "$swant" ]; then
        echo "  capturing every character type (the game's character table, 11 runs)"
        rm -rf "$SCAP"
        "$PY" tools/capture_types.py "$HOST" "$SCAP/types" --jobs "$JOBS"
        echo "$swant" > "$SSTAMP"
    else
        echo "  characters: using cached capture"
    fi
    echo "  characters"
    "$PY" tools/sprite_sheet.py "$FCAP/maps" "$SCAP" --types "$SCAP/types" --json-only
    rm -rf "$SCAP/fit"
    "$PY" tools/check_ai_sprites.py hd/sprites/source "$SCAP/characters.json" "$SCAP/fit" > "$SCAP/fit-report.txt"
    "$PY" tools/make_sprite_hdpack.py "$SCAP/characters.json" "$SCAP/fit/fitted_full" "$FCAP/maps" "$OUT" \
        --report "$(dirname "$OUT")/sprite-report.json"
    cat >> "$OUT/NOTICE.txt" <<'NOTE'

Walking characters: the project owner's artwork (hd/sprites/source), fitted
to the game's own character sprites and keyed per 8x8 sprite by
tools/make_sprite_hdpack.py.
NOTE
fi
