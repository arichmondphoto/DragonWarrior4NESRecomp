#!/usr/bin/env bash
# The Windows build itself, cross-compiled on Linux with MinGW-w64. Run by
# build_windows.sh inside its container (or on the host with --native). From
# the repository root:
#
#   windows/build_in_env.sh     -> dist/DragonWarriorIV-windows-x64-<ver>.zip
#
# Needs: a native C/C++ toolchain, MinGW-w64 (x86_64-w64-mingw32-gcc/g++,
# posix threads), CMake >= 3.24, Ninja, Python >= 3.11 (venv), curl, perl
# (shasum). The ROM is at rom/DragonWarriorIV.nes; it is never put in the zip.
#
# Steps:
#   1. a Linux headless build (build-win-host/): it supplies the recompiler,
#      which a cross build cannot run from itself, and it plays the game to
#      capture what the HD pack is keyed on (the pack is the same on every
#      platform)
#   2. SDL2 for MinGW (the official development release, fetched once)
#   3. the Windows build (build-windows/)
#   4. the zip: the game, its DLLs, assets, the HD pack switched on, read-me
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

JOBS="$(nproc)"
H=build-win-host
B=build-windows
EXE=DragonWarrior4
HD_ID="dragon-warrior-4.hd-text"
SDL_VERSION=2.30.12
MINGW=x86_64-w64-mingw32
HD_VERSION="$(sed -n 's/^HD_VERSION="\(.*\)".*/\1/p' package_macos_app.sh | head -1)"
[ -n "$HD_VERSION" ] || die "HD_VERSION not found in package_macos_app.sh"
VERSION="1.0.$(git rev-list --count HEAD 2>/dev/null || echo 0)"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

[ -f rom/DragonWarriorIV.nes ] || die "rom/DragonWarriorIV.nes not found"
command -v "$MINGW-gcc-posix" >/dev/null 2>&1 || command -v "$MINGW-gcc" >/dev/null 2>&1 \
    || die "MinGW-w64 ($MINGW-gcc) is not installed"

say "Applying framework fixes (patches/)"
tools/apply_patches.sh

# --- 1. Linux headless build -------------------------------------------------
say "Building the Linux helper (recompiler + headless game for the HD pack captures)"
cmake -S . -B "$H" -G Ninja -DCMAKE_BUILD_TYPE=Release -DNESRECOMP_HEADLESS=ON \
      -DDW4_ROM="$PWD/rom/DragonWarriorIV.nes"
cmake --build "$H" --parallel "$JOBS"
RECOMPILER="$PWD/$H/nesrecomp-host/NESRecomp"
[ -x "$RECOMPILER" ] || die "the helper build has no recompiler at $RECOMPILER"

# --- HD pack (generated from the ROM and the art in hd/; cached between builds) ---
VENV="$H/.hd-venv"
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import PIL, numpy, scipy' 2>/dev/null; then
    say "Setting up Python for the HD pack"
    rm -rf "$VENV"
    if python3 -c 'import PIL, numpy, scipy' 2>/dev/null; then
        python3 -m venv --system-site-packages "$VENV"
    else
        python3 -m venv "$VENV"
        "$VENV/bin/pip" install --quiet --upgrade pip pillow numpy scipy
    fi
fi
NESMOD=""
if [ "${DW4_NO_HD:-0}" != 1 ]; then
    say "Building the HD pack (first time ~10-25 min; later builds reuse the captures)"
    tools/build_hd_pack.sh "$H/$EXE" "$H/hd/pack" "$VENV/bin/python" "$JOBS"
    NESMOD="$H/dw4-hd-$HD_VERSION.nesmod"
    rm -f "$NESMOD"
    "$VENV/bin/python" nesrecomp/tools/package_hdpack.py --pack "$H/hd/pack" --rom rom/DragonWarriorIV.nes \
        --game-id dragon-warrior-4 --id "$HD_ID" --version "$HD_VERSION" \
        --name "HD text, windows, monsters, maps, characters, title and casino" --author "DragonWarrior4NESRecomp" \
        --license "Personal use; generated from your ROM and your artwork" --notice "$H/hd/pack/NOTICE.txt" --out "$NESMOD"
fi

# --- 2. SDL2 for MinGW --------------------------------------------------------
SDL_ROOT="$B/sdl2/SDL2-$SDL_VERSION/$MINGW"
if [ ! -f "$SDL_ROOT/lib/cmake/SDL2/SDL2Config.cmake" ]; then
    say "Fetching SDL2 $SDL_VERSION for MinGW"
    mkdir -p "$B/sdl2"
    curl -fsSL "https://github.com/libsdl-org/SDL/releases/download/release-$SDL_VERSION/SDL2-devel-$SDL_VERSION-mingw.tar.gz" \
        -o "$B/sdl2/sdl.tar.gz"
    tar -xzf "$B/sdl2/sdl.tar.gz" -C "$B/sdl2"
    rm -f "$B/sdl2/sdl.tar.gz"
