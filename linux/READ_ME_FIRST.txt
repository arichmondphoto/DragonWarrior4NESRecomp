Dragon Warrior IV for Linux - version @VERSION@
================================================

A native Linux version of Dragon Warrior IV (NES), with HD graphics, as a
single AppImage file.
The game itself is NOT included: you need your own ROM file of
Dragon Warrior IV (USA) for the NES (a .nes file).

Requirements: a @ARCH@ PC with a desktop Linux from about 2022 or newer
(glibc @GLIBC@ or newer) - Ubuntu, Fedora, Arch, Manjaro, Mint, openSUSE,
SteamOS desktop mode, ... X11 and Wayland both work.


1. Install
----------
Unpack the download and put "@APPIMAGE@" wherever you keep
programs (for example ~/Applications). Then make it executable:

  - In your file manager: right-click it > Properties > Permissions >
    tick "Allow executing file as program" (or "Is executable").
  - Or in a terminal:  chmod +x @APPIMAGE@

Double-click it to start. (Optional: tools such as Gear Lever or
AppImageLauncher add it to your applications menu.)


2. Add your ROM
---------------
The launcher opens. Click "Browse For ROM" and choose your
Dragon Warrior IV (USA) .nes file. The launcher checks that it is the
right game and remembers it, so you only do this once. Then press PLAY.

Or, if you prefer: put the .nes file in the game's data folder (below);
the game finds it there by itself.


Playing
-------
Keyboard: arrow keys = D-pad, Z = A, X = B, Return = Start, \ = Select.
Gamepads work out of the box; change controls in the launcher.
Esc = menu, F7 = save states, F8 = rewind, Tab = fast-forward,
F11 = full screen.

HD graphics are switched on. To play with the original graphics, open
"Mods" in the launcher and turn the HD pack off.

Cheats: the launcher's "Cheats" page takes Game Genie codes.

Steam Deck: in desktop mode, add the AppImage to Steam as a non-Steam
game to play it from Game Mode.


Your saves and settings
-----------------------
Everything you save is kept outside the AppImage, in this folder:

  ~/.local/share/DragonWarrior4Recomp

(It is a hidden folder: press Ctrl+H in most file managers to see it.)
The game's save (its three adventure logs) is saves/DragonWarriorIV.sav;
save states, settings (config.ini) and cheats (cheats.txt) are there too.

To update to a new version, replace the AppImage. Your saves and settings
stay. Back up that folder to keep your progress safe.


If it doesn't start
-------------------
- "Permission denied" or nothing happens: make it executable (step 1).
- A message about FUSE: run it once from a terminal with
    ./@APPIMAGE@ --appimage-extract-and-run
  or install your distro's "fuse" (FUSE 2) package.
- Browse For ROM shows its own simple file list instead of your desktop's
  file picker when neither "zenity" nor "kdialog" is installed; it works
  either way.
