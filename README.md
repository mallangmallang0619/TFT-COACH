# TFT Coach — Desktop Overlay with Screen Capture

A real-time Teamfight Tactics coaching overlay that captures your game screen, detects your board state via computer vision, and surfaces actionable advice as a transparent overlay on top of the game.

## Architecture

Electron owns both the normal Control Center and the transparent React overlay.
It starts the Python computer-vision backend on an available local port and
passes that WebSocket address to both windows through the preload bridge.

```
TFT.exe ──direct/fallback capture──► Python detector + coach
                                           │
                              dynamic localhost WebSocket
                                           │
                          Electron-managed React application
                               ├── Control Center
                               └── in-game overlay
```

## Components

### Python Backend (`backend/`)

 Module               | Purpose                                                     
----------------------|-------------------------------------------------------------
 `main.py`            | Entry point — starts capture loop + WebSocket server        
 `capture.py`         | Direct Windows game-window capture with `mss` fallback, frame cropping
 `detector.py`        | OpenCV template matching + Tesseract OCR for game state     
 `game_state.py`      | Data model for the full game state                          
 `coach.py`           | Coaching logic — generates advice from game state          
 `synergy.py`         | Active synergy + comp-direction detection from board state  
 `game_data.py`       | Static game data: champions, traits, item recipes, meta comps |
 `tftacademy_live.py` | Background sync of TFT Academy's comp tier list             
 `websocket_server.py`| Async WebSocket server pushing state to frontend            
 `demo_server.py`     | `--demo` mode: fabricated game states, no CV needed         
 `sim_server.py`      | `--sim` mode: real detector + coach on synthesized frames   
 `fetch_templates.py` | Downloads champion/component/trait/item templates from Riot CDNs |
 `capture_templates.py`| In-game wizard for UI templates the CDNs don't have        |
 `eval_detection.py`  | Detection accuracy benchmark on synthetic boards            |
 `test_system.py`     | System test suite — run this first                          |
 `config.py`          | Resolution presets, ROI coordinates, thresholds       
       

### Electron Overlay (`electron/`)

 File                      | Purpose
---------------------------|---------------------------------------------------
 `main.js`                 | Owns Control Center, overlay, IPC, hotkeys, and lifecycle
 `backendManager.js`       | Starts, monitors, restarts, and stops the Python backend
 `supportTools.js`         | Runs diagnostics and creates privacy-scoped support ZIPs
 `applicationLifecycle.js` | Implements acknowledged, clean application shutdown
 `preload.js`              | Exposes the restricted native API to React

The repository currently provides a developer-run Electron overlay rather than
a self-contained public installer. See the
[desktop application roadmap](docs/APPLICATION_ROADMAP.md) for the packaging,
backend lifecycle, installer, and release plan. The prioritized
[improvement plan](docs/IMPROVEMENT_PLAN.md) covers product reliability,
packaging, detection evaluation, and future game-state features.

### React Frontend (`frontend/`)

The frontend receives game state over WebSocket and selects its window-specific
view from the launch URL:

 File                   | Purpose
------------------------|------------------------------------------------------
 `src/App.jsx`          | Transparent in-game coaching overlay
 `src/ControlCenter.jsx`| Normal out-of-game management and support interface
 `src/useCoachSocket.js`| Shared live backend connection and command hook
 `src/backendConnection.js` | Validates Electron-provided local WebSocket details

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- Tesseract OCR (live mode only):
  - Windows: `winget install UB-Mannheim.TesseractOCR`
  - macOS: `brew install tesseract`
  - Linux: `sudo apt install tesseract-ocr`

### Installation

```bash
# 1. Clone and enter the project
cd tft-coach-desktop

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Node dependencies (root + frontend)
npm install
cd frontend && npm install && cd ..

# 4. Download template images from Riot's CDNs (champions, components, traits, items)
python backend/fetch_templates.py

# 5. Verify everything works
npm run verify
```

### Running

```bash
# Demo mode — fabricated game data, no game or CV deps needed.
# Electron starts and owns the demo backend automatically:
npm run dev

# Sim mode — the REAL detector + coach running on synthesized board frames:
npm run dev:sim

# Live mode — capture the actual game (TFT must be running):
npm run dev:live

# Browser-only development (without Electron):
python backend/main.py        # terminal 1
npm run dev:frontend          # terminal 2, then open localhost:5173
```

