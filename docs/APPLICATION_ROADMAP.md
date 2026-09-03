# TFT Coach Desktop Application Roadmap

## Outcome

Ship TFT Coach as a normal Windows application:

- The user downloads one signed installer.
- A Start menu or desktop shortcut launches the overlay.
- No terminal, Python, Node.js, or separate Tesseract installation is required.
- The application starts and stops its computer-vision backend automatically.
- Only one TFT Coach instance runs at a time.
- Updates, logs, diagnostics, and failures are understandable to a non-developer.

The first public target should be **Windows 10/11 x64**. The capture pipeline is
already Windows-focused and TFT players primarily need a Windows build. macOS
and Linux packaging should not delay the Windows release.

## Current State

The project is already a desktop application architecturally:

```text
Electron process -> React overlay -> WebSocket -> Python CV backend -> TFT.exe
```

Development mode now launches Electron and the frontend; Electron owns the
Python backend process, selects a free local port, prevents duplicate app
instances, and exposes startup/crash recovery in the overlay. `electron-builder`
is configured for an NSIS installer, but the current package includes only the
Electron files, built frontend, and assets. The remaining release blocker is to
package the Python backend and Tesseract so end users need neither installed.

The application conversion is therefore mostly packaging, lifecycle, storage,
and release engineering—not a UI rewrite.

### Foundation completed

- Electron-managed backend start, stop, restart, and crash reporting
- Dynamic localhost WebSocket port passed safely to React
- Single-instance application lock
- Visible detection-engine startup and failure states with retry
- Unified `npm run dev`, `npm run dev:sim`, and `npm run dev:live` process flow

## Recommended Architecture

Keep Electron and React. Package the Python backend as a Windows executable and
let Electron own its lifecycle.

```text
TFT Coach.exe
  |-- Electron main process
  |     |-- creates the overlay and tray menu
  |     |-- chooses an available localhost port
  |     |-- starts/stops the backend child process
  |     `-- reports startup/crash status to React
  |-- bundled Python backend (PyInstaller onedir)
  |     |-- OpenCV + ONNX Runtime + capture dependencies
  |     |-- bundled Tesseract executable and English trained data
  |     `-- immutable Set/model assets
  `-- writable user data
        |-- logs
        |-- diagnostics
        |-- caches
        `-- optional training inbox
```

Use a PyInstaller **onedir** backend initially. It starts faster, is easier to
debug, and avoids unpacking a large OpenCV/ONNX payload on every launch. The
outer Electron installer still gives users one installer and one application.

## Product Decisions for Version 1

- Windows 10/11 x64 only.
- Offline inference; screenshots and crops remain local by default.
- One Electron instance and one managed backend instance.
- A dynamically selected localhost port instead of assuming port 8765 is free.
- The overlay opens even if the backend fails, showing a useful recovery screen.
- Runtime files go under Electron's `userData` directory, never inside Program
  Files or the read-only packaged resources directory.
- Model training and the manual sorter remain developer tools and are not part
  of the first public installer.
- Automatic gameplay input is out of scope. The application observes the game
  and presents advice only.

## Implementation Phases

### Phase 0 — Release Baseline

Goal: make the existing development build reproducible before packaging it.

- Pin Python and Node dependency versions used by the release build.
- Add a single command that runs Python system tests, Electron tests, frontend
  tests, and the production frontend build.
- Record the supported Windows versions and required architecture.
- Add application icons, publisher name, semantic versioning, and license files.
- Keep training data, diagnostics, caches, and developer logs out of releases.

Exit criteria:

- A clean clone produces the same frontend and backend outputs twice.
- All current tests pass from one release-check command.

### Phase 1 — Packaged Backend

Goal: produce a standalone backend that runs on a machine without Python.

- Add a PyInstaller spec for `backend/main.py`.
- Include OpenCV, NumPy, ONNX Runtime, WebSockets, Pydantic, capture libraries,
  the production ONNX model, metadata, and required static assets.
