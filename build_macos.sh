#!/usr/bin/env bash
# Build the windowed Dragon Warrior IV recomp on macOS (Apple Silicon or Intel).
#
# Usage:  ./build_macos.sh [path/to/Dragon Warrior IV (USA).nes]
#
# Without an argument the ROM is taken from rom/DragonWarriorIV.nes.
# The result is build/DragonWarrior4, packaged as "Dragon Warrior IV.app" and
# installed in /Applications (see package_macos_app.sh).
set -euo pipefail
cd "$(dirname "$0")"

EXPECTED_SHA1="1b3dc265ba0d7e4b2cef9b3f8b0be0847df67c3c"   # PRG+CHR, header excluded

say()  { printf '\n==> %s\n' "$*"; }
die()  { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# 1. Toolchain -------------------------------------------------------------
say "Checking Xcode command line tools"
xcode-select -p >/dev/null 2>&1 || {
    xcode-select --install || true
    die "Install the Xcode command line tools from the dialog that just opened, then run this script again."
}

say "Checking Homebrew"
if ! command -v brew >/dev/null 2>&1; then
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
fi
command -v brew >/dev/null 2>&1 || die "Homebrew is required. Install it from https://brew.sh, then run this script again."

say "Installing build dependencies (cmake, ninja, sdl2, python)"
for pkg in cmake ninja sdl2 python@3.12; do
    brew list --formula "$pkg" >/dev/null 2>&1 || brew install "$pkg"
done
PY="$(brew --prefix python@3.12)/bin/python3.12"
[ -x "$PY" ] || die "python3.12 not found at $PY"

# 2. Sources ---------------------------------------------------------------
say "Fetching nesrecomp (with its netplay libraries) and recomp-ui at their pinned commits"
git submodule update --init --recursive nesrecomp recomp-ui

# 3. ROM -------------------------------------------------------------------
mkdir -p rom
if [ $# -ge 1 ]; then
    [ -f "$1" ] || die "ROM not found: $1"
    cp "$1" rom/DragonWarriorIV.nes
fi
[ -f rom/DragonWarriorIV.nes ] || die "Put your ROM at rom/DragonWarriorIV.nes or pass its path: ./build_macos.sh \"/path/to/Dragon Warrior IV (USA).nes\""
ROM_SHA1="$(tail -c +17 rom/DragonWarriorIV.nes | shasum -a 1 | cut -d' ' -f1)"
[ "$ROM_SHA1" = "$EXPECTED_SHA1" ] || die "This ROM doesn't match Dragon Warrior IV (USA) (SHA-1 $ROM_SHA1)."
echo "ROM OK (Dragon Warrior IV USA)"

# 4. Build -----------------------------------------------------------------
say "Configuring (generates C from the ROM; takes a minute)"
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
      -DCMAKE_PREFIX_PATH="$(brew --prefix)" \
      -DPython3_EXECUTABLE="$PY" \
      -DDW4_ROM="$PWD/rom/DragonWarriorIV.nes"

say "Compiling"
cmake --build build --parallel "$(sysctl -n hw.ncpu)"

[ -x build/DragonWarrior4 ] || die "Build finished but build/DragonWarrior4 is missing."

# 5. Package -----------------------------------------------------------------
# Builds "Dragon Warrior IV.app" and installs it in /Applications.
# Set DW4_NO_APP=1 to skip, or DW4_NO_INSTALL=1 to leave the app in dist/.
if [ "${DW4_NO_APP:-0}" != 1 ]; then
    if [ "${DW4_NO_INSTALL:-0}" = 1 ]; then ./package_macos_app.sh --no-install; else ./package_macos_app.sh; fi
    say "Done. Open \"Dragon Warrior IV\" from Applications or Launchpad."
else
    say "Done. Start the game with:  ./play_macos.sh"
fi
