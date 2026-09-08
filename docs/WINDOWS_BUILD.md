# Windows beta build

The first local NSIS build bundles Electron/React, Python 3.14, OpenCV, ONNX
Runtime, champion/star models, templates, and Tesseract English OCR. Runtime
writes use Electron's user-data directory (normally
`%APPDATA%/tft-coach-desktop`) for logs, diagnostics, caches, and training data.
The install directory contains immutable resources. Uninstall is configured
to preserve user data.

## Build prerequisites

- Windows x64 and Python 3.14 (the tested builder uses 3.14.5).
- Node/npm, with root and frontend dependencies installed via `npm ci` and
  `npm --prefix frontend ci`.
- Tesseract in `C:\Program Files\Tesseract-OCR`, including English trained data.
- Production models and local templates in `assets/`.

From the repository root:

```powershell
npm run verify
npm run package
npm run test:packaged
```

`scripts/build_windows.ps1` creates `packaging/.venv`, installs pinned build
dependencies, copies Tesseract's executable, DLLs, English data and supplied
license documentation, and builds the backend. A custom Tesseract location can
be supplied to that script with `-TesseractDirectory PATH`.

Outputs:

- `dist-electron/TFT Coach Setup 0.1.0.exe`: installer to give a tester.
- `dist-electron/win-unpacked/TFT Coach.exe`: directly runnable app, provided
  the entire `win-unpacked` directory stays together.
- `packaging/dist/tft-coach-backend/`: intermediate backend bundle.

Build products, build environments, local diagnostics, and training data are
not committed. `--publish never` prevents builds from creating a GitHub release.
Tesseract is copied from the builder's installed distribution; its version is
not yet pinned by an automated download. Preserve the supplied third-party
notices and finish a dependency-license inventory before public distribution.

## Validation performed

- Source system tests and desktop launch/path contract tests.
- Bundled champion/star ONNX inference and Tesseract OCR.
- Bundled demo WebSocket connection, with developer Python/Tesseract removed
  from PATH, a different working directory, and Unicode/space-containing user paths.
- Packaged Control Center startup: backend reports Ready while waiting for TFT.

The automated smoke test launches only its own temporary backend and stops it
after checking the connection. It does not require or play a game.

## Still required before public release

- Clean Windows machine: install, live capture, diagnostic export, quit,
  upgrade, reinstall, and uninstall; verify user data survives upgrades.
- Validate supported Windows versions and display/DPI configurations.
- Code signing and a trusted release-download channel. This local beta disables
  signing/executable resource editing to avoid the signing-tool symlink privilege
  requirement on developer machines. Restore that step for a signed release.
- Complete third-party license notices and automate the Windows build in CI.

Successful packaging is not a claim that the existing item, champion, or trait
detector is perfect. Continue reporting gameplay mismatches with diagnostics.
