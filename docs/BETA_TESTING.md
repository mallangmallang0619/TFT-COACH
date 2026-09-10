# TFT Coach beta tester guide

## First launch

1. Run the installer and choose your preferred folder (C: or D:).
2. Open TFT Coach using the desktop or Start menu shortcut.
3. Confirm the Control Center starts the backend and waits for TFT.
4. Enter a normal TFT game. Record Windows version, game resolution, display
   scaling, and window mode when reporting results.

## During planning

- Compare each champion and star level with the board.
- Check each equipped item independently, including two- and three-item units.
- Compare active traits and counts against the left-side trait panel. Inactive
  progress such as 2/3 must not become active.
- Check that comp advice reflects held items and that conditional comps respect
  their augment/emblem requirements.
- Capture a diagnostic when the expected and actual readings differ.

## Desktop and installation checks

- Quit the app and confirm its overlay and backend stop.
- Reopen it and confirm it starts successfully.
- Export a support ZIP from the app and confirm it opens. Inspect it before sharing.
- On a test machine, back up `%APPDATA%\tft-coach-desktop` before reinstall,
  upgrade, and uninstall tests. Confirm saved data survives each step.
- Test on a Windows x64 machine without Python, Node.js, or Tesseract installed.

## Bug report template

App version: 0.1.0-beta.1

Windows version:

Resolution / display scaling / window mode:

Install folder:

Game stage and planning/combat phase:

Steps to reproduce:

Expected behavior:

Actual behavior:

Diagnostic attachment (reviewed before sharing):
