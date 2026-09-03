const { spawn } = require("node:child_process");
const { EventEmitter } = require("node:events");
const net = require("node:net");
const path = require("node:path");

const HOST = "127.0.0.1";

function findAvailablePort(host = HOST) {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.once("error", reject);
    server.listen(0, host, () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close((error) => error ? reject(error) : resolve(port));
    });
  });
}

function probePort(port, host = HOST, timeoutMs = 250) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port });
    let settled = false;
    const finish = (ready) => {
      if (settled) return;
      settled = true;
      socket.destroy();
      resolve(ready);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => finish(true));
    socket.once("timeout", () => finish(false));
    socket.once("error", () => finish(false));
  });
}

function buildBackendLaunch({
  appPath,
  isPackaged,
  mode = "live",
  port,
  pythonCommand = process.env.TFT_COACH_PYTHON || "python",
  resourcesPath,
  userDataPath,
}) {
  const modeArg = mode === "demo" ? "--demo" : mode === "sim" ? "--sim" : null;
  const command = isPackaged
    ? path.join(resourcesPath, "backend", "tft-coach-backend.exe")
    : pythonCommand;
  const args = isPackaged
    ? ["--port", String(port)]
    : [
        path.join(appPath, "backend", "main.py"),
        ...(modeArg ? [modeArg] : []),
        "--port",
        String(port),
      ];

  return {
    command,
    args,
    options: {
      cwd: isPackaged ? path.join(resourcesPath, "backend") : appPath,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
        TFT_COACH_USER_DATA: userDataPath,
      },
      shell: false,
      windowsHide: true,
    },
  };
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

class BackendManager extends EventEmitter {
  constructor({
    appPath,
    isPackaged,
    mode = process.env.TFT_COACH_BACKEND_MODE || "live",
    portFinder = findAvailablePort,
    readinessProbe = probePort,
    resourcesPath,
    spawnImpl = spawn,
    startupTimeoutMs = 60000,
    userDataPath,
  }) {
    super();
    this.options = { appPath, isPackaged, mode, resourcesPath, userDataPath };
    this.portFinder = portFinder;
    this.readinessProbe = readinessProbe;
    this.spawnImpl = spawnImpl;
    this.startupTimeoutMs = startupTimeoutMs;
    this.child = null;
    this.stopping = false;
    this.info = {
      status: "stopped",
      wsUrl: null,
      port: null,
      message: "Backend is stopped",
      pid: null,
    };
  }

  setInfo(update) {
    this.info = { ...this.info, ...update };
    this.emit("status", { ...this.info });
  }

  async start() {
    if (this.child) return { ...this.info };

    const port = await this.portFinder();
    const wsUrl = `ws://${HOST}:${port}`;
    this.stopping = false;
    this.setInfo({
      status: "starting",
      wsUrl,
      port,
      message: "Starting detection engine (the model may take a moment to load)…",
      pid: null,
    });

    const launch = buildBackendLaunch({ ...this.options, port });
    const child = this.spawnImpl(launch.command, launch.args, launch.options);
    this.child = child;

    if (child.stdout) {
      child.stdout.on("data", (chunk) => process.stdout.write(`[backend] ${chunk}`));
    }
    let lastError = "";
    if (child.stderr) {
      child.stderr.on("data", (chunk) => {
        lastError = String(chunk).trim().slice(-600);
        process.stderr.write(`[backend] ${chunk}`);
      });
    }

    const failed = new Promise((_, reject) => {
      child.once("error", (error) => reject(error));
      child.once("exit", (code, signal) => {
        if (this.child === child) this.child = null;
        if (this.stopping) return;
        const exitReason = signal || (code ?? "unknown");
        const detail = lastError || `Detection engine exited (${exitReason})`;
        if (this.info.status === "ready") {
          this.setInfo({ status: "failed", message: detail, pid: null });
          return;
        }
        reject(new Error(detail));
      });
    });

    const ready = (async () => {
      const deadline = Date.now() + this.startupTimeoutMs;
      while (Date.now() < deadline) {
        if (await this.readinessProbe(port)) return;
        await delay(150);
      }
      throw new Error("Detection engine did not become ready in time");
    })();

    try {
      await Promise.race([ready, failed]);
      this.setInfo({
        status: "ready",
        message: "Detection engine is ready",
        pid: child.pid || null,
      });
      return { ...this.info };
    } catch (error) {
      if (this.child === child) {
        this.child = null;
        try { child.kill(); } catch {}
      }
      this.setInfo({
        status: "failed",
        message: error?.message || "Detection engine failed to start",
        pid: null,
      });
      throw error;
    }
  }

  async stop() {
    const child = this.child;
    this.stopping = true;
    this.child = null;
    if (child) {
      await new Promise((resolve) => {
        let timer;
        const done = () => {
          if (timer) clearTimeout(timer);
          resolve();
        };
        child.once("exit", done);
        try { child.kill(); } catch { done(); }
        timer = setTimeout(done, 2000);
      });
    }
    this.setInfo({
      status: "stopped",
      message: "Backend is stopped",
      pid: null,
    });
  }

  async restart() {
    await this.stop();
    return this.start();
  }
}

module.exports = {
  BackendManager,
  buildBackendLaunch,
  findAvailablePort,
  probePort,
};