- Bundle Tesseract and its English trained data, including required third-party
  license notices. Point `pytesseract` at the bundled binary in packaged mode.
- Add a central path module that distinguishes immutable packaged resources
  from writable application data.
- Move logs, downloaded caches, diagnostics, and optional collected crops to a
  writable user-data directory.
- Preserve source-tree paths in development mode so existing tools still work.

Suggested files:

- `backend/app_paths.py`
- `packaging/tft_coach_backend.spec`
- `packaging/tesseract/`
- `scripts/build_backend.ps1`

Exit criteria:

- The backend executable starts and detects the model on a clean Windows VM
  with no Python or Tesseract installed.
- Paths containing spaces and non-ASCII Windows usernames work.
- Read-only installation directories do not break caches or logs.

### Phase 2 — Electron Owns the Backend

Goal: launching TFT Coach launches the complete product.

- Add an Electron backend manager responsible for spawn, readiness, shutdown,
  crash detection, and limited restart with backoff.
- In development, spawn the local Python command; in production, spawn the
  bundled backend executable from `process.resourcesPath`.
- Let Electron reserve an available localhost port and pass it to the backend.
- Expose the resulting WebSocket URL to React through the preload bridge instead
  of hardcoding `ws://localhost:8765`.
- Add a backend-ready handshake with a timeout before declaring live mode ready.
- Shut down the child process and its descendants when Electron quits.
- Use `app.requestSingleInstanceLock()` so double-clicking cannot start two
  backends and recreate the WinError 10048 port collision.

Suggested files:

- `electron/backendManager.js`
- `electron/backendManager.test.js`
- updates to `electron/main.js` and `electron/preload.js`
- updates to `frontend/src/useCoachSocket.js`

Exit criteria:

- One shortcut starts the overlay and backend without a terminal window.
- A second launch focuses the existing application.
- A port conflict is handled automatically.
- Quit leaves no Python/backend process running.
- Backend crashes produce a visible error and a working Retry action.

### Phase 3 — Production Overlay Experience

Goal: make lifecycle and troubleshooting understandable outside a terminal.

- Add a system tray icon with Show/Hide, Restart Backend, Open Logs, Run
  Diagnostic, Share Mode, Start with Windows, and Quit.
- Add explicit UI states: Starting, Waiting for TFT, Detecting, Degraded Capture,
  Backend Failed, and Update Available.
- Surface model version, application version, capture method, and backend health
  in an About/Diagnostics view.
- Provide buttons to open the log and diagnostics folders.
- Persist safe user settings such as opacity, overlay position, compact state,
  hotkeys, and launch-on-startup preference.
- Keep the current global hotkeys, but report conflicts in the UI.

Exit criteria:

- Every common failure has a user-visible message and recovery action.
- A user can find logs and generate a diagnostic without opening PowerShell.
- Overlay position and settings survive a restart and multiple-monitor changes.

### Phase 4 — Installer

Goal: create an installable Windows artifact.

- Build the React production bundle before Electron packaging.
- Add the packaged backend and Tesseract runtime through
  `electron-builder.extraResources`.
- Configure NSIS install/uninstall behavior, application icons, shortcuts,
  version metadata, and clean removal.
- Do not delete user diagnostics or settings during ordinary upgrades.
- Add a portable ZIP build for testers if useful, while keeping NSIS as the
  primary public artifact.
- Sign the executable and installer before calling the release public. Unsigned
  beta builds will trigger stronger SmartScreen warnings.

Exit criteria:

- Install, upgrade, repair/reinstall, and uninstall succeed on a clean VM.
- The installed application launches from Start and from a desktop shortcut.
- No console windows appear during normal use.

### Phase 5 — Automated Releases

Goal: make every release repeatable and auditable.

- Add a Windows GitHub Actions workflow that installs pinned dependencies,
  runs all tests, builds the backend, builds React, and runs electron-builder.