The desktop app chooses a free local port for its backend, prevents duplicate
instances, and stops the backend when the app exits. If the detection engine
cannot start or crashes, the overlay shows the reason and a **Retry** button.

Launching the desktop app also opens a normal **Control Center** window. Use it
outside the game to show or hide the overlay, restart detection, run an annotated
diagnostic capture, open logs or screenshots, and export a support ZIP containing
recent diagnostic images, logs, and model metadata. Closing the Control Center
minimizes it to the taskbar; use **Quit TFT Coach** to stop the entire application.

### Release verification and packaging

```bash
npm run verify       # Node tests + model contract + frontend build + Python suite
npm run check:model  # Validate production model metadata only
npm run package      # Build an NSIS installer only when standalone inputs exist
```

Standalone packaging is intentionally guarded. Until the PyInstaller backend
and bundled Tesseract runtime are present, `npm run package` exits with the
missing inputs instead of producing an Electron shell that cannot detect TFT.
Follow [Milestones 2–3 of the improvement plan](docs/IMPROVEMENT_PLAN.md) to
complete the first installable Windows build.

The overlay is click-through ("ghost mode") by default so game clicks pass
underneath — **hover over the panel to interact with it**; move the cursor
off and it goes back to ghost mode. The badge in the header shows the
current mode.

Hotkeys (global — they work while the game has focus):

| Keys | Action |
|------|--------|
| `Ctrl+Shift+G` | **Ghost lock** — overlay never captures the mouse, even on hover. Use while scouting: TFT's player list sits underneath the panel, and this lets your clicks reach it. Press again to unlock. |
| `Ctrl+Shift+H` | Show / hide the overlay (e.g. before alt-tabbing — the overlay floats above other apps). |
| `Ctrl+Shift+R` | **Share Mode** — make the overlay visible in Discord streams and screenshots. The backend prefers direct `TFT.exe` capture and reports when it must use the foreground screen fallback. |
| `Ctrl+Shift+T` | Manual click-through toggle (also clears ghost lock). |
| `Ctrl+Shift+Q` | Quit TFT Coach. |

### Troubleshooting live detection

If HP/gold/components/units read wrong (or not at all) in live mode, run
the diagnostic while the game is open:

```bash
python backend/diagnose_capture.py               # capture the game window
python backend/diagnose_capture.py --fullscreen  # or the whole monitor
python backend/diagnose_capture.py --dump-hexes  # also save per-hex crops
```

It writes an annotated PNG to `backend/_debug/` with every ROI drawn on the
frame and prints what the detector read. Each labeled box should sit exactly
on its UI element — if they're all shifted, the capture grabbed the wrong
window or region; if one box is off, that ROI needs recalibrating in
`config.GameROIs`.

The overlay header also reports `DATA INBOX`, `DATA WAITING`, or `DATA PAUSED`.
Live mode collects visually valid board and bench crops without guessing unit
names. Collection runs only during planning, requires two stable observations,
and waits eight seconds before saving the same position again. Collection is
uncapped by default; filtering and the manual sorter keep large inboxes
manageable. Direct UE5 window capture may be unavailable; the collector
automatically uses a trusted screen fallback while `TFT.exe` is foreground.
Recent annotated session frames are kept in `backend/_debug/session/`, and
the persistent backend log is `backend/_logs/tft-coach.log`.

**Unit identification:** live Set 18 board and bench units are classified with
the bundled EfficientNet-B0 ONNX model. The detector first anchors board crops
to health bars and verifies bench occupancy independently, then applies
confidence and temporal-stability gates. The left HUD trait panel remains the
source of truth for active synergies because classifier misses must not invent
or remove traits.

### Template Images

Static templates (champion portraits, component/trait/item icons) are downloaded
from Riot's Data Dragon and Community Dragon CDNs:

```bash
python backend/fetch_templates.py           # fetch anything missing
python backend/fetch_templates.py --force   # re-download all (after a patch)
```

UI-region templates (stage banner, augment panel framing) aren't on the CDNs and
are captured from a live game instead — run `python backend/capture_templates.py`
with TFT open at your native resolution. Only needed for live mode; sim/demo
modes work without them.

## Configuration

Edit `backend/config.py` to match your setup:

