#!/usr/bin/env bash
# The Linux build itself, run by build_linux.sh inside its container (or on
# the host with --native). From the repository root:
#
#   linux/build_in_env.sh            build + dist/Dragon_Warrior_IV-<ver>-<arch>.AppImage
#   DW4_RELEASE=1 linux/build_in_env.sh   ... and the player download
#                                     dist/DragonWarriorIV-linux-<arch>-<ver>.tar.gz
#                                     (the AppImage + READ ME FIRST.txt)
#
# Needs: a C/C++ toolchain, CMake >= 3.24, Ninja, Python >= 3.11 (venv), SDL2
# with its CMake config (SDL2_DIR), patchelf, curl. The ROM is at
# rom/DragonWarriorIV.nes (the game code and the HD pack are generated from
# it); it is never put in the AppImage.
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

RELEASE="${DW4_RELEASE:-0}"
JOBS="$(nproc)"
ARCH="$(uname -m)"
B=build-linux
EXE=DragonWarrior4
APP_ID=dragon-warrior-4
HD_ID="dragon-warrior-4.hd-text"
# One pack version for every platform: package_macos_app.sh holds it.
HD_VERSION="$(sed -n 's/^HD_VERSION="\(.*\)".*/\1/p' package_macos_app.sh | head -1)"
[ -n "$HD_VERSION" ] || die "HD_VERSION not found in package_macos_app.sh"
VERSION="1.0.$(git rev-list --count HEAD 2>/dev/null || echo 0)"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

[ -f rom/DragonWarriorIV.nes ] || die "rom/DragonWarriorIV.nes not found"

# --- game ---------------------------------------------------------------------
say "Applying framework fixes (patches/)"
tools/apply_patches.sh

say "Configuring (generates C from the ROM)"
cmake -S . -B "$B" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      ${SDL2_DIR:+-DSDL2_DIR="$SDL2_DIR"} \
      -DDW4_ROM="$PWD/rom/DragonWarriorIV.nes" ${DW4_CMAKE_ARGS:-}   # DW4_CMAKE_ARGS: extra -D options
say "Compiling ($JOBS jobs)"
cmake --build "$B" --parallel "$JOBS"
[ -x "$B/$EXE" ] || die "the build finished but $B/$EXE is missing"
readelf -d "$B/$EXE" | grep -q 'libSDL2' || die "SDL2 was not found, so the game was built without a window (set SDL2_DIR)"

# --- HD pack (generated from the ROM and the art in hd/; cached between builds) ---
VENV="$B/.hd-venv"
if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import PIL, numpy, scipy' 2>/dev/null; then
    say "Setting up Python for the HD pack"
    rm -rf "$VENV"
    if python3 -c 'import PIL, numpy, scipy' 2>/dev/null; then
        python3 -m venv --system-site-packages "$VENV"      # this Python already has them
    else
        python3 -m venv "$VENV"
        "$VENV/bin/pip" install --quiet --upgrade pip pillow numpy scipy
    fi
fi
PACK_DIR=""
if [ "${DW4_NO_HD:-0}" != 1 ]; then
    say "Building the HD pack (first time ~10-25 min; later builds reuse the captures)"
    tools/build_hd_pack.sh "$B/$EXE" "$B/hd/pack" "$VENV/bin/python" "$JOBS"
    NESMOD="$B/dw4-hd-$HD_VERSION.nesmod"
    rm -f "$NESMOD"
    "$VENV/bin/python" nesrecomp/tools/package_hdpack.py --pack "$B/hd/pack" --rom rom/DragonWarriorIV.nes \
        --game-id dragon-warrior-4 --id "$HD_ID" --version "$HD_VERSION" \
        --name "HD text, windows, monsters, maps, characters, title and casino" --author "DragonWarrior4NESRecomp" \
        --license "Personal use; generated from your ROM and your artwork" --notice "$B/hd/pack/NOTICE.txt" --out "$NESMOD"
    PACK_DIR="$NESMOD"
fi

# --- AppDir -------------------------------------------------------------------
say "Assembling the AppImage"
APPDIR="$B/AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib" "$APPDIR/usr/share/dragonwarrior4"
cp "$B/$EXE" "$APPDIR/usr/bin/$EXE"
[ -d "$B/assets" ] && cp -R "$B/assets" "$APPDIR/usr/bin/assets"   # the launcher finds them beside the program