- Upload the installer, portable archive, checksums, and build logs as artifacts.
- Trigger release builds from version tags such as `v0.2.0`.
- Publish first to a private or prerelease GitHub release channel.
- Add code signing secrets only through the CI secret store.
- Add automatic updates after installer upgrades are proven reliable. Updates
  must never replace writable caches or diagnostics.

Exit criteria:

- A tagged commit produces a tested installer without manual file copying.
- The artifact version matches the Git tag, UI, backend, and model metadata.
- Failed tests prevent release publication.

### Phase 6 — Beta Hardening

Goal: validate the application on computers other than the development machine.

Test at minimum:

- 1280x720, 1920x1080, and 2560x1440.
- 100%, 125%, and 150% Windows display scaling.
- One and two monitors, including a secondary monitor left of the primary.
- TFT launched before and after TFT Coach.
- Windowed, borderless, minimized, loading, and reconnect scenarios.
- Systems without Python, Node, Tesseract, or developer environment variables.
- Port conflicts, backend crash/restart, app double-launch, sleep/resume, and
  Windows shutdown.
- Windows usernames and installation paths containing spaces and Unicode.
- Machines with and without an NVIDIA GPU; inference must remain usable on CPU.

Collect beta reports through an explicit user action that creates a redacted
support bundle. It should include versions, configuration, logs, and selected
diagnostics, and clearly show the user what will be shared.

Exit criteria:

- No known data-loss, orphan-process, startup, or uninstall bugs.
- Detection behavior matches the development build on supported resolutions.
- A non-developer can install, run, diagnose, and uninstall without instructions
  involving a terminal.

## Testing Strategy

Add tests alongside each phase rather than validating only the final installer:

- Unit tests for packaged/development path resolution.
- Unit tests for port choice, backend command construction, restart backoff, and
  single-instance behavior.
- Integration test that starts the packaged backend, connects over WebSocket,
  requests state, and shuts it down cleanly.
- Smoke test that launches packaged Electron and confirms the built React page
  connects to the managed backend.
- Installer tests on clean Windows VMs.
- Existing detection/system tests remain release gates.

## Release Sizes and Performance

The installer will be substantially larger than the ONNX model because Electron,
Chromium, Python, OpenCV, ONNX Runtime, and Tesseract are included. Optimize size
only after the packaged build works reliably. Startup and detection latency are
more important than saving tens of megabytes.

Use these performance gates:

- Overlay visible within 3 seconds on a typical SSD.
- Backend ready within 10 seconds on a cold start.
- No more than one active capture/inference loop.
- Idle CPU remains low while TFT is not running.
- Current live detection throughput does not regress by more than 10% versus the
  development build on the same machine.

## Suggested Delivery Order

For a solo developer, a realistic first beta is approximately **8–12 focused
development days**:

1. Release baseline and path abstraction: 1–2 days.
2. PyInstaller backend and bundled OCR: 2–3 days.
3. Electron process management and dynamic WebSocket port: 2–3 days.
4. Tray/status/error experience and NSIS installer: 2–3 days.
5. CI release workflow and clean-machine validation: 1–2 days.

## Definition of Done for the First Public Beta

- A user downloads and installs one Windows `.exe`.
- Launching it opens TFT Coach without a terminal.
- TFT may be started before or after the coach.
- The backend, model, capture, OCR, and overlay all work without developer tools.
- Double-launch and port conflicts do not create duplicate processes.
- Closing through Quit stops every owned process.
- Logs and diagnostics are available from the tray or application UI.
- The build passes automated tests and clean-VM smoke tests.
- Privacy behavior and third-party licenses are documented.

## First Implementation Slice

Start with the smallest end-to-end proof:

1. Add packaged/development path resolution to Python.
2. Build the backend with PyInstaller onedir.
3. Add the Electron backend manager with single-instance locking.
4. Pass a dynamically chosen WebSocket URL through preload to React.
5. Package both parts into an unsigned internal NSIS installer.
6. Test that installer on a Windows machine without Python or Node.

Do not begin auto-update, telemetry, or public data collection until this slice
can install, launch, detect, and quit reliably.
