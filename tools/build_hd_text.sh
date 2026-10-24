#!/usr/bin/env bash
# Generate the HD text pack (font, window borders, cursors) from your ROM.
#
#   tools/build_hd_text.sh HOST OUTDIR [PYTHON] [extra make_font_hdpack.py args]
#
# HOST is a headless or windowed build of this project (both accept the
# headless options used here). The game is driven along the Chapter 1 route
# to Burland castle, its CHR RAM is dumped, and every text/window tile is
# smoothly upscaled 4x. PYTHON must have Pillow (default: python3).
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="$1"; OUT="$2"; PY="${3:-python3}"; shift 2; [ $# -gt 0 ] && shift
[ -x "$HOST" ] || { echo "host not found: $HOST" >&2; exit 1; }
DUMP="$(mktemp -t dw4dump.XXXXXX)"
trap 'rm -f "$DUMP"' EXIT
# Frame 4200 of the route: the font and window tiles are loaded.
"$HOST" rom/DragonWarriorIV.nes --frames 4201 --no-save \
    --input routes/ch1_to_first_battles.txt \
    --mem-frame 4200 --mem-out "$DUMP" >/dev/null
"$PY" tools/make_font_hdpack.py "$DUMP" "$OUT" "$@"
cat > "$OUT/NOTICE.txt" <<'NOTE'
Dragon Warrior IV HD text pack: font, window borders and cursors, smoothly
upscaled 4x from the game's own 8x8 tiles by tools/make_font_hdpack.py.
Generated locally from the player's ROM; not for redistribution.
NOTE
