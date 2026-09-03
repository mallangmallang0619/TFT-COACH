const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  buildDiagnosticLaunch,
  collectSupportFiles,
  createSupportBundle,
  getSupportPaths,
} = require("./supportTools");

test("development diagnostic runs the Python diagnostic script without a shell", () => {
  const appPath = path.join("C:", "repo");
  const launch = buildDiagnosticLaunch({
    appPath,
    isPackaged: false,
    pythonCommand: "py",
    resourcesPath: path.join("C:", "resources"),
  });

  assert.equal(launch.command, "py");
  assert.deepEqual(launch.args, [path.join(appPath, "backend", "diagnose_capture.py")]);
  assert.equal(launch.options.cwd, appPath);
  assert.equal(launch.options.shell, false);
  assert.equal(launch.options.windowsHide, true);
});

test("packaged diagnostic uses the bundled backend tool mode", () => {
  const resourcesPath = path.join("C:", "app", "resources");
  const launch = buildDiagnosticLaunch({
    appPath: path.join("C:", "ignored"),
    isPackaged: true,
    resourcesPath,
  });

  assert.equal(
    launch.command,
    path.join(resourcesPath, "backend", "tft-coach-backend.exe"),
  );
  assert.deepEqual(launch.args, ["--diagnose"]);
});

test("support collection includes recent safe files but excludes unrelated data", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tft-support-test-"));
  try {
    const diagnosticDir = path.join(root, "diagnostics");
    const logDir = path.join(root, "logs");
    fs.mkdirSync(diagnosticDir);
    fs.mkdirSync(logDir);
    fs.writeFileSync(path.join(diagnosticDir, "older.png"), "old");
    fs.writeFileSync(path.join(diagnosticDir, "newer.jpg"), "new");
    fs.writeFileSync(path.join(diagnosticDir, "notes.txt"), "private");
    fs.writeFileSync(path.join(logDir, "tft-coach.log"), "log");
    fs.utimesSync(path.join(diagnosticDir, "older.png"), 1, 1);
    fs.utimesSync(path.join(diagnosticDir, "newer.jpg"), 2, 2);

    const files = collectSupportFiles({
      diagnosticDirs: [diagnosticDir],
      logDirs: [logDir],
      metadataFiles: [],
    }, { maxDiagnosticImages: 1 });

    assert.deepEqual(files.map((file) => file.archivePath).sort(), [
      "diagnostics/newer.jpg",
      "logs/tft-coach.log",
    ]);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("support bundle produces a readable zip and manifest", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tft-bundle-test-"));
  try {
    const diagnosticDir = path.join(root, "diagnostics");
    fs.mkdirSync(diagnosticDir);
    fs.writeFileSync(path.join(diagnosticDir, "capture.png"), "image-data");
    const outputPath = path.join(root, "support.zip");
    const result = createSupportBundle({
      outputPath,
      paths: { diagnosticDirs: [diagnosticDir], logDirs: [], metadataFiles: [] },
      appVersion: "0.1.0-test",
    });

    assert.equal(result.fileCount, 1);
    assert.ok(fs.statSync(outputPath).size > 0);
    const AdmZip = require("adm-zip");
    const names = new AdmZip(outputPath).getEntries().map((entry) => entry.entryName);
    assert.deepEqual(names.sort(), ["diagnostics/capture.png", "support-manifest.json"]);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("support paths cover source-tree and writable app-data diagnostics", () => {
  const paths = getSupportPaths({
    appPath: path.join("C:", "repo"),
    userDataPath: path.join("C:", "user-data"),
  });
  assert.ok(paths.diagnosticDirs.includes(path.join("C:", "repo", "backend", "_debug")));
  assert.ok(paths.diagnosticDirs.includes(path.join("C:", "user-data", "diagnostics")));
  assert.ok(paths.logDirs.includes(path.join("C:", "repo", "backend", "_logs")));
});
