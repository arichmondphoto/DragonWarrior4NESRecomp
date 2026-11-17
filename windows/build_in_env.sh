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
        --license "MIT License" --notice "$H/hd/pack/NOTICE.txt" --out "$NESMOD"
fi

# --- 2. SDL2 for MinGW --------------------------------------------------------
SDL_TOP="$B/sdl2/SDL2-$SDL_VERSION"
SDL_ROOT="$SDL_TOP/$MINGW"
# SDL2's CMake setup: the one in the 64-bit tree (named sdl2-config.cmake or
# SDL2Config.cmake depending on the release). Not the release's top cmake/
# folder: that one chooses 32/64-bit by CMAKE_SIZEOF_VOID_P and reports "not
# found" whenever that isn't known at the time of the search.
sdl_cmake_dir() {
    for d in "$SDL_ROOT/lib/cmake/SDL2" "$SDL_TOP/cmake"; do
        if [ -f "$d/sdl2-config.cmake" ] || [ -f "$d/SDL2Config.cmake" ]; then echo "$d"; return 0; fi
    done
    return 1
}
if ! sdl_cmake_dir >/dev/null || [ ! -f "$SDL_ROOT/bin/SDL2.dll" ]; then
    say "Fetching SDL2 $SDL_VERSION for MinGW"
    rm -rf "$B/sdl2"
    mkdir -p "$B/sdl2"
    curl -fsSL "https://github.com/libsdl-org/SDL/releases/download/release-$SDL_VERSION/SDL2-devel-$SDL_VERSION-mingw.tar.gz" \
        -o "$B/sdl2/sdl.tar.gz"
    tar -xzf "$B/sdl2/sdl.tar.gz" -C "$B/sdl2"
    rm -f "$B/sdl2/sdl.tar.gz"
fi
SDL_CMAKE="$(sdl_cmake_dir)" || { echo "SDL2 download contents:" >&2; find "$B/sdl2" -maxdepth 4 -name '*.cmake' >&2;
    die "SDL2's CMake files are missing under $SDL_TOP"; }
[ -f "$SDL_ROOT/bin/SDL2.dll" ] || die "SDL2.dll is missing under $SDL_ROOT/bin"
echo "  SDL2: $SDL_CMAKE"

# --- 3. Windows build ---------------------------------------------------------
say "Configuring the Windows build"
rm -f "$B/CMakeCache.txt"     # a fresh look for SDL2 every time (a failed search is cached)
cmake -S . -B "$B" -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_TOOLCHAIN_FILE="$PWD/windows/toolchain-mingw64.cmake" \
      -DSDL2_DIR="$PWD/$SDL_CMAKE" \
      -DDW4_RECOMPILER="$RECOMPILER" \
      -DNESRECOMP_GAME_VERSION="$VERSION" -DNESRECOMP_BUILD_REVISION="$COMMIT" \
      -DDW4_ROM="$PWD/rom/DragonWarriorIV.nes" ${DW4_CMAKE_ARGS:-} 2>&1 | tee "$B/configure.log"
[ "${PIPESTATUS[0]}" = 0 ] || die "configuring the Windows build failed (see above)"
if grep -q "SDL2 not found" "$B/configure.log"; then
    echo "--- details for the bug report ---"
    grep -E "^(CMAKE_SIZEOF_VOID_P|SDL2_DIR|CMAKE_C_COMPILER):" "$B/CMakeCache.txt" || true
    grep -E "CMAKE_SIZEOF_VOID_P" "$B"/CMakeFiles/*/CMakeCCompiler.cmake 2>/dev/null || true
    ls "$SDL_CMAKE"
    cmake -S . -B "$B" --debug-find-pkg=SDL2 2>&1 | grep -A6 -E "not accepted|considered the following" | head -30
    die "SDL2 was not found when configuring (details above)"
fi
say "Compiling for Windows ($JOBS jobs)"
cmake --build "$B" --parallel "$JOBS"
[ -f "$B/$EXE.exe" ] || die "the build finished but $B/$EXE.exe is missing"
OBJDUMP="$(command -v "$MINGW-objdump" || command -v objdump)"
# (Read the whole list first: grep -q stopping early fails the pipe under pipefail.)
IMPORTS="$("$OBJDUMP" -p "$B/$EXE.exe" 2>&1 | grep -i 'DLL Name' || true)"
if ! grep -qi 'DLL Name: SDL2.dll' <<<"$IMPORTS"; then
    echo "--- details for the bug report ---"
    echo "objdump: $OBJDUMP"
    "$OBJDUMP" -p "$B/$EXE.exe" 2>&1 | grep -i -E "DLL Name|format" | head -30
    grep -c CYC_WITH_SDL "$B/build.ninja" || true
    die "the game doesn't use SDL2.dll, so it would have no window (details above)"
fi

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
# Windows' own DLLs stay out; any other one the program imports must be found.
WINDOWS_DLLS=" kernel32.dll user32.dll gdi32.dll shell32.dll ole32.dll oleaut32.dll comdlg32.dll advapi32.dll \
 ws2_32.dll opengl32.dll d2d1.dll dwrite.dll windowscodecs.dll msvcrt.dll ucrtbase.dll winmm.dll imm32.dll \
 version.dll setupapi.dll shlwapi.dll dbghelp.dll bcrypt.dll crypt32.dll iphlpapi.dll dwmapi.dll uxtheme.dll \
 hid.dll cfgmgr32.dll dinput8.dll xinput1_4.dll ntdll.dll "
missing=""
for dll in $(sed -n 's/.*DLL Name: //p' <<<"$IMPORTS" | tr -d '\r'); do
    lc="$(tr 'A-Z' 'a-z' <<<"$dll")"
    case "$WINDOWS_DLLS" in *" $lc "*) continue ;; esac
    case "$lc" in api-ms-win-*) continue ;; esac
    [ -f "$STAGE/$dll" ] && continue
    found=""
    for d in "${SEARCH[@]}"; do
        if [ -f "$d/$dll" ]; then cp "$d/$dll" "$STAGE/"; echo "  + $dll"; found=1; break; fi
    done
    [ -n "$found" ] || missing="$missing $dll"
done
[ -z "$missing" ] || die "the game needs DLLs that weren't found to include:$missing"

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