fi
[ -f "$SDL_ROOT/lib/cmake/SDL2/SDL2Config.cmake" ] || die "SDL2's CMake files are missing under $SDL_ROOT"

# --- 3. Windows build ---------------------------------------------------------
say "Configuring the Windows build"
cmake -S . -B "$B" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_TOOLCHAIN_FILE="$PWD/windows/toolchain-mingw64.cmake" \
      -DSDL2_DIR="$PWD/$SDL_ROOT/lib/cmake/SDL2" \
      -DDW4_RECOMPILER="$RECOMPILER" \
      -DNESRECOMP_GAME_VERSION="$VERSION" -DNESRECOMP_BUILD_REVISION="$COMMIT" \
      -DDW4_ROM="$PWD/rom/DragonWarriorIV.nes" ${DW4_CMAKE_ARGS:-}
say "Compiling for Windows ($JOBS jobs)"
cmake --build "$B" --parallel "$JOBS"
[ -f "$B/$EXE.exe" ] || die "the build finished but $B/$EXE.exe is missing"
OBJDUMP="$(command -v "$MINGW-objdump" || command -v objdump)"
"$OBJDUMP" -p "$B/$EXE.exe" | grep -qi 'DLL Name: SDL2.dll' \
    || die "SDL2 was not found, so the game was built without a window (check SDL2_DIR)"

# --- 4. the zip ----------------------------------------------------------------
say "Assembling the Windows folder"
STAGE_ROOT="$B/stage"
STAGE="$STAGE_ROOT/Dragon Warrior IV"
rm -rf "$STAGE_ROOT"
mkdir -p "$STAGE"
cp "$B/$EXE.exe" "$STAGE/$EXE.exe"
[ -d "$B/assets" ] && cp -R "$B/assets" "$STAGE/assets"     # the launcher finds them beside the program
cp "$SDL_ROOT/bin/SDL2.dll" "$STAGE/"

# Any other DLL the program needs that Windows itself doesn't have (MinGW's
# thread library, for one) comes from the MinGW install.
SEARCH=("$SDL_ROOT/bin" /usr/$MINGW/bin /usr/$MINGW/lib /usr/lib/gcc/$MINGW/*-posix /usr/lib/gcc/$MINGW/*)
for dll in $("$OBJDUMP" -p "$B/$EXE.exe" | sed -n 's/.*DLL Name: //p' | tr -d '\r'); do
    [ -f "$STAGE/$dll" ] && continue
    for d in "${SEARCH[@]}"; do
        if [ -f "$d/$dll" ]; then cp "$d/$dll" "$STAGE/"; echo "  + $dll"; break; fi
    done
done

# The HD pack, switched on from the first run (Mods in the launcher turns it off).
if [ -n "$NESMOD" ]; then
    DEST="$STAGE/mods/packages/$HD_ID/$HD_VERSION"
    mkdir -p "$DEST"
    "$VENV/bin/python" -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$NESMOD" "$DEST"
    printf 'format_version = 1\n\n[[package]]\nid = "%s"\nversion = "%s"\n\n[[feature]]\npackage_id = "%s"\nid = "hd-pack"\nenabled = true\n' \
        "$HD_ID" "$HD_VERSION" "$HD_ID" > "$STAGE/mods/state.toml"
fi

# Read-me with Windows line endings (Notepad on older Windows needs them).
sed -e "s|@VERSION@|$VERSION ($COMMIT)|g" windows/READ_ME_FIRST.txt | sed 's/$/\r/' > "$STAGE/READ ME FIRST.txt"

mkdir -p dist
ZIP="dist/DragonWarriorIV-windows-x64-$VERSION.zip"
rm -f "$ZIP"
"$VENV/bin/python" - "$STAGE_ROOT" "$ZIP" <<'EOF'
import os, sys, zipfile
root, out = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for d, _, files in os.walk(root):
        for f in sorted(files):
            p = os.path.join(d, f)
            z.write(p, os.path.relpath(p, root))
EOF
say "Windows package: $ZIP ($(du -h "$ZIP" | cut -f1))"
echo "  The ROM is not included. Unzip, open the folder, run $EXE.exe."
echo "  To try it on this Linux machine:  wine \"$STAGE/$EXE.exe\""