- `GAME_RESOLUTION`: Your monitor resolution (1920x1080, 2560x1440, etc.)
- `CAPTURE_FPS`: How many times per second to capture (default: 2)
- `CONFIDENCE_THRESHOLD`: Template matching confidence (default: 0.8)
- `WEBSOCKET_PORT`: Port for frontend connection (default: 8765)

## Tier-List Data (TFT Academy)

The coach cross-references each detected comp against [TFT Academy's curated
comp tier list](https://tftacademy.com/tierlist/comps) so suggestions show
the meta tier (S/A/B/C/X) and patch trend (rising / falling / new).

### How auto-sync works

`backend/tftacademy_live.py` keeps the tier list current without you having
to think about it:

| When | What happens |
|------|--------------|
| Backend imports the module | Loads `assets/tftacademy_cache.json` into `META_COMPS` (instant, no network) |
| Backend startup | Schedules one async refresh (debounced, non-blocking) |
| Each WebSocket client connects | Triggers another refresh check — debounced, so opening the overlay 10× in a row hits the network at most once |
| Refresh fires | Fetches `tftacademy.com/tierlist/comps`, compares the live patch number against the cache. If different, re-parses the page, merges with curated `carry`/`match_traits` metadata, writes a new cache, and updates `META_COMPS` in place — running coaching code sees the new ratings immediately |
| Network error or parse failure | Logs a warning and keeps using the cached data — never crashes the app |

The refresh is debounced to **once every 30 minutes** by default. You can
force a fresh check at any time by running:

```bash
python scripts/sync_tftacademy.py --write   # also re-fetches now
python scripts/sync_tftacademy.py --force --write   # bypass debounce
python scripts/sync_tftacademy.py            # dry-run preview
```

### Augment tier list

Augment ratings sync from TFT Academy's JSON API
(`/api/tierlist/augments?set=18` — the same endpoint their own page uses),
covering every augment in the set with S/A/B/C ratings per pick stage
(2-1 / 3-2 / 4-2) and slot (silver / gold / prismatic). Display names are
resolved via Data Dragon's `tft-augments.json`.

The refresh runs alongside the comp-list refresh (startup + client connect,
debounced). Hand-curated tips in `AUGMENT_RATINGS` are preserved and
overlaid with the live ratings; curated-only entries are kept.

Augment lookups from OCR go exact → normalized → fuzzy
(`game_data.find_augment_rating`), so noisy reads like "Heroic Grab 8ag"
still resolve.

## How Detection Works

### Set 18 / Unreal migration

The active data profile is **Set 18: Enchanted Wilds** on Riot's Unreal
client. Riot's launch data is split across services: Data Dragon exposes the
new `DA_*` shop identities and all nine Avatar Lux rows, while CommunityDragon
currently exposes reliable trait breakpoints but an incomplete shop roster.
`backend/set18_data.py` is the reviewed join used at runtime.

Validate that snapshot against the latest Riot payloads with:

```bash
python scripts/sync_set_data.py
```

Set 18's temporary shop effects are **Wisps** (the updated Charms mechanic).
The detector keeps Wisp titles separate from champion slots, and purchase
tracking will wait until the covered champion is visible again. This prevents a
Wisp purchase from becoming a false champion purchase or a poisoned ML label.

Lux's nine Avatar origins remain distinct gameplay identities because the
chosen origin contributes two trait points. For vision training, all nine are
pooled into the single `Lux` class. Their Unreal models can differ substantially,
so every form needs crops from multiple sessions; the live trait HUD supplies
the exact origin while the classifier identifies the shared Lux unit.

The Unreal unit classifier dataset is isolated at
`backend/_training/set18/`. New live crops first enter `_inbox` with board/bench
locations in their filenames. Sort them with the keyboard-driven viewer, then
check training readiness:

```bash
# Optional: move a noisy old inbox aside without permanently deleting it:
python scripts/sort_training_inbox.py --archive-inbox

# Run this form once to manually review crops from the old auto-labeler:
python scripts/sort_training_inbox.py --requeue-existing

# Future sessions can open the new-crop inbox directly:
python scripts/sort_training_inbox.py

# Preview/apply recoverable filtering before manual sorting:
python scripts/sort_training_inbox.py --filter-inbox-dry-run
python scripts/sort_training_inbox.py --filter-inbox

# Instant filename-only threshold check:
python scripts/train_classifier.py --quick-check

# Full image-quality/cross-label audit before rebuilding:
python scripts/train_classifier.py --check
python scripts/training_data.py --stats

# Controlled architecture experiment (does not overwrite production):
python scripts/train_classifier.py --architecture efficientnet_b0 `
  --out-dir assets/models/experiments/efficientnet-b0
```

The sorter indexes the inbox into contact sheets of up to 20 visually/model-
similar crops across every slot. Click outliers to deselect them, choose a
champion, and press Enter to file the selected batch. `S` uses the displayed
model suggestion but never files automatically; `A` selects all, `N` selects
none, Space defers the group, Delete rejects selected crops recoverably, and
Ctrl+Z undoes the latest batch. Requeued files retain their previous guessed
label in the filename only as a hint. Lux's forms are pooled into `Lux`.

Classifier rebuilding uses a deterministic, capture-burst-aware validation
split. Adjacent frames from the same idle-animation sequence stay together in
training or validation instead of leaking near-duplicates across both sides.
New models preserve the complete tall sprite with 192px letterboxed input,
balance board and bench crops within each champion, and calibrate the accepted
prediction threshold for at least 95% validation precision with a 0.55 floor.
EfficientNet-B0 is the production backbone; MobileNetV3-Small remains available
through `--architecture mobilenet_v3_small` for faster comparison runs.

Inbox filtering rejects known quality failures and thins only rapid,
visually-similar crops from the same board/bench position. Spaced duplicates
and visibly different units are retained. Filtered files are moved to
`_rejected_manual` with their reason in the filename; nothing is deleted.

A Set 17/Hextech ONNX model is rejected at load time rather than silently
producing bad predictions.

#### Star level and equipped-item data (experimental)

Star level and equipped items are separate vision tasks from champion identity:
star level is a 3-class prediction, while equipped items are multi-label because
a unit can hold up to three. Their optional ONNX adapters now safely abstain
unless compatible Set 18 models and metadata exist, so this foundation does not
change live advice yet. Both detail models run only during the planning phase;
combat continues champion tracking without spending time on unstable star/item
reads.

Conservative paired crop collection is enabled by default in live mode:

```powershell
npm run dev:live
```

Accepted board-unit crops produce matching files under
`backend/_training/set18_details/stars/_inbox/` and
`backend/_training/set18_details/items/_inbox/`. The shared filename preserves
which star and item regions came from the same unit. The matching full champion
crop remains in `backend/_training/set18/_inbox/`, so all three views can be
joined by filename during review. Each board position has a
30-second cooldown, and crops without a trustworthy health-bar anchor are
skipped. Collection is also restricted to planning rounds. This intentionally
excludes combat animation and most unanchored bench crops rather than saving
badly aligned samples. To turn detail collection off for a session:

```powershell
$env:TFT_COACH_COLLECT_UNIT_DETAILS="0"
npm run dev:live
```

Do not place these crops into the champion sorter. Star crops will be reviewed
into `1`, `2`, or `3`; item crops use multi-label annotations rather than a
class for every possible item combination. Open the dedicated sorters with:

```powershell
npm run sort:stars
npm run sort:items
```

Star mode displays visually similar batches: click outliers to exclude them,
then press `1`, `2`, or `3`. Item mode displays the matching full champion crop
and an item catalog covering components, craftables, artifacts, radiant items,
and emblems from the local TFT Academy cache. Ctrl+click up to three items and
press Enter, or press `0` for no items. `A` selects the whole visual batch, `N`
selects none, Space defers, Delete rejects recoverably, and Ctrl+Z undoes the
latest label or rejection. Item annotations are written to
`backend/_training/set18_details/items/labels.json`.

A training command and held-out evaluation gate are still required before
either model is allowed to influence board strength or comp direction.

The core Unreal HUD/board ROIs were calibrated from a live 2560×1440 Set 18
frame. Re-run `python backend/diagnose_capture.py --dump-hexes` after changing
resolution or in-game UI scale.

### Component Detection
Template matching against cropped regions of the item bench area. Each component icon is matched against stored templates with confidence scoring.

### Stage Detection
OCR on the stage indicator region (top-center of screen). Tesseract extracts the stage string (e.g., "3-2").

### HP / Gold Detection
OCR on fixed UI regions. Digits are extracted and parsed.

### Board State Detection
Health bars locate occupied board hexes and define full-sprite crops for the
EfficientNet-B0 ONNX classifier. Bench slots use the same crop geometry as
training and require an independent health-bar occupancy check. Predictions
must clear confidence and temporal-stability gates before entering game state.

### Comp Direction

Comp direction combines the authoritative left-panel synergies, detected and
purchase-tracked units, completed items, held components, and selected
augments. Item commitments outweigh replaceable unit matches. Situational TFT
Academy lines are hidden until their hard prerequisite is observed: for
example, Dark Mages needs the Flora Fatalis emblem, Solar Kayle
Copy needs Cursed Crown, and Trait Ladder needs the Trait Ladder augment.
Unknown X-tier lines default to hidden until an explicit enabling rule is added.

### Augment Screen Detection
Detects the augment selection overlay and reads augment names via OCR.

## Development Roadmap

- [x] Architecture scaffold
- [x] Screen capture pipeline (adaptive resolution + frame checking)
- [x] Template matching engine (F1 = 1.00 on synthetic boards, `eval_detection.py`)
- [x] Game state data model
- [x] Coaching logic engine (items, comp direction, tips, TFT Academy tiers)
- [x] WebSocket communication
- [x] Electron overlay shell (click-through, hotkeys)
- [x] Template fetching from Riot CDNs (`fetch_templates.py`)
- [x] Set 18 roster (65 unique units) and trait breakpoints
- [x] Avatar Lux gameplay forms (+2 origin) pooled into one visual ML class
- [x] Wisp-covered shop slots excluded from purchase tracking
- [x] Unreal-scoped training/model metadata rejects stale Hextech models
- [x] Comp detection from active synergies
- [x] Multi-resolution support (ROIs are resolution-relative)
- [x] Auto-update tier list for new patches (TFT Academy sync)
- [x] Augment database — full set coverage synced from TFT Academy's API, with fuzzy OCR-name matching
- [ ] In-game UI templates for live mode (`capture_templates.py` — needs a live game)
- [x] Current-set auto-detection (trait fetch + augments API track the newest set; no constant to bump)
- [x] Live HUD detection validated on a real frame (stage/HP/gold/level OCR + trait panel — `test_real_frame.py`)
- [x] Trait-panel synergy detection for live games (drives comp advice without unit identification)
- [x] Hover-to-interact overlay (ghost mode by default, cursor-poll release)
- [x] Detection diagnostic tool (`diagnose_capture.py` — annotated ROI overlay + per-hex crop dump)
- [x] Context-aware comp direction (held components + taken augments boost matching comps)
- [x] Contextual augment picks (offers scored by tier + comp fit + active synergies, best flagged ★ PICK)
- [x] Meta board layouts (Position tab renders TFT Academy's recommended placement, stars, and items for your comp)
- [x] Shop-card reading (name-banner OCR + fuzzy roster matching — skin-proof, no art templates)
- [x] Purchase-tracking roster — shop diffs between frames reveal buys; owned units (with 3-copy star-ups) feed comp direction as held units
- [x] Manual-inbox training harvester — live mode saves stable, visually novel board and bench crops to `_training/set18/_inbox` without guessing labels, while retaining a periodic duplicate for variation. The smart contact-sheet sorter files up to 20 reviewed neighbours at once, supports outlier deselection and batch undo, and never auto-labels. Raw crops remain local and reversible. Pool sorted crops across machines with `python scripts/training_data.py --pack/--merge` (`--stats` shows progress)
- [x] Live unit identification — EfficientNet-B0 ONNX classifier with health-bar occupancy and temporal-stability gates
- [~] Star-level classifier — optional ONNX inference contract and conservative board-crop collection are implemented; labeling, training, held-out evaluation, temporal fusion, and bench geometry remain
- [~] Item classifier — optional multi-label ONNX inference contract and paired board-crop collection are implemented; labeling UI, training, held-out evaluation, item localization, and temporal fusion remain
- [ ] Player-HP row tracking — the right-side player list reorders by standing, so the fixed HP ROI reads the wrong row late-game
- [ ] Opponent scouting + positioning prediction (read enemy boards during combat, suggest counter-positioning)
- [x] Set 18 data migration — current roster/traits, TFT Academy Set 18 cache, and `DA_*` identifiers
- [x] Set 18 Unreal core ROI calibration from a live 2560×1440 frame
