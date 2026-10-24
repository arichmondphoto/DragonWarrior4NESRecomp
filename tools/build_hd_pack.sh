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
