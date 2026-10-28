#!/usr/bin/env bash
# Package build/DragonWarrior4 into "Dragon Warrior IV.app" and install it.
#
# Usage:  ./package_macos_app.sh [--no-install] [--dest DIR] [--release]
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
#
# --release makes a shareable download instead: the same app WITHOUT the ROM
# (the player picks their own in the launcher on first launch), zipped with a
# "READ ME FIRST.txt" (installing, opening an app from outside the App Store,
# adding the ROM) as dist/DragonWarriorIV-macOS-<arch>-<version>.zip. It is
# not installed. It runs on Macs of the build machine's architecture and on
# the oldest macOS its libraries allow (both are written in the read-me).
set -euo pipefail
cd "$(dirname "$0")"

APP_NAME="Dragon Warrior IV"
BUNDLE_ID="local.recomp.dragonwarrior4"
EXE=DragonWarrior4
DATA_DIR_NAME="DragonWarrior4Recomp"
DATA_DIR="$HOME/Library/Application Support/$DATA_DIR_NAME"

INSTALL=1; DEST=""; RELEASE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --no-install) INSTALL=0 ;;
        --dest) DEST="$2"; shift ;;
        --release) RELEASE=1; INSTALL=0 ;;
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
HD_ID="dragon-warrior-4.hd-text"
HD_VERSION="0.12.0"     # bump whenever the pack's content changes (the Mods catalog keys on it)
SAVE_NAME="DragonWarriorIV"   # battery save / save states: saves/DragonWarriorIV.*, whatever the ROM file is called
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"

APP="dist/$APP_NAME.app"
C="$APP/Contents"
say "Assembling $APP (version $VERSION, $COMMIT)"
rm -rf "$APP"
mkdir -p "$C/MacOS" "$C/Resources" "$C/Frameworks"

# --- game binary, launcher assets, ROM (not in a release) -----------------
cp "build/$EXE" "$C/MacOS/$EXE"
[ -d build/assets ] && cp -R build/assets "$C/Resources/assets"
[ "$RELEASE" = 1 ] || cp rom/DragonWarriorIV.nes "$C/Resources/DragonWarriorIV.nes"


# --- launch script: run from the data folder ------------------------------
# config.ini, the battery save (saves/*.sav), mods/, rom.cfg and cheats.txt
# live in the working directory, so start the game there. Save states go to
# the same saves/ folder (patch 0015), under a fixed name.
# The ROM: the one inside the app (your own build), else the one the launcher
# remembers (rom.cfg, written when the player picks it with Browse For ROM),
# else a .nes file the player put in the data folder, else none: the launcher
# then asks for it.
cat > "$C/MacOS/launch" <<EOF
#!/bin/bash
DATA="\$HOME/Library/Application Support/$DATA_DIR_NAME"
mkdir -p "\$DATA/saves" "\$DATA/diagnostics" "\$DATA/mods"
cd "\$DATA" || exit 1
export NESRECOMP_DIAGNOSTICS_DIR="\$DATA/diagnostics"
export NESRECOMP_SAVE_NAME="$SAVE_NAME"
export NESRECOMP_STATE_DIR="\$DATA/saves"
HERE="\$(cd "\$(dirname "\$0")" && pwd)"
export NESRECOMP_BUNDLED_MODS="\$HERE/../Resources/mods"   # the HD pack inside the app
# First run: the HD pack starts switched on (Mods in the launcher turns it off).
if [ ! -f mods/state.toml ] && [ -d "\$NESRECOMP_BUNDLED_MODS/packages/$HD_ID/$HD_VERSION" ]; then
    printf 'format_version = 1\\n\\n[[package]]\\nid = "%s"\\nversion = "%s"\\n\\n[[feature]]\\npackage_id = "%s"\\nid = "hd-pack"\\nenabled = true\\n' \\
        "$HD_ID" "$HD_VERSION" "$HD_ID" > mods/state.toml
fi
ROM=""
if [ -f "\$HERE/../Resources/DragonWarriorIV.nes" ]; then
    ROM="\$HERE/../Resources/DragonWarriorIV.nes"
