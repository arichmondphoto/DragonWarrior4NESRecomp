#!/usr/bin/env bash
# Package build/DragonWarrior4 into "Dragon Warrior IV.app" and install it.
#
# Usage:  ./package_macos_app.sh [--no-install] [--dest DIR]
#
# Run after build_macos.sh (which calls this automatically). The app is
# written to dist/ and, unless --no-install, copied to /Applications
# (or ~/Applications when /Applications isn't writable).
#
# The app is self-contained: the game, its SDL2 library, the launcher's
# fonts/images, the HD pack and your ROM are inside it. Settings, battery saves and save
# states live in ~/Library/Application Support/DragonWarrior4Recomp, so
# reinstalling or rebuilding the app never touches your progress.
#
# The app contains your ROM. Don't share it.
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Dragon Warrior IV"
BUNDLE_ID="local.recomp.dragonwarrior4"
EXE=DragonWarrior4
DATA_DIR_NAME="DragonWarrior4Recomp"
DATA_DIR="$HOME/Library/Application Support/$DATA_DIR_NAME"

INSTALL=1; DEST=""
while [ $# -gt 0 ]; do
    case "$1" in
        --no-install) INSTALL=0 ;;
        --dest) DEST="$2"; shift ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

[ -x "build/$EXE" ] || die "build/$EXE not found. Run ./build_macos.sh first."
[ -f rom/DragonWarriorIV.nes ] || die "rom/DragonWarriorIV.nes not found."
# Framework fixes (patches/) newer than the game build: rebuild the game first,
# or the app (and the HD pack's capture tools) would run the old engine.
if [ -n "$(find patches -name '*.patch' -newer "build/$EXE" 2>/dev/null)" ]; then
    say "Engine fixes changed since the last build: rebuilding the game"
    tools/apply_patches.sh
    cmake --build build --parallel "$(sysctl -n hw.ncpu)" || die "Rebuild failed; run ./build_macos.sh"
fi

VERSION="1.0.$(git rev-list --count HEAD 2>/dev/null || echo 0)"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

APP="dist/$APP_NAME.app"
C="$APP/Contents"
say "Assembling $APP (version $VERSION, $COMMIT)"
rm -rf "$APP"
mkdir -p "$C/MacOS" "$C/Resources" "$C/Frameworks"

# --- game binary, launcher assets, ROM ------------------------------------
cp "build/$EXE" "$C/MacOS/$EXE"
[ -d build/assets ] && cp -R build/assets "$C/Resources/assets"
cp rom/DragonWarriorIV.nes "$C/Resources/DragonWarriorIV.nes"


# --- launch script: run from the data folder ------------------------------
# config.ini, the battery save (saves/*.sav) and mods/ are created in the
# working directory, so start the game there.
cat > "$C/MacOS/launch" <<EOF
#!/bin/bash
DATA="\$HOME/Library/Application Support/$DATA_DIR_NAME"
mkdir -p "\$DATA/saves" "\$DATA/diagnostics"
cd "\$DATA" || exit 1
export NESRECOMP_DIAGNOSTICS_DIR="\$DATA/diagnostics"
HERE="\$(cd "\$(dirname "\$0")" && pwd)"
export NESRECOMP_BUNDLED_MODS="\$HERE/../Resources/mods"   # the HD pack inside the app
exec "\$HERE/$EXE" "\$HERE/../Resources/DragonWarriorIV.nes" "\$@"
EOF
chmod +x "$C/MacOS/launch"

