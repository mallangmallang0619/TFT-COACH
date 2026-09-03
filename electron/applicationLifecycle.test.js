const assert = require("node:assert/strict");
const test = require("node:test");

const { registerQuitHandler } = require("./applicationLifecycle");

test("quit IPC acknowledges the renderer and schedules a real application quit", async () => {
  let handler;
  let quitRequested = false;
  const ipcMain = {
    handle(channel, callback) {
      assert.equal(channel, "quit-application");
      handler = callback;
    },
  };
  registerQuitHandler(ipcMain, () => { quitRequested = true; });

  assert.deepEqual(await handler(), { ok: true });
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(quitRequested, true);
});
