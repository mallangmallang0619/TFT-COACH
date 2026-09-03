function registerQuitHandler(ipcMain, requestQuit) {
  ipcMain.handle("quit-application", () => {
    // Acknowledge the renderer before shutdown tears down its IPC channel.
    setImmediate(requestQuit);
    return { ok: true };
  });
}

module.exports = { registerQuitHandler };