elif [ -f rom.cfg ] && [ -f "\$(head -n 1 rom.cfg)" ]; then
    ROM="\$(head -n 1 rom.cfg)"
else
    for f in "\$DATA"/*.nes "\$DATA"/*.NES; do [ -f "\$f" ] && { ROM="\$f"; break; }; done
fi
exec "\$HERE/$EXE" \${ROM:+"\$ROM"} "\$@"
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

# The oldest macOS the app runs on: the newest minimum among the game and the
# libraries bundled with it (Homebrew builds them for this Mac's macOS).
MIN_MACOS="$(otool -l "$C/MacOS/$EXE" "$C"/Frameworks/*.dylib 2>/dev/null | awk '/minos /{print $2}' | sort -t. -k1,1n -k2,2n | tail -1)"
[ -n "$MIN_MACOS" ] || MIN_MACOS=11.0
ARCHS="$(lipo -archs "$C/MacOS/$EXE" 2>/dev/null || uname -m)"

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
    <key>LSMinimumSystemVersion</key><string>$MIN_MACOS</string>
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
# launcher (Mods > HD text, windows, monsters, maps, characters, title and casino).
# Set DW4_NO_HD=1 to skip.
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
        --name "HD text, windows, monsters, maps, characters, title and casino" --author "DragonWarrior4NESRecomp" \
        --license "Personal use; generated from your ROM and your artwork" --notice build/hd/pack/NOTICE.txt --out "$NESMOD"
    DEST_PKG="$C/Resources/mods/packages/$HD_ID/$HD_VERSION"
    rm -rf "$C/Resources/mods"; mkdir -p "$DEST_PKG"
    "$VENV/bin/python" -c 'import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])' "$NESMOD" "$DEST_PKG"
    # Earlier builds installed the pack into the Mods catalog; the bundled copy
    # replaces it (and the old DejaVu font proof of concept).
    [ "$RELEASE" = 1 ] || rm -rf "$DATA_DIR/mods/packages/$HD_ID" "$DATA_DIR/mods/packages/dragon-warrior-4.hd-font"
    echo "  $DEST_PKG"
fi

# --- signing (ad-hoc; required on Apple Silicon after editing load paths) ---
say "Signing (ad-hoc)"
for f in "$C"/Frameworks/*.dylib; do [ -e "$f" ] && codesign --force --sign - "$f"; done
codesign --force --sign - "$C/MacOS/$EXE"
codesign --force --sign - "$APP"
codesign --verify --deep --strict "$APP" && echo "  signature OK"

# --- release: zip the app (no ROM) with the player's read-me -----------------
if [ "$RELEASE" = 1 ]; then
    if find "$APP" -iname '*.nes' | grep -q .; then die "the release app contains a ROM"; fi
    ARCH_TAG="$(echo "$ARCHS" | tr ' ' '-')"
    case "$ARCHS" in
        *arm64*x86_64*|*x86_64*arm64*) MACS="any Mac (Apple Silicon or Intel)" ;;
        *arm64*) MACS="a Mac with Apple Silicon (M1 or later); Intel Macs are not supported" ;;
        *) MACS="an Intel Mac" ;;
    esac
    ZIP="dist/DragonWarriorIV-macOS-$ARCH_TAG-$VERSION.zip"
    STAGE="$(mktemp -d)/Dragon Warrior IV"
    mkdir -p "$STAGE"
    ditto "$APP" "$STAGE/$APP_NAME.app"
    sed -e "s|@VERSION@|$VERSION ($COMMIT)|g" -e "s|@MACS@|$MACS|g" -e "s|@MINOS@|$MIN_MACOS|g" \
        -e "s|@DATA@|$DATA_DIR_NAME|g" -e "s|@SAVE@|$SAVE_NAME|g" \
        release/READ_ME_FIRST.txt > "$STAGE/READ ME FIRST.txt"
    rm -f "$ZIP"
    ditto -c -k --sequesterRsrc --keepParent "$STAGE" "$ZIP"
    say "Release package: $ZIP"
    echo "  for $MACS, macOS $MIN_MACOS or later; $(du -h "$ZIP" | cut -f1)"
    echo "  The ROM is not included: players add their own (see READ ME FIRST.txt)."
    exit 0
fi

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
