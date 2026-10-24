#!/usr/bin/env bash
# Regenerate hd/font (the HD dialog font pack) from a running game.
#
#   tools/build_hd_font.sh [HOST] [FONT.ttf|otf]
#
# HOST is a headless or windowed build of this project (default:
# build-headless/nes_game). The game is driven along the Chapter 1 route to a
# dialog scene, its CHR RAM is dumped, and every glyph is re-rendered from
# FONT (default DejaVu Sans Mono Bold). Needs Python 3 with Pillow.
set -euo pipefail
cd "$(dirname "$0")/.."
HOST="${1:-build-headless/nes_game}"
FONT="${2:-/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf}"
[ -x "$HOST" ] || { echo "host not found: $HOST" >&2; exit 1; }
[ -f "$FONT" ] || { echo "font not found: $FONT" >&2; exit 1; }
mkdir -p out
# Frame 4200 of the route: Burland castle, the font and window tiles loaded.
"$HOST" rom/DragonWarriorIV.nes --frames 4201 --no-save \
    --input routes/ch1_to_first_battles.txt \
    --mem-frame 4200 --mem-out out/font_dump.txt >/dev/null
python3 tools/make_font_hdpack.py out/font_dump.txt hd/font --font "$FONT"
echo "Bump HD_FONT_VERSION in package_macos_app.sh when the pack changes."
