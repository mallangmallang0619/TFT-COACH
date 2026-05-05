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

  // Resize the overlay window
  resizeOverlay: (width, height) =>
    ipcRenderer.send("resize-overlay", { width, height }),

  // Move the overlay window
  moveOverlay: (x, y) =>
    ipcRenderer.send("move-overlay", { x, y }),

  // Set overlay opacity
  setOpacity: (opacity) =>
    ipcRenderer.send("set-opacity", opacity),

  // Listen for interaction mode changes from main process
  onInteractionMode: (callback) =>
    ipcRenderer.on("interaction-mode", (event, isInteractive) =>
      callback(isInteractive)
    ),

  // Check if running in Electron
  isElectron: true,
});
