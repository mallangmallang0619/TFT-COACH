# TFT Coach — Desktop Overlay with Screen Capture

A real-time Teamfight Tactics coaching overlay that captures your game screen, detects your board state via computer vision, and surfaces actionable advice as a transparent overlay on top of the game.

## Architecture

```
Uses an electron shell that has a react frontend. The react frontend connects to the computer vision pipeline all connected using a websocket.

## Components

### Python Backend (`backend/`)

 Module               | Purpose                                                     
----------------------|-------------------------------------------------------------
 `main.py`            | Entry point — starts capture loop + WebSocket server        
 `capture.py`         | Screen capture via `mss`, window detection, frame cropping  
 `detector.py`        | OpenCV template matching + Tesseract OCR for game state     
 `game_state.py`      | Data model for the full game state                          
 `coach.py`           | Coaching logic — generates advice from game state          
 `websocket_server.py`| Async WebSocket server pushing state to frontend            
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
- Tesseract OCR installed (`brew install tesseract` for macos / `sudo apt install tesseract-ocr` for windows)

### Installation

```bash
# 1. Clone and enter the project
cd tft-coach-desktop

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Install Node dependencies
npm install

# 4. Generate template images (see below, MIGHT NOT WORK)

# 5. Start the backend
python backend/main.py

# 6. In another terminal, start the Electron overlay
npm start
```

### Generating Template Images

The CV pipeline uses template matching — it needs reference screenshots of each TFT component icon, champion portrait, and UI element. To generate these:

1. Open TFT at your native resolution
2. Run `python backend/capture_templates.py` (guided wizard)
3. Templates are saved to `assets/templates/`

This only needs to be done once per patch/resolution change.
This might not work very well...

## Configuration

Edit `backend/config.py` to match your setup:

- `GAME_RESOLUTION`: Your monitor resolution (1920x1080, 2560x1440, etc.)
- `CAPTURE_FPS`: How many times per second to capture (default: 2)
- `CONFIDENCE_THRESHOLD`: Template matching confidence (default: 0.8)
- `WEBSOCKET_PORT`: Port for frontend connection (default: 8765)

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
- [x] Screen capture pipeline - work in progress
- [x] Template matching engine
- [-] Game state data model - work in progress
- [-] Coaching logic engine - work in progress
- [x] WebSocket communication
- [x] Electron overlay shell
- [ ] Template image generation wizard
- [ ] Champion portrait database
- [ ] Augment OCR + database
- [ ] Comp detection from active synergies
- [ ] Multi-resolution support
- [ ] Auto-update for new patches
