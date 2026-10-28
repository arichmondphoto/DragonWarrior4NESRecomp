Dragon Warrior IV for macOS - version @VERSION@
================================================

A native Mac version of Dragon Warrior IV (NES), with HD graphics.
The game itself is NOT included: you need your own ROM file of
Dragon Warrior IV (USA) for the NES (a .nes file).

Requirements: @MACS@, macOS @MINOS@ or later.


1. Install
----------
Unzip the download (double-click it) and drag "Dragon Warrior IV.app"
into your Applications folder.


2. Open it the first time
-------------------------
This app is not from the App Store, so macOS asks you to confirm it once:

  a. Double-click "Dragon Warrior IV" in Applications. macOS says it
     cannot verify the app. Click "Done" (or "Cancel").
  b. Open System Settings > Privacy & Security, scroll down to
     "Security" and click "Open Anyway" next to "Dragon Warrior IV".
     Confirm with your password or Touch ID.
  c. Open the app again and click "Open Anyway" (or "Open").

After that it opens normally.

On older macOS versions you can instead right-click (or Control-click)
the app, choose "Open", then "Open" again.

If macOS says the app "is damaged and can't be opened", open Terminal
(Applications > Utilities) and paste this line, then press Return:

  xattr -dr com.apple.quarantine "/Applications/Dragon Warrior IV.app"


3. Add your ROM
---------------
The launcher opens. Click "Browse For ROM" and choose your
Dragon Warrior IV (USA) .nes file, wherever it is on your Mac. The
launcher checks that it is the right game and remembers it, so you only
do this once. Then press PLAY.

Or, if you prefer: put the .nes file in the game's data folder (below);
the app finds it there by itself.

Please do NOT put the ROM inside the app ("Show Package Contents"):
changing anything inside the app breaks its signature, and macOS will
then refuse to open it.


Playing
-------
Keyboard: arrow keys = D-pad, Z = A, X = B, Return = Start, \ = Select.
Gamepads work out of the box; change controls in the launcher.
Esc = menu, F7 = save states, F8 = rewind, Tab = fast-forward,
F11 = full screen (on a Mac keyboard you may need fn + the F-key).

HD graphics are switched on. To play with the original graphics, open
"Mods" in the launcher and turn the HD pack off.

Cheats: the launcher's "Cheats" page takes Game Genie codes.


Your saves and settings
-----------------------
Everything you save is kept outside the app, in this folder:

  ~/Library/Application Support/@DATA@

(In Finder: Go > Go to Folder..., paste the line above, press Return.)
The game's save (its three adventure logs) is saves/@SAVE@.sav; save
states, settings (config.ini) and cheats (cheats.txt) are there too.

To update to a new version, replace the app in Applications. Your saves
and settings stay. Back up that folder to keep your progress safe.
