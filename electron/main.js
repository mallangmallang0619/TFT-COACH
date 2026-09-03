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

const { app, BrowserWindow, dialog, globalShortcut, ipcMain, screen, shell } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("path");
const { BackendManager } = require("./backendManager");
const {
  buildDiagnosticLaunch,
  createSupportBundle,
  getSupportPaths,
} = require("./supportTools");
const { getOverlayBounds } = require("./windowSizing");

let overlayWindow = null;
let controlWindow = null;
let backendManager = null;
let backendStoppedForQuit = false;
let isQuitting = false;
let isInteractive = false;
let isVisible = true;
let isShareMode = process.env.TFT_COACH_SHARE_MODE === "1";
let isCompact = false;
let expandedBounds = null;
// Ghost lock: while true the overlay never captures the mouse, even on
// hover — needed when clicking game UI that sits underneath it (the
// player list used for scouting other boards is right below the panel).
let hoverLocked = false;

function loadFrontendView(window, view) {
  const isDev = process.env.NODE_ENV === "development";
  if (isDev) {
    const query = view ? `?view=${encodeURIComponent(view)}` : "";
    window.loadURL(`http://localhost:5173/${query}`);
    window.webContents.once("did-fail-load", () => {
      console.warn(
        "[TFT Coach] Vite dev server not reachable on :5173 — loading frontend/dist."
      );
      window.loadFile(path.join(__dirname, "../frontend/dist/index.html"), {
        query: view ? { view } : {},
      });
    });
  } else {
    window.loadFile(path.join(__dirname, "../frontend/dist/index.html"), {
      query: view ? { view } : {},
    });
  }
}

function sendToWindow(window, channel, payload) {
  if (window && !window.isDestroyed() && !window.webContents.isDestroyed()) {
    window.webContents.send(channel, payload);
  }
}

function createOverlayWindow() {
  const initialBounds = getOverlayBounds(screen.getPrimaryDisplay().workArea, false);

  overlayWindow = new BrowserWindow({
    // Full-screen overlay
    ...initialBounds,

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
  overlayWindow.setContentProtection(!isShareMode);

  // Enable click-through initially
  setClickThrough(true);

  loadFrontendView(overlayWindow, null);

  // Keep window on top even when it loses focus
  overlayWindow.setAlwaysOnTop(true, "screen-saver");

  // Prevent the window from being closed accidentally
  overlayWindow.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    overlayWindow.hide();
    isVisible = false;
  });

  overlayWindow.on("closed", () => {
    overlayWindow = null;
  });

  overlayWindow.on("show", () => {
    isVisible = true;
    sendToWindow(controlWindow, "overlay-visibility", true);
  });
  overlayWindow.on("hide", () => {
    isVisible = false;
    sendToWindow(controlWindow, "overlay-visibility", false);
  });

  console.log("[TFT Coach] Overlay window created");
  console.log("[TFT Coach] Hotkeys:");
  console.log("  Ctrl+Shift+G  — Ghost lock (overlay never captures the mouse — scout freely)");
  console.log("  Ctrl+Shift+T  — Toggle click-through (interact with overlay)");
  console.log("  Ctrl+Shift+H  — Show/Hide overlay");
  console.log("  Ctrl+Shift+Q  — Quit TFT Coach");
}

function createControlWindow() {
  controlWindow = new BrowserWindow({
    width: 980,
    height: 700,
    minWidth: 760,
    minHeight: 560,
    title: "TFT Coach Control Center",
    backgroundColor: "#0d0e12",
    autoHideMenuBar: true,
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      nodeIntegration: false,
      contextIsolation: true,
    },
  });
  controlWindow.setContentProtection(true);
  loadFrontendView(controlWindow, "control");
  controlWindow.once("ready-to-show", () => controlWindow?.show());
  controlWindow.on("close", (event) => {
    if (isQuitting) return;
    event.preventDefault();
    controlWindow.minimize();
  });
  controlWindow.on("closed", () => {
    controlWindow = null;
  });
}

function setOverlayVisibility(visible) {
  if (!overlayWindow) return false;
  if (visible) overlayWindow.show();
  else overlayWindow.hide();
  isVisible = visible;
  sendToWindow(controlWindow, "overlay-visibility", isVisible);
  return isVisible;
}

function setCompactMode(compact) {
  if (!overlayWindow) return;

  const nextCompact = !!compact;
  if (nextCompact === isCompact) return;

  // Use the display containing the overlay so minimizing also behaves on
  // secondary monitors and work areas with a non-zero origin/taskbar.
  const display = screen.getDisplayMatching(overlayWindow.getBounds());
  if (nextCompact) {
    expandedBounds = overlayWindow.getBounds();
  }
  const bounds = nextCompact
    ? getOverlayBounds(display.workArea, true)
    : expandedBounds || getOverlayBounds(display.workArea, false);
  overlayWindow.setBounds(bounds, true);
  isCompact = nextCompact;
  if (!isCompact) expandedBounds = null;
}

function setShareMode(enabled) {
  isShareMode = !!enabled;
  if (!overlayWindow) return;
  overlayWindow.setContentProtection(!isShareMode);
  overlayWindow.webContents.send("share-mode", isShareMode);
  console.log(
    `[TFT Coach] Share Mode: ${isShareMode ? "ON - visible in captures" : "OFF - capture protected"}`
  );
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
    setOverlayVisibility(!isVisible);
    console.log(`[TFT Coach] Overlay ${isVisible ? "shown" : "hidden"}`);
  });

  register("Ctrl+Shift+R", () => {
    setShareMode(!isShareMode);
  });

  // Quit
  register("Ctrl+Shift+Q", () => {
    console.log("[TFT Coach] Quitting...");
    isQuitting = true;
    app.quit();
  });
}

