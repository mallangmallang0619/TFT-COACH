# TFT Coach — Desktop Overlay with Screen Capture

A real-time Teamfight Tactics coaching overlay that captures your game screen, detects your board state via computer vision, and surfaces actionable advice as a transparent overlay on top of the game.

## Architecture

Uses an Electron shell that hosts a React frontend. The React frontend connects to the Python computer-vision pipeline over a WebSocket.

```
TFT client ──screen capture──► Python backend ──ws://localhost:8765──► React UI (Electron overlay)
                 (mss)          detect + coach
```

## Components

### Python Backend (`backend/`)

 Module               | Purpose                                                     
----------------------|-------------------------------------------------------------
 `main.py`            | Entry point — starts capture loop + WebSocket server        
 `capture.py`         | Screen capture via `mss`, window detection, frame cropping  
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

 File          | Purpose                                           
---------------|---------------------------------------------------
 `main.js`     | Creates transparent, always-on-top overlay window 
 `preload.js`  | Exposes IPC bridge to renderer                    

### React Frontend (`frontend/`)

Adapted from the prototype — receives game state via WebSocket and renders coaching UI.

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
python backend/test_system.py
```

### Running

```bash
# Demo mode — fabricated game data, no game or CV deps needed.
# Starts the Vite frontend + demo backend + Electron overlay together:
npm run dev

# Sim mode — the REAL detector + coach running on synthesized board frames:
npm run dev:sim

# Live mode — capture the actual game (TFT must be running):
python backend/main.py        # terminal 1
npm run dev:frontend          # terminal 2
npm start                     # terminal 3 (Electron overlay)
```

The overlay is click-through ("ghost mode") by default so game clicks pass
underneath — **hover over the panel to interact with it**; move the cursor
off and it goes back to ghost mode. The badge in the header shows the
current mode.

Hotkeys (global — they work while the game has focus):

| Keys | Action |
|------|--------|
| `Ctrl+Shift+G` | **Ghost lock** — overlay never captures the mouse, even on hover. Use while scouting: TFT's player list sits underneath the panel, and this lets your clicks reach it. Press again to unlock. |
| `Ctrl+Shift+H` | Show / hide the overlay (e.g. before alt-tabbing — the overlay floats above other apps). |
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

**Known limitation — unit identification:** board and bench units render as
3D models, which the CDN portrait templates cannot match, so unit names are
currently only detected in sim mode. Live games still get synergies (read
from the HUD trait panel), HP/gold/stage/level OCR, and item advice. The
path to live unit ID is collecting in-game crops via `--dump-hexes` and
building a per-set template library from them.

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
(`/api/tierlist/augments?set=17` — the same endpoint their own page uses),
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

### Component Detection
Template matching against cropped regions of the item bench area. Each component icon is matched against stored templates with confidence scoring.

### Stage Detection
OCR on the stage indicator region (top-center of screen). Tesseract extracts the stage string (e.g., "3-2").

### HP / Gold Detection
OCR on fixed UI regions. Digits are extracted and parsed.

### Board State Detection
The hex grid is mapped to pixel coordinates. Each hex is sampled for champion portraits via template matching.

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
- [x] Champion portrait database (63 champions, set 17)
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
- [ ] Live unit identification — board/bench are 3D models; needs an in-game template library (collect with `diagnose_capture.py --dump-hexes`)
- [ ] Player-HP row tracking — the right-side player list reorders by standing, so the fixed HP ROI reads the wrong row late-game
- [ ] Opponent scouting + positioning prediction (read enemy boards during combat, suggest counter-positioning)
- [ ] New-set data migration — `game_data.py` CHAMPIONS/TRAITS/META_COMPS seeds are still hand-written per set; templates need a `--force` re-fetch
