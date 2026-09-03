/**
 *Electron Preload Script
 *
 * Exposes a safe API to the React renderer process via contextBridge.
 * The renderer can use `window.electronAPI` to communicate with the
 * main process without having direct access to Node.js APIs.
 */

const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("electronAPI", {
  // Toggle between click-through and interactive mode
  toggleInteraction: () => ipcRenderer.send("toggle-interaction"),

  // Explicitly set interactivity (used for hover-to-interact)
  setInteractive: (enabled) => ipcRenderer.send("set-interactive", enabled),

  // Resize the overlay window
  resizeOverlay: (width, height) =>
    ipcRenderer.send("resize-overlay", { width, height }),

  // Switch between the full overlay and its compact toolbar.
  setCompactMode: (compact) =>
    ipcRenderer.send("set-overlay-compact", compact),

  // Move the overlay window
  moveOverlay: (x, y) =>
    ipcRenderer.send("move-overlay", { x, y }),

  // Set overlay opacity
  setOpacity: (opacity) =>
    ipcRenderer.send("set-opacity", opacity),

  setShareMode: (enabled) =>
    ipcRenderer.send("set-share-mode", enabled),

  getShareMode: () => ipcRenderer.invoke("get-share-mode"),

  getBackendInfo: () => ipcRenderer.invoke("get-backend-info"),

  restartBackend: () => ipcRenderer.invoke("restart-backend"),

  onBackendStatus: (callback) => {
    const listener = (event, info) => callback(info);
    ipcRenderer.on("backend-status", listener);
    return () => ipcRenderer.removeListener("backend-status", listener);
  },

  getOverlayVisibility: () => ipcRenderer.invoke("get-overlay-visibility"),
  setOverlayVisibility: (visible) =>
    ipcRenderer.invoke("set-overlay-visibility", visible),
  onOverlayVisibility: (callback) => {
    const listener = (event, visible) => callback(visible);
    ipcRenderer.on("overlay-visibility", listener);
    return () => ipcRenderer.removeListener("overlay-visibility", listener);
  },
  minimizeControlCenter: () => ipcRenderer.send("minimize-control-center"),
  quitApplication: () => ipcRenderer.invoke("quit-application"),
  runDiagnostic: () => ipcRenderer.invoke("run-diagnostic"),
  openDiagnosticsFolder: () => ipcRenderer.invoke("open-diagnostics-folder"),
  openLogsFolder: () => ipcRenderer.invoke("open-logs-folder"),
  exportSupportBundle: () => ipcRenderer.invoke("export-support-bundle"),

  // Listen for interaction mode changes from main process
  onInteractionMode: (callback) =>
    ipcRenderer.on("interaction-mode", (event, isInteractive) =>
      callback(isInteractive)
    ),

  // Listen for ghost-lock state changes (Ctrl+Shift+G)
  onHoverLock: (callback) =>
    ipcRenderer.on("hover-lock", (event, locked) => callback(locked)),

  onShareMode: (callback) =>
    ipcRenderer.on("share-mode", (event, enabled) => callback(enabled)),

  // Check if running in Electron
  isElectron: true,
});