// ── App Lifecycle ────────────────────────────────────────────────────────────

const hasSingleInstanceLock = app.requestSingleInstanceLock();
if (!hasSingleInstanceLock) {
  app.quit();
}

app.on("second-instance", () => {
  if (controlWindow) {
    if (controlWindow.isMinimized()) controlWindow.restore();
    controlWindow.show();
    controlWindow.focus();
  }
});

app.whenReady().then(() => {
  if (!hasSingleInstanceLock) return;
  backendManager = new BackendManager({
    appPath: app.getAppPath(),
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
    userDataPath: app.getPath("userData"),
  });
  backendManager.on("status", (info) => {
    sendToWindow(overlayWindow, "backend-status", info);
    sendToWindow(controlWindow, "backend-status", info);
  });

  createOverlayWindow();
  createControlWindow();
  registerHotkeys();
  overlayWindow.webContents.on("did-finish-load", () => {
    overlayWindow.webContents.send("share-mode", isShareMode);
    overlayWindow.webContents.send("backend-status", backendManager.info);
  });
  controlWindow.webContents.on("did-finish-load", () => {
    controlWindow.webContents.send("backend-status", backendManager.info);
    controlWindow.webContents.send("overlay-visibility", isVisible);
  });
  backendManager.start().catch((error) => {
    console.error(`[TFT Coach] Detection engine failed: ${error.message}`);
  });
});

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
});

app.on("before-quit", (event) => {
  isQuitting = true;
  if (!backendManager || backendStoppedForQuit) return;

  event.preventDefault();
  backendManager.stop().catch((error) => {
    console.warn(`[TFT Coach] Could not stop detection engine cleanly: ${error.message}`);
  }).finally(() => {
    backendStoppedForQuit = true;
    app.quit();
  });
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

// Collapse the full-height overlay into a small, right-aligned toolbar.
ipcMain.on("set-overlay-compact", (event, compact) => {
  setCompactMode(compact);
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

ipcMain.on("set-share-mode", (event, enabled) => {
  setShareMode(enabled);
});

ipcMain.handle("get-share-mode", () => isShareMode);

ipcMain.handle("get-backend-info", () => backendManager?.info || ({
  status: "starting",
  wsUrl: null,
  port: null,
  message: "Desktop application is starting",
}));

ipcMain.handle("restart-backend", async () => {
  if (!backendManager) throw new Error("Detection engine is not initialized");
  try {
    return await backendManager.restart();
  } catch (error) {
    console.error(`[TFT Coach] Detection engine restart failed: ${error.message}`);
    return backendManager.info;
  }
});

ipcMain.handle("get-overlay-visibility", () => isVisible);
ipcMain.handle("set-overlay-visibility", (event, visible) => (
  setOverlayVisibility(Boolean(visible))
));
ipcMain.on("minimize-control-center", () => controlWindow?.minimize());
ipcMain.on("quit-application", () => {
  isQuitting = true;
  app.quit();
});

function currentSupportPaths() {
  return getSupportPaths({
    appPath: app.getAppPath(),
    userDataPath: app.getPath("userData"),
  });
}

async function openSupportDirectory(kind) {
  const paths = currentSupportPaths();
  const candidates = kind === "logs" ? paths.logDirs : paths.diagnosticDirs;
  const directory = app.isPackaged ? candidates[1] : candidates[0];
  fs.mkdirSync(directory, { recursive: true });
  const error = await shell.openPath(directory);
  return error ? { ok: false, message: error } : { ok: true, path: directory };
}

ipcMain.handle("open-diagnostics-folder", () => openSupportDirectory("diagnostics"));
ipcMain.handle("open-logs-folder", () => openSupportDirectory("logs"));

ipcMain.handle("export-support-bundle", async () => {
  const stamp = new Date().toISOString().replaceAll(":", "-").slice(0, 19);
  const choice = await dialog.showSaveDialog(controlWindow, {
    title: "Export TFT Coach support bundle",
    defaultPath: path.join(app.getPath("documents"), `tft-coach-support-${stamp}.zip`),
    filters: [{ name: "ZIP archive", extensions: ["zip"] }],
  });
  if (choice.canceled || !choice.filePath) return { canceled: true };
  const result = createSupportBundle({
    outputPath: choice.filePath,
    paths: currentSupportPaths(),
    appVersion: app.getVersion(),
  });
  return { canceled: false, ...result };
});

ipcMain.handle("run-diagnostic", () => new Promise((resolve) => {
  const launch = buildDiagnosticLaunch({
    appPath: app.getAppPath(),
    isPackaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
  });
  let stdout = "";
  let stderr = "";
  let settled = false;
  const child = spawn(launch.command, launch.args, launch.options);
  const finish = (result) => {
    if (settled) return;
    settled = true;
    clearTimeout(timeout);
    resolve(result);
  };
  child.stdout?.on("data", (chunk) => { stdout += String(chunk); });
  child.stderr?.on("data", (chunk) => { stderr += String(chunk); });
  child.once("error", (error) => finish({ ok: false, message: error.message }));
  child.once("exit", (code) => {
    const match = stdout.match(/Annotated frame:\s*(.+\.png)\s*$/m);
    if (code === 0) {
      finish({
        ok: true,
        path: match?.[1]?.trim() || null,
        message: "Diagnostic capture completed",
      });
    } else {
      const detail = stderr.trim().split(/\r?\n/).at(-1) || stdout.trim() || `Exited with code ${code}`;
      finish({ ok: false, message: detail });
    }
  });
  const timeout = setTimeout(() => {
    try { child.kill(); } catch {}
    finish({ ok: false, message: "Diagnostic timed out after two minutes" });
  }, 120000);
}));
