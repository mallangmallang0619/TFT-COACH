const assert = require("node:assert/strict");
const net = require("node:net");
const path = require("node:path");
const test = require("node:test");

const {
  BackendManager,
  buildBackendLaunch,
  findAvailablePort,
} = require("./backendManager");

test("findAvailablePort returns a port that can be bound locally", async () => {
  const port = await findAvailablePort();
  assert.ok(Number.isInteger(port));
  assert.ok(port > 0 && port <= 65535);

  await new Promise((resolve, reject) => {
    const server = net.createServer();
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => server.close(resolve));
  });
});

test("development launch runs backend/main.py without a shell", () => {
  const appPath = path.join("C:", "repo");
  const launch = buildBackendLaunch({
    appPath,
    isPackaged: false,
    mode: "demo",
    port: 49152,
    pythonCommand: "py",
    resourcesPath: path.join("C:", "resources"),
    userDataPath: path.join("C:", "user-data"),
  });

  assert.equal(launch.command, "py");
  assert.deepEqual(launch.args, [
    path.join(appPath, "backend", "main.py"),
    "--demo",
    "--port",
    "49152",
  ]);
  assert.equal(launch.options.cwd, appPath);
  assert.equal(launch.options.shell, false);
  assert.equal(launch.options.windowsHide, true);
  assert.equal(launch.options.env.TFT_COACH_USER_DATA, path.join("C:", "user-data"));
});

test("packaged launch uses the bundled backend executable", () => {
  const resourcesPath = path.join("C:", "app", "resources");
  const launch = buildBackendLaunch({
    appPath: path.join("C:", "ignored"),
    isPackaged: true,
    mode: "live",
    port: 49153,
    resourcesPath,
    userDataPath: path.join("C:", "user-data"),
  });

  assert.equal(
    launch.command,
    path.join(resourcesPath, "backend", "tft-coach-backend.exe"),
  );
  assert.deepEqual(launch.args, ["--port", "49153"]);
  assert.equal(launch.options.cwd, path.join(resourcesPath, "backend"));
});

test("manager reports a spawn failure and can retry", async () => {
  let attempts = 0;
  const manager = new BackendManager({
    appPath: path.join("C:", "repo"),
    isPackaged: false,
    portFinder: async () => 49154,
    readinessProbe: async () => false,
    resourcesPath: path.join("C:", "resources"),
    spawnImpl: () => {
      attempts += 1;
      const child = new (require("node:events").EventEmitter)();
      child.stdout = null;
      child.stderr = null;
      child.kill = () => true;
      process.nextTick(() => child.emit("error", new Error("Python was not found")));
      return child;
    },
    startupTimeoutMs: 100,
    userDataPath: path.join("C:", "user-data"),
  });

  await assert.rejects(manager.start(), /Python was not found/);
  assert.equal(manager.info.status, "failed");
  assert.match(manager.info.message, /Python was not found/);

  await assert.rejects(manager.restart(), /Python was not found/);
  assert.equal(attempts, 2);
});

test("manager reports an unexpected crash after startup", async () => {
  const child = new (require("node:events").EventEmitter)();
  child.pid = 1234;
  child.stdout = null;
  child.stderr = null;
  child.kill = () => true;
  const manager = new BackendManager({
    appPath: path.join("C:", "repo"),
    isPackaged: false,
    portFinder: async () => 49155,
    readinessProbe: async () => true,
    resourcesPath: path.join("C:", "resources"),
    spawnImpl: () => child,
    userDataPath: path.join("C:", "user-data"),
  });

  await manager.start();
  assert.equal(manager.info.status, "ready");
  child.emit("exit", 7, null);
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(manager.info.status, "failed");
  assert.match(manager.info.message, /exited \(7\)/);
});
