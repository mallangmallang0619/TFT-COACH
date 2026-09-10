# TFT Coach 0.1.0-beta.1 — Windows x64

First public-beta candidate for the Set 18 desktop app. Experimental coaching;
please report incorrect board, item, star, and active-trait readings with a
diagnostic capture.

## Download and install

Download **TFT-Coach-Setup-0.1.0-beta.1.exe**, run it, and choose an installation
folder. Launch TFT Coach from the desktop or Start menu, then enter a TFT game.
Python, Node.js, and Tesseract are bundled; you do not need to install them.

This installer is **unsigned**. Windows may show an unknown-publisher warning.
Check that the download came from the project's GitHub Releases page and compare
its SHA-256 with `SHA256SUMS.txt`. Do not disable Windows security protections.

For an existing installation, quit TFT Coach before running setup. User data
lives under `%APPDATA%\tft-coach-desktop`, even when the app is installed on D:.
Uninstall is configured to preserve it; upgrade/uninstall preservation has not
yet been validated on a clean machine. Keep a backup before testing those flows.

## Included

- Electron Control Center and overlay with automatic backend launch.
- Bundled OCR and champion/star inference models.
- Set 18 comp seeds, active-trait reading, and item-based comp recommendations.
- In-app diagnostic capture and support export.
- Removal of identified Set 17 data, retired icons, and historical fixtures.
- Available third-party notices inside the installation's `resources/notices`
  folder and in the accompanying `THIRD_PARTY_NOTICES.zip`.

## Known limitations

- Windows x64 only. Clean-machine installation, upgrade, uninstall, and broad
  Windows/display/DPI coverage remain unverified.
- Live gameplay detection accuracy is still being evaluated. The automated
  tests do not establish accuracy during a real match.
- No automatic-update channel is configured. Install newer tester builds manually.
- This candidate is unsigned; trusted signing remains release work.
- Dependency notices have been collected, but the native dependency and
  game-asset/data redistribution review remains incomplete. This candidate is
  prepared locally and is not yet approved for public publication.

## Feedback

Use Control Center's diagnostic/support tools after a mismatch. Review the
export before sharing it: screenshots may contain player names and chat.
Include app version, Windows version, resolution, display scaling, game stage,
expected reading, actual reading, and steps to reproduce.

See `TESTER_GUIDE.md` for the test checklist. Report issues at
https://github.com/mallangmallang0619/TFT-COACH/issues.
