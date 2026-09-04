# TFT Coach Improvement Plan

## Objective

Turn the current developer-run overlay into a dependable Windows application
without weakening the Set 18 detector or losing locally collected training
data. Product work and model work should advance on separate tracks with shared
release gates.

## Current Assessment

### What is already strong

- The live pipeline covers capture, HUD OCR, traits, board/bench units, shop
  purchases, augments, item advice, comp direction, and training-data harvest.
- The EfficientNet-B0 model is exported to ONNX and guarded by set/model
  metadata, confidence thresholds, and temporal stabilization.
- The Electron process now owns the Python backend, chooses a free port,
  prevents duplicate instances, and exposes failures to React.
- The Control Center provides overlay management, diagnostics, logs, and a
  privacy-scoped support ZIP.
- The project has broad Python system coverage plus focused Node tests.

### Main gaps and risks

1. **The packaged app is not functional yet.** `electron-builder` includes the
   frontend and assets, but not a standalone Python backend or Tesseract.
2. **Runtime paths are development-only.** Logs, caches, diagnostics, and crop
   output still assume a writable source tree. Installed application resources
   will be read-only.
3. **Release inputs are not reproducible.** Python versions are ranges,
   ONNX Runtime is commented out, PyInstaller is absent, and there is no CI.
4. **The Control Center is only a first pass.** It needs persisted settings,
   clearer capture states, version/model information, and safer recovery flows.
5. **Detection quality is not measured on a representative labeled corpus.**
   Synthetic and selected real-frame tests catch regressions, but they do not
   provide per-class precision/recall across resolutions, arenas, animations,
   Lux forms, health-bar colors, and board versus bench crops.
6. **Several intelligence inputs remain missing.** Star level, equipped items,
   late-game player-row identity, and opponent boards are prerequisites for
   materially better board-strength and positioning advice.
7. **Documentation has drifted.** The architecture diagram still shows a fixed
   port, component tables omit the new desktop modules, and completed versus
   remaining application phases are not clearly marked.

## Working Rules

- Add a failing test or measurable acceptance check before behavior changes.
- Never include training data, diagnostics, logs, or local cache refreshes in a
  feature commit.
- Treat production model files as release artifacts: record architecture,
  dataset fingerprint, metrics, threshold, set, and input geometry.
- Keep automatic gameplay input out of scope; TFT Coach observes and advises.
- Target Windows 10/11 x64 first. Other platforms must not block the first beta.
- Prefer honest “unknown” states over confident but fabricated game data.

## Delivery Plan

### Milestone 0 — Truthful baseline and release guardrails

Deliverables:

- Update the README architecture and component inventory to match the dynamic
  port, managed backend, Control Center, and current model.
- Split runtime, training, and build dependencies; pin the release toolchain.
- Add an explicit release verification command and prevent `npm run package`
  from silently creating an app with no backend.
- Document supported Windows versions, CPU/GPU expectations, privacy behavior,
  and exactly which generated files stay local.
- Add a model-manifest validation check to the release gate.

Tests and exit criteria:

- One command runs Node tests, Python system tests, frontend build, dependency
  checks, and model-manifest validation.
- Packaging fails early with a useful message until required backend artifacts
  exist.
- A clean status check cannot accidentally stage caches, logs, or training data.

### Milestone 1 — Control Center reliability and settings

Deliverables:

- Persist overlay visibility, compact state, opacity, position, and safe
  application preferences under Electron user data.
- Show distinct states for starting, ready, waiting for TFT, detecting,
  degraded capture, and backend failure.
- Display app version, backend protocol, model version/architecture/threshold,
  capture method, resolution, and last diagnostic time.
- Add diagnostic history with preview/open/delete controls and allow the user
  to review the exact support-bundle contents before saving.
- Add a tray menu for Control Center, overlay visibility, restart, logs,
  diagnostics, Share Mode, and Quit.
- Surface global-hotkey registration conflicts instead of logging them only.

Tests and exit criteria:

- Settings survive restart and remain on-screen after monitor changes.
- Every native action has an IPC contract test and visible success/failure state.
- Quit leaves no owned Electron or Python process.

### Milestone 2 — Packaged backend and writable data paths

Deliverables:

- Add `backend/app_paths.py` to separate immutable resources from writable user
  data while preserving current CLI paths in development.
- Move installed-app logs, downloaded caches, diagnostics, and optional crop
  collection under `%LOCALAPPDATA%/TFT Coach`.