# --- bundle non-system libraries (Homebrew SDL2 and anything it pulls in) --
say "Bundling libraries"
is_external() { case "$1" in /opt/homebrew/*|/usr/local/*|@rpath/*) return 0 ;; *) return 1 ;; esac; }
resolve_dep() {   # resolve @rpath entries against Homebrew's lib dir
    case "$1" in
        @rpath/*) local n="${1#@rpath/}"; for d in "$(brew --prefix)/lib" "$(brew --prefix sdl2)/lib"; do [ -f "$d/$n" ] && { echo "$d/$n"; return; }; done; echo "" ;;
        *) echo "$1" ;;
    esac
}
fix_deps() {   # $1 = Mach-O file inside the bundle
    local file="$1" dep src name
    otool -L "$file" | tail -n +2 | awk '{print $1}' | while read -r dep; do
        is_external "$dep" || continue
        src="$(resolve_dep "$dep")"; [ -n "$src" ] && [ -f "$src" ] || die "can't find library $dep needed by $file"
        name="$(basename "$src")"
        if [ ! -f "$C/Frameworks/$name" ]; then
            cp -L "$src" "$C/Frameworks/$name"; chmod u+w "$C/Frameworks/$name"
            install_name_tool -id "@executable_path/../Frameworks/$name" "$C/Frameworks/$name"
            fix_deps "$C/Frameworks/$name"
        fi
        install_name_tool -change "$dep" "@executable_path/../Frameworks/$name" "$file"
        echo "  $name"
    done
}
fix_deps "$C/MacOS/$EXE"

# Homebrew's "sdl2" is sdl2-compat: libSDL2 is a shim that dlopen()s SDL3 at
# runtime, so SDL3 never shows up in otool -L. sdl2-compat looks first for
# @loader_path/libSDL3.dylib, i.e. beside itself in Contents/Frameworks.
if [ -f "$C/Frameworks/libSDL2-2.0.0.dylib" ] && grep -aq 'libSDL3' "$C/Frameworks/libSDL2-2.0.0.dylib"; then
    SDL3_SRC=""
    for cand in "$(brew --prefix sdl3 2>/dev/null)/lib/libSDL3.0.dylib" "$(brew --prefix)/lib/libSDL3.0.dylib" "$(brew --prefix)/lib/libSDL3.dylib"; do
        [ -f "$cand" ] && { SDL3_SRC="$cand"; break; }
    done
    [ -n "$SDL3_SRC" ] || die "SDL2 here is sdl2-compat, which needs SDL3, but libSDL3 wasn't found (try: brew install sdl3)"
    cp -L "$SDL3_SRC" "$C/Frameworks/libSDL3.dylib"; chmod u+w "$C/Frameworks/libSDL3.dylib"
    install_name_tool -id "@loader_path/libSDL3.dylib" "$C/Frameworks/libSDL3.dylib"
    fix_deps "$C/Frameworks/libSDL3.dylib"
    echo "  libSDL3.dylib (loaded at runtime by sdl2-compat)"
fi

# Remove any LC_RPATH entries pointing back into Homebrew.
otool -l "$C/MacOS/$EXE" | awk '/LC_RPATH/{r=1} r&&/path /{print $2; r=0}' | while read -r rp; do
    is_external "$rp" && install_name_tool -delete_rpath "$rp" "$C/MacOS/$EXE" || true
done
if otool -L "$C/MacOS/$EXE" "$C"/Frameworks/*.dylib 2>/dev/null | grep -E '/opt/homebrew|/usr/local' ; then
    die "the app still references Homebrew libraries (listed above)"
fi

# --- icon -----------------------------------------------------------------
say "Building icon"
ICONSET="$(mktemp -d)/AppIcon.iconset"; mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
    sips -z $s $s assets/icon_1024.png --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z $((s*2)) $((s*2)) assets/icon_1024.png --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$C/Resources/AppIcon.icns"

# --- Info.plist -----------------------------------------------------------
cat > "$C/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>$APP_NAME</string>
    <key>CFBundleDisplayName</key><string>$APP_NAME</string>
    <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
    <key>CFBundleExecutable</key><string>launch</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>$VERSION</string>
    <key>CFBundleVersion</key><string>$VERSION</string>
    <key>CFBundleGetInfoString</key><string>NESRecomp build $COMMIT</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.role-playing-games</string>
    <key>LSMinimumSystemVersion</key><string>11.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>NSSupportsAutomaticGraphicsSwitching</key><true/>
</dict>
</plist>
EOF

# --- HD pack (text, windows, battle monsters) --------------------------------
# Generated from your ROM: the game's own text and window tiles smoothly
# upscaled, plus your monster art (hd/monsters) sliced onto the monsters the
# game draws (captured by forcing one battle per monster; cached between
# builds). Bundled inside the app (Contents/Resources/mods, laid out like the
# Mods catalog; the launch script points NESRECOMP_BUNDLED_MODS at it, patch
# 0012), so it is replaced with the app and nothing is copied into your
# Library folder. Its on/off setting stays in your Mods catalog (state.toml),
# so it carries over between versions; on a new Mac turn it on once in the
# launcher (Mods > HD text, windows, monsters, maps, characters and title).
# Set DW4_NO_HD=1 to skip.
HD_ID="dragon-warrior-4.hd-text"
HD_VERSION="0.10.0"
if [ "${DW4_NO_HD:-0}" != 1 ]; then
    say "Generating the HD pack from your ROM (text, windows, monsters, maps)"
    PYB="$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"; [ -x "$PYB" ] || PYB=python3
    VENV=build/.hd-venv
    if [ ! -x "$VENV/bin/python" ] || ! "$VENV/bin/python" -c 'import PIL, numpy, scipy' 2>/dev/null; then
        "$PYB" -m venv "$VENV"
        "$VENV/bin/pip" install --quiet --upgrade pip pillow numpy scipy
    fi
    tools/build_hd_pack.sh "build/$EXE" build/hd/pack "$VENV/bin/python" "$(sysctl -n hw.ncpu)"
    NESMOD="dist/dw4-hd-$HD_VERSION.nesmod"
    rm -f "$NESMOD"
    "$VENV/bin/python" nesrecomp/tools/package_hdpack.py --pack build/hd/pack --rom rom/DragonWarriorIV.nes \
        --game-id dragon-warrior-4 --id "$HD_ID" --version "$HD_VERSION" \
        --name "HD text, windows, monsters, maps, characters and title" --author "DragonWarrior4NESRecomp" \
        --license "Personal use; generated from your ROM and your artwork" --notice build/hd/pack/NOTICE.txt --out "$NESMOD"
    DEST_PKG="$C/Resources/mods/packages/$HD_ID/$HD_VERSION"
    rm -rf "$C/Resources/mods"; mkdir -p "$DEST_PKG"
    "$VENV/bin/python" -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$NESMOD" "$DEST_PKG"
    # Earlier builds installed the pack into the Mods catalog; the bundled copy
    # replaces it (and the old DejaVu font proof of concept).
    rm -rf "$DATA_DIR/mods/packages/$HD_ID" "$DATA_DIR/mods/packages/dragon-warrior-4.hd-font"
    echo "  $DEST_PKG"
fi

# --- signing (ad-hoc; required on Apple Silicon after editing load paths) ---
say "Signing (ad-hoc)"
for f in "$C"/Frameworks/*.dylib; do [ -e "$f" ] && codesign --force --sign - "$f"; done
codesign --force --sign - "$C/MacOS/$EXE"
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "  signature OK"

# Save-state slots are written to "<SDL base dir>/saves", which for an app is
# Contents/Resources. Point that at the user's data folder so states sit beside
# the battery save and survive reinstalling. Added after signing because
# codesign refuses symlinks that leave the bundle; the binary's signature is
# unaffected, and a locally built (non-quarantined) app is not re-assessed.
mkdir -p "$DATA_DIR/saves"
ln -s "$DATA_DIR/saves" "$C/Resources/saves"

# --- carry over progress from the old build/ folder (first time only) -------
if [ -f build/config.ini ] && [ ! -f "$DATA_DIR/config.ini" ]; then
    cp build/config.ini "$DATA_DIR/config.ini"; echo "Copied settings from build/config.ini"
fi
if [ -d build/saves ]; then
    for f in build/saves/*; do
        [ -e "$f" ] || continue
        b="$(basename "$f")"
        [ -e "$DATA_DIR/saves/$b" ] || { cp "$f" "$DATA_DIR/saves/$b"; echo "Copied save $b"; }
    done
fi

# --- install --------------------------------------------------------------
if [ "$INSTALL" = 1 ]; then
    if [ -z "$DEST" ]; then
        if [ -w /Applications ]; then DEST=/Applications; else DEST="$HOME/Applications"; fi
    fi
    mkdir -p "$DEST"
    say "Installing to $DEST"
    rm -rf "$DEST/$APP_NAME.app"
    ditto "$APP" "$DEST/$APP_NAME.app"
    # Refresh Launchpad/Finder's view of the app and its icon.
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$DEST/$APP_NAME.app" >/dev/null 2>&1 || true
    touch "$DEST/$APP_NAME.app"
    echo "Installed: $DEST/$APP_NAME.app"
else
    echo "App written to $APP"
fi
echo "Your settings and saves: $DATA_DIR"