# SDL2 travels with the game (everything else - C library, graphics drivers,
# X11/Wayland, sound servers - comes from the player's system).
SDL_LIB="$(ldd "$B/$EXE" | awk '/libSDL2-2.0.so.0/{print $3}')"
[ -f "$SDL_LIB" ] || die "can't find the libSDL2 the game links"
cp -L "$SDL_LIB" "$APPDIR/usr/lib/libSDL2-2.0.so.0"
# A distro's "SDL2" may be sdl2-compat, which loads SDL3 at run time: bring that too.
if grep -aq 'libSDL3.so' "$APPDIR/usr/lib/libSDL2-2.0.so.0"; then
    SDL3_LIB="$(ldconfig -p 2>/dev/null | awk '/libSDL3.so.0 /{print $NF; exit}')"
    [ -n "$SDL3_LIB" ] && [ -f "$SDL3_LIB" ] || die "this SDL2 is sdl2-compat and needs SDL3, but libSDL3.so.0 wasn't found"
    cp -L "$SDL3_LIB" "$APPDIR/usr/lib/libSDL3.so.0"
fi
chmod u+w "$APPDIR"/usr/lib/*.so*
patchelf --set-rpath '$ORIGIN/../lib' "$APPDIR/usr/bin/$EXE"
for l in "$APPDIR"/usr/lib/*.so*; do patchelf --set-rpath '$ORIGIN' "$l"; done

if [ -n "$PACK_DIR" ]; then
    DEST="$APPDIR/usr/share/dragonwarrior4/mods/packages/$HD_ID/$HD_VERSION"
    mkdir -p "$DEST"
    "$VENV/bin/python" -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$PACK_DIR" "$DEST"
fi

sed -e "s|@HD_ID@|$HD_ID|g" -e "s|@HD_VERSION@|$HD_VERSION|g" -e "s|@EXE@|$EXE|g" linux/AppRun > "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"
sed -e "s|@VERSION@|$VERSION|g" linux/dragon-warrior-4.desktop > "$APPDIR/$APP_ID.desktop"
"$VENV/bin/python" -c 'import sys; from PIL import Image; Image.open(sys.argv[1]).convert("RGBA").resize((256, 256), Image.LANCZOS).save(sys.argv[2])' \
    assets/icon_1024.png "$APPDIR/$APP_ID.png"
ln -sf "$APP_ID.png" "$APPDIR/.DirIcon"

# --- appimagetool (fetched once; run without FUSE so it works in containers) ---
TOOL="$B/tools/appimagetool-$ARCH.AppImage"
if [ ! -x "$TOOL" ]; then
    mkdir -p "$B/tools"
    curl -fsSL "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-$ARCH.AppImage" -o "$TOOL"
    chmod +x "$TOOL"
fi
mkdir -p dist
OUT="dist/Dragon_Warrior_IV-$VERSION-$ARCH.AppImage"
rm -f "$OUT"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH="$ARCH" "$TOOL" --no-appstream "$APPDIR" "$OUT" >/dev/null
chmod +x "$OUT"
say "AppImage: $OUT ($(du -h "$OUT" | cut -f1))"

# --- release: the AppImage with the player's read-me ----------------------------
if [ "$RELEASE" = 1 ]; then
    GLIBC="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')"; [ -n "$GLIBC" ] || GLIBC=unknown
    STAGE="$(mktemp -d)/Dragon Warrior IV"
    mkdir -p "$STAGE"
    cp "$OUT" "$STAGE/"
    sed -e "s|@VERSION@|$VERSION ($COMMIT)|g" -e "s|@ARCH@|$ARCH|g" -e "s|@GLIBC@|$GLIBC|g" \
        -e "s|@APPIMAGE@|$(basename "$OUT")|g" linux/READ_ME_FIRST.txt > "$STAGE/READ ME FIRST.txt"
    TAR="dist/DragonWarriorIV-linux-$ARCH-$VERSION.tar.gz"
    rm -f "$TAR"
    tar -C "$(dirname "$STAGE")" -czf "$TAR" "Dragon Warrior IV"
    say "Release package: $TAR ($(du -h "$TAR" | cut -f1))"
    echo "  for $ARCH Linux with glibc $GLIBC or newer. The ROM is not included."
fi
