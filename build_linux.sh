#!/usr/bin/env bash
# Build Dragon Warrior IV for Linux as an AppImage, on any distro.
#
# Usage:  ./build_linux.sh [--release] [--native] [path/to/Dragon Warrior IV (USA).nes]
#
# Without a path the ROM is taken from rom/DragonWarriorIV.nes.
#
# The build runs in a container (Podman or Docker, whichever is installed) on
# Debian 12, so it works the same on Manjaro, Fedora, Ubuntu, ..., and the
# AppImage runs on distros with glibc 2.36 or newer (2022 onward). The first
# run builds the container image (a few minutes); later runs reuse it.
#
# Result: dist/Dragon_Warrior_IV-<version>-<arch>.AppImage. It does not contain
# your ROM: pick it in the launcher (Browse For ROM) the first time. Saves and
# settings go to ~/.local/share/DragonWarrior4Recomp.
#
# --release  also packs the AppImage with a "READ ME FIRST.txt" for players as
#            dist/DragonWarriorIV-linux-<arch>-<version>.tar.gz
# --native   build on this machine instead of in a container (needs cmake,
#            ninja, python >= 3.11, SDL2 and patchelf installed; the AppImage
#            then needs a distro as new as this one)
set -euo pipefail
cd "$(dirname "$0")"

EXPECTED_SHA1="1b3dc265ba0d7e4b2cef9b3f8b0be0847df67c3c"   # PRG+CHR, header excluded
IMAGE=dw4-linux-build

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

RELEASE=0; NATIVE=0; ROM_ARG=""
while [ $# -gt 0 ]; do
    case "$1" in
        --release) RELEASE=1 ;;
        --native) NATIVE=1 ;;
        -h|--help) sed -n '2,24p' "$0"; exit 0 ;;
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
[ -f rom/DragonWarriorIV.nes ] || die "Put your ROM at rom/DragonWarriorIV.nes or pass its path: ./build_linux.sh \"/path/to/Dragon Warrior IV (USA).nes\""
ROM_SHA1="$(tail -c +17 rom/DragonWarriorIV.nes | sha1sum | cut -d' ' -f1)"
[ "$ROM_SHA1" = "$EXPECTED_SHA1" ] || die "This ROM doesn't match Dragon Warrior IV (USA) (SHA-1 $ROM_SHA1)."
echo "ROM OK (Dragon Warrior IV USA)"

# --- native build --------------------------------------------------------------
if [ "$NATIVE" = 1 ]; then
    missing=""
    for t in cmake ninja python3 patchelf curl pkg-config; do command -v "$t" >/dev/null 2>&1 || missing="$missing $t"; done
    pkg-config --exists sdl2 2>/dev/null || missing="$missing SDL2(dev)"
    if [ -n "$missing" ]; then
        echo "Missing:$missing"
        echo "  Arch/Manjaro:  sudo pacman -S --needed base-devel cmake ninja python sdl2 patchelf curl pkgconf"
        echo "  Debian/Ubuntu: sudo apt install build-essential cmake ninja-build python3-venv libsdl2-dev patchelf curl pkg-config"
        echo "  Fedora:        sudo dnf install gcc-c++ cmake ninja-build python3 SDL2-devel patchelf curl pkgconf"
        die "install the tools above (or drop --native to build in a container)"
    fi
    [ "$RELEASE" = 1 ] && echo "Note: a --native release runs only on distros as new as this one; the container build reaches more."
    DW4_RELEASE="$RELEASE" bash linux/build_in_env.sh
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
"$ENGINE" build -t "$IMAGE" linux/

# Run as you, so everything the build writes (build-linux/, dist/) is yours.
if [ "$ENGINE" = podman ]; then USER_ARGS=(--userns=keep-id); else USER_ARGS=(--user "$(id -u):$(id -g)"); fi
say "Building in the container"
"$ENGINE" run --rm "${USER_ARGS[@]}" \
    -v "$PWD":/src:Z -w /src \
    -e HOME=/tmp/home -e DW4_RELEASE="$RELEASE" -e DW4_NO_HD="${DW4_NO_HD:-0}" \
    "$IMAGE" bash -c 'mkdir -p "$HOME" && git config --global --add safe.directory "*" && linux/build_in_env.sh'

say "Done."
ls -1 dist/*.AppImage 2>/dev/null | tail -1 | sed 's/^/  /'
[ "$RELEASE" = 1 ] && ls -1 dist/*.tar.gz 2>/dev/null | tail -1 | sed 's/^/  /'
echo "  Run it:  ./dist/Dragon_Warrior_IV-*.AppImage   (your saves: ~/.local/share/DragonWarrior4Recomp)"
