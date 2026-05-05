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

  // Enable click-through initially
  setClickThrough(true);

  // Load the React frontend
  // In development, load from Vite dev server
  // In production, load the built index.html
  const isDev = process.env.NODE_ENV === "development";
  if (isDev) {
    overlayWindow.loadURL("http://localhost:5173");
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
  console.log("  Ctrl+Shift+T  — Toggle click-through (interact with overlay)");
  console.log("  Ctrl+Shift+H  — Show/Hide overlay");
  console.log("  Ctrl+Shift+Q  — Quit TFT Coach");
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
  // Toggle click-through
  globalShortcut.register("Ctrl+Shift+T", () => {
    setClickThrough(isInteractive); // Toggle
  });

  // Show/hide overlay
  globalShortcut.register("Ctrl+Shift+H", () => {
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
  globalShortcut.register("Ctrl+Shift+Q", () => {
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