- Seed writable caches from bundled snapshots without modifying packaged files.
- Build `backend/main.py` with PyInstaller onedir, explicitly including OpenCV,
  ONNX Runtime, capture libraries, Pydantic, WebSockets, the model, and assets.
- Bundle Tesseract plus English trained data and required license notices.

Tests and exit criteria:

- Backend executable runs on a clean Windows VM with no Python or Tesseract.
- Read-only install directories and Unicode/space-containing usernames work.
- Demo and live startup, diagnostics, cache refresh, and clean shutdown pass.

### Milestone 3 — Windows installer and repeatable releases

Deliverables:

- Package React, Electron, backend onedir, OCR runtime, and immutable assets into
  NSIS and optional portable tester builds.
- Add version metadata, shortcuts, upgrade/uninstall behavior, checksums, and
  third-party notices. Decorative application artwork is optional.
- Add a Windows GitHub Actions workflow that installs pinned dependencies,
  verifies the project, builds all artifacts, and uploads them from version tags.
- Keep releases private/prerelease until clean-machine testing is complete.

Tests and exit criteria:

- Install, launch, upgrade, reinstall, and uninstall pass on a clean VM.
- No terminal window or developer dependency is required.
- Version numbers agree across Git tag, Control Center, backend, and model.

### Milestone 4 — Detection evaluation and performance

Deliverables:

- Build a reviewed evaluation set separated by capture session, resolution,
  arena, board/bench source, star color, animation phase, and Lux form.
- Report coverage, confusion matrix, per-class precision/recall, abstention rate,
  temporal flip rate, and board/bench false-positive rates.
- Benchmark capture, OCR, inference, coaching, serialization, and render latency
  separately. Avoid reloading the model or running duplicate inference loops.
- Tune confidence and hysteresis from held-out results rather than validation
  accuracy alone.
- Add difficult negatives: Little Legends, overlapping units, empty hexes,
  particles, carousel/PvE enemies, tooltips, and arena decorations.

Tests and exit criteria:

- Champion acceptance precision is at least 95% on held-out sessions.
- Predictions do not oscillate visibly during normal idle animations.
- Detection throughput regresses by no more than 10% on the same machine.
- 1280×720, 1920×1080, and 2560×1440 pass defined HUD/board checks.

### Milestone 5 — Higher-value game-state inputs

Current foundation: optional Set 18 ONNX contracts now exist for star level and
equipped items, together with health-bar-relative region extraction and an
opt-in, source-throttled paired crop collector. Missing models abstain, and the
new fields do not affect advice. The remaining Milestone 5 gates below still
apply before enabling either signal in production.

Implement in dependency order:

1. **Player-row identity tracking:** anchor the local player instead of assuming
   a fixed right-side standings row.
2. **Equipped-item detection:** locate item slots first, then classify components,
   completed items, artifacts, emblems, and support items with an unknown class.
3. **Star-level detection:** classify the bronze/silver/gold indicator separately
   from champion identity and fuse it over time.
4. **Board-strength revision:** use observed champion, star, item, level, trait,
   and tactics.tools signals with an explicit confidence/coverage score.
5. **Opponent scouting:** only after the local-board pipeline is reliable, track
   board ownership and recommend positioning from observed threats.

Tests and exit criteria:

- Each classifier has session-separated data and per-class metrics before it is
  allowed to affect advice.
- Missing item/star data lowers confidence instead of inventing a value.
- Board-strength changes are explainable in the UI.

### Milestone 6 — Coaching quality and beta feedback

Deliverables:

- Create deterministic comp-ranking scenarios covering item commitments,
  augments, emblems, contested units, stage, HP, economy, and conditional X-tier
  gates.
- Explain why a comp is recommended and which observed signals caused a change.
- Add opt-in import/export for redacted beta support bundles; do not upload in
  the background.
- Test on multiple machines, Windows scaling settings, monitors, and GPUs.

Tests and exit criteria:

- Conditional comps are never shown without their hard prerequisite.
- Item commitments outweigh temporary unit matches in direction tests.
- A non-developer can install, run, diagnose, export a report, and uninstall
  without PowerShell instructions.

## Recommended Execution Order

1. Complete Milestone 0 immediately.
2. Finish the Control Center reliability items that aid testing and support.
3. Build the path abstraction and packaged backend before adding more UI.
4. Produce an internal installer and test it on a clean machine.
5. Establish the real evaluation corpus before retraining or changing model
   thresholds again.
6. Add player-row, item, and star detection in that order.
7. Rework board strength and opponent advice only when those inputs are measured.

This order gives the project a testable application first, then improves model
quality using evidence rather than repeatedly retraining against an uncertain
dataset.
