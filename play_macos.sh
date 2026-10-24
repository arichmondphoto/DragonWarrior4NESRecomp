#!/usr/bin/env bash
# Start the windowed Dragon Warrior IV recomp built by build_macos.sh.
set -euo pipefail
cd "$(dirname "$0")/build"
[ -x ./DragonWarrior4 ] || { echo "Run ./build_macos.sh first." >&2; exit 1; }
exec ./DragonWarrior4 "$PWD/../rom/DragonWarriorIV.nes" "$@"
