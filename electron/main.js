/**
 * Electron Main Process
 *
 * Creates a transparent, always-on-top, click-through overlay window
 * that renders the React coaching UI on top of the game.
 *
 * Key behaviors:
 *   - Frameless, transparent window
 *   - Always on top of other windows
 *   - Click-through by default (mouse events pass to game)
 *   - Toggle interactivity with a global hotkey (Ctrl+Shift+T)
 *   - Hotkey to show/hide overlay (Ctrl+Shift+H)
 */

const { app, BrowserWindow, globalShortcut, ipcMain, screen } = require("electron");
const path = require("path");

let overlayWindow = null;
let isInteractive = false;
let isVisible = true;
// Ghost lock: while true the overlay never captures the mouse, even on
// hover — needed when clicking game UI that sits underneath it (the
// player list used for scouting other boards is right below the panel).
let hoverLocked = false;

function createOverlayWindow() {
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  overlayWindow = new BrowserWindow({
    // Full-screen overlay
    width: 420,
    height: height,
    x: width - 420, // Right edge of screen
    y: 0,

    // Overlay behavior
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: true,
    hasShadow: false,

    // Click-through by default
    // (mouse events pass through to the game underneath)
    ...(process.platform !== "linux" && {
      // Linux doesn't support click-through well
    }),

    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  // Exclude the overlay from screen capture (WDA_EXCLUDEFROMCAPTURE on
  // Windows). Without this the backend's own capture includes the overlay
  // pixels — it sits exactly over the game's player-HP list, corrupting
  // OCR of everything underneath it.
  overlayWindow.setContentProtection(true);

  // Enable click-through initially
  setClickThrough(true);

  // Load the React frontend
  // In development, load from Vite dev server
  // In production, load the built index.html
  const isDev = process.env.NODE_ENV === "development";
  if (isDev) {
    overlayWindow.loadURL("http://localhost:5173");
    // Dev server not running → fall back to the built bundle instead of a
    // blank window. The bundle may be older than src/ — the in-app
    // BACKEND/OVERLAY version badge surfaces real mismatches.
    overlayWindow.webContents.once("did-fail-load", () => {
      console.warn(
        "[overlay] Vite dev server not reachable on :5173 — loading frontend/dist. " +
        "Run `npm run dev:frontend` for live code, or `npm run build:frontend` to refresh the bundle."
      );
      overlayWindow.loadFile(path.join(__dirname, "../frontend/dist/index.html"));
    });
  } else {
    overlayWindow.loadFile(path.join(__dirname, "../frontend/dist/index.html"));
  }

  // Keep window on top even when it loses focus
  overlayWindow.setAlwaysOnTop(true, "screen-saver");

  // Prevent the window from being closed accidentally
  overlayWindow.on("close", (event) => {
    event.preventDefault();
    overlayWindow.hide();
    isVisible = false;
  });

  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });

  console.log("[TFT Coach] Overlay window created");
  console.log("[TFT Coach] Hotkeys:");
  console.log("  Ctrl+Shift+G  — Ghost lock (overlay never captures the mouse — scout freely)");
  console.log("  Ctrl+Shift+T  — Toggle click-through (interact with overlay)");
  console.log("  Ctrl+Shift+H  — Show/Hide overlay");
  console.log("  Ctrl+Shift+Q  — Quit TFT Coach");
}

function setHoverLock(locked) {
  hoverLocked = locked;
  if (locked) {
    setClickThrough(true);   // release the mouse immediately
  }
  if (overlayWindow) {
    overlayWindow.webContents.send("hover-lock", hoverLocked);
  }
  console.log(`[TFT Coach] Ghost lock: ${locked ? "ON — overlay is pure glass" : "OFF"}`);
}

function setClickThrough(enabled) {
  if (!overlayWindow) return;

  isInteractive = !enabled;

  if (enabled) {
    // Mouse clicks pass through the overlay to the game
    overlayWindow.setIgnoreMouseEvents(true, { forward: true });
    overlayWindow.setOpacity(0.85);
  } else {
    // Overlay captures mouse events (interactive mode)
    overlayWindow.setIgnoreMouseEvents(false);
    overlayWindow.setOpacity(1.0);
  }

  // Notify the renderer about interaction state
  overlayWindow.webContents.send("interaction-mode", isInteractive);
  console.log(`[TFT Coach] Click-through: ${enabled ? "ON" : "OFF"}`);
}

