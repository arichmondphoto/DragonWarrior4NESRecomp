#!/usr/bin/env bash
# Build Dragon Warrior IV for Windows, on Linux (cross-compiled with MinGW-w64).
#
# Usage:  ./build_windows.sh [--native] [path/to/Dragon Warrior IV (USA).nes]
#
# Without a path the ROM is taken from rom/DragonWarriorIV.nes. The ROM stays
# on this machine: it is used to generate the game code and the HD pack, and
# is never put in the result.
#
# The build runs in a container (Podman or Docker, whichever is installed) on
# Debian 12 with MinGW-w64, so it works the same on any distro. The first run
# builds the container image (a few minutes); later runs reuse it.
#
# Result: dist/DragonWarriorIV-windows-x64-<version>.zip - a folder with
# DragonWarrior4.exe, its DLLs, the HD pack (switched on) and a read-me. It
# runs on 64-bit Windows 10 and 11. Saves and settings are kept in that folder.
# Try it here with Wine:  wine "build-windows/stage/Dragon Warrior IV/DragonWarrior4.exe"
#
# --native   build on this machine instead of in a container (needs cmake,
#            ninja, python >= 3.11, curl, perl and MinGW-w64 installed)
set -euo pipefail
cd "$(dirname "$0")"

EXPECTED_SHA1="1b3dc265ba0d7e4b2cef9b3f8b0be0847df67c3c"   # PRG+CHR, header excluded
IMAGE=dw4-windows-build

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

NATIVE=0; ROM_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --native) NATIVE=1 ;;
        -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
        -*) die "unknown option: $1" ;;
        *) ROM_ARG="$1" ;;
    esac
    shift
done

# --- sources and ROM (on the host) --------------------------------------------
command -v git >/dev/null 2>&1 || die "git is required"
say "Fetching nesrecomp and recomp-ui at their pinned commits"
git submodule update --init --recursive nesrecomp recomp-ui

mkdir -p rom
if [ -n "$ROM_ARG" ]; then
    [ -f "$ROM_ARG" ] || die "ROM not found: $ROM_ARG"
    cp "$ROM_ARG" rom/DragonWarriorIV.nes
fi
[ -f rom/DragonWarriorIV.nes ] || die "Put your ROM at rom/DragonWarriorIV.nes or pass its path: ./build_windows.sh \"/path/to/Dragon Warrior IV (USA).nes\""
ROM_SHA1="$(tail -c +17 rom/DragonWarriorIV.nes | sha1sum | cut -d' ' -f1)"
[ "$ROM_SHA1" = "$EXPECTED_SHA1" ] || die "This ROM doesn't match Dragon Warrior IV (USA) (SHA-1 $ROM_SHA1)."
echo "ROM OK (Dragon Warrior IV USA)"

# --- native build --------------------------------------------------------------
if [ "$NATIVE" = 1 ]; then
    missing=""
    for t in cmake ninja python3 curl perl cc c++; do command -v "$t" >/dev/null 2>&1 || missing="$missing $t"; done
    command -v x86_64-w64-mingw32-gcc-posix >/dev/null 2>&1 || command -v x86_64-w64-mingw32-gcc >/dev/null 2>&1 \
        || missing="$missing MinGW-w64"
    if [ -n "$missing" ]; then
        echo "Missing:$missing"
        echo "  Arch/Manjaro:  sudo pacman -S --needed base-devel cmake ninja python curl perl mingw-w64-gcc"
        echo "  Debian/Ubuntu: sudo apt install build-essential cmake ninja-build python3-venv curl perl g++-mingw-w64-x86-64-posix"
        echo "  Fedora:        sudo dnf install gcc-c++ cmake ninja-build python3 curl perl mingw64-gcc-c++ mingw64-winpthreads-static"
        die "install the tools above (or drop --native to build in a container)"
    fi
    bash windows/build_in_env.sh
    exit 0
fi

# --- container build -------------------------------------------------------------
if command -v podman >/dev/null 2>&1; then ENGINE=podman
elif command -v docker >/dev/null 2>&1; then ENGINE=docker
else
    die "Podman or Docker is needed for the container build.
  Arch/Manjaro:  sudo pacman -S podman
  Debian/Ubuntu: sudo apt install podman
  Fedora:        sudo dnf install podman
Or build on this machine with --native."
fi

say "Preparing the build container ($ENGINE; the first time takes a few minutes)"
"$ENGINE" build -t "$IMAGE" windows/

# Run as you, so everything the build writes (build-windows/, dist/) is yours.
if [ "$ENGINE" = podman ]; then USER_ARGS=(--userns=keep-id); else USER_ARGS=(--user "$(id -u):$(id -g)"); fi
say "Building in the container"
"$ENGINE" run --rm "${USER_ARGS[@]}" \
    -v "$PWD":/src:Z -w /src \
    -e HOME=/tmp/home -e DW4_NO_HD="${DW4_NO_HD:-0}" \
    "$IMAGE" bash -c 'mkdir -p "$HOME" && git config --global --add safe.directory "*" && windows/build_in_env.sh'

say "Done."
ls -1 dist/DragonWarriorIV-windows-*.zip 2>/dev/null | tail -1 | sed 's/^/  /'
echo "  Try it here:  wine \"build-windows/stage/Dragon Warrior IV/DragonWarrior4.exe\""