function registerHotkeys() {
  // globalShortcut.register returns false when another app already owns
  // the accelerator — surface that instead of failing silently.
  const register = (accelerator, handler) => {
    const ok = globalShortcut.register(accelerator, handler);
    if (!ok) {
      console.warn(
        `[TFT Coach] Could not register hotkey ${accelerator} — ` +
        `another application may already use it`
      );
    }
    return ok;
  };

  // Ghost lock — overlay stays visible but never captures the mouse.
  // Use while scouting: the game's player list sits underneath the panel.
  register("Ctrl+Shift+G", () => {
    setHoverLock(!hoverLocked);
  });

  // Toggle click-through
  register("Ctrl+Shift+T", () => {
    if (hoverLocked) {
      setHoverLock(false);  // manual toggle overrides the lock
    }
    setClickThrough(isInteractive); // Toggle
  });

  // Show/hide overlay
  register("Ctrl+Shift+H", () => {
    if (isVisible) {
      overlayWindow.hide();
      isVisible = false;
    } else {
      overlayWindow.show();
      isVisible = true;
    }
    console.log(`[TFT Coach] Overlay ${isVisible ? "shown" : "hidden"}`);
  });

  // Quit
  register("Ctrl+Shift+Q", () => {
    console.log("[TFT Coach] Quitting...");
    overlayWindow.destroy();
    app.quit();
  });
}

// ── App Lifecycle ────────────────────────────────────────────────────────────

app.whenReady().then(() => {
  createOverlayWindow();
  registerHotkeys();
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
});

app.on("window-all-closed", () => {
  app.quit();
});

// ── IPC Handlers ─────────────────────────────────────────────────────────────

// Frontend can request interaction mode toggle
ipcMain.on("toggle-interaction", () => {
  setClickThrough(isInteractive);
});

// Hover-to-interact: the renderer still receives mouse events while
// click-through (setIgnoreMouseEvents forwards them), so it asks for
// interactivity when the cursor enters the panel. Release is decided
// here by polling the real cursor position against the window bounds —
// renderer mouseleave can't be trusted for it, because toggling
// setIgnoreMouseEvents fires synthetic enter/leave events that would
// flap the state. Ctrl+Shift+T remains as a manual fallback.
let hoverReleaseTimer = null;

function startHoverRelease() {
  if (hoverReleaseTimer) return;
  hoverReleaseTimer = setInterval(() => {
    if (!overlayWindow || !isInteractive) {
      clearInterval(hoverReleaseTimer);
      hoverReleaseTimer = null;
      return;
    }
    const { x, y } = screen.getCursorScreenPoint();
    const b = overlayWindow.getBounds();
    const inside = x >= b.x && x < b.x + b.width && y >= b.y && y < b.y + b.height;
    if (!inside) {
      setClickThrough(true);
      clearInterval(hoverReleaseTimer);
      hoverReleaseTimer = null;
    }
  }, 250);
}

ipcMain.on("set-interactive", (event, enabled) => {
  if (hoverLocked) {
    return;   // ghost lock: hover never grabs the mouse
  }
  if (enabled && !isInteractive) {
    setClickThrough(false);
    startHoverRelease();
  }
  // Explicit disables from the renderer are ignored — cursor polling
  // owns the release to avoid enter/leave feedback loops.
});

// Frontend can request window resize
ipcMain.on("resize-overlay", (event, { width, height }) => {
  if (overlayWindow) {
    overlayWindow.setSize(width, height);
  }
});

// Frontend can request position change
ipcMain.on("move-overlay", (event, { x, y }) => {
  if (overlayWindow) {
    overlayWindow.setPosition(x, y);
  }
});

// Frontend requests overlay opacity change
ipcMain.on("set-opacity", (event, opacity) => {
  if (overlayWindow) {
    overlayWindow.setOpacity(Math.max(0.3, Math.min(1.0, opacity)));
  }
});
