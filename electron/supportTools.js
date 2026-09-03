const fs = require("node:fs");
const path = require("node:path");
const AdmZip = require("adm-zip");

const IMAGE_EXTENSIONS = new Set([".jpg", ".jpeg", ".png"]);
const LOG_EXTENSIONS = new Set([".log", ".txt"]);

function buildDiagnosticLaunch({
  appPath,
  isPackaged,
  pythonCommand = process.env.TFT_COACH_PYTHON || "python",
  resourcesPath,
}) {
  return {
    command: isPackaged
      ? path.join(resourcesPath, "backend", "tft-coach-backend.exe")
      : pythonCommand,
    args: isPackaged
      ? ["--diagnose"]
      : [path.join(appPath, "backend", "diagnose_capture.py")],
    options: {
      cwd: isPackaged ? path.join(resourcesPath, "backend") : appPath,
      env: { ...process.env, PYTHONUNBUFFERED: "1" },
      shell: false,
      windowsHide: true,
    },
  };
}

function getSupportPaths({ appPath, userDataPath }) {
  return {
    diagnosticDirs: [
      path.join(appPath, "backend", "_debug"),
      path.join(userDataPath, "diagnostics"),
    ],
    logDirs: [
      path.join(appPath, "backend", "_logs"),
      path.join(userDataPath, "logs"),
    ],
    metadataFiles: [
      path.join(appPath, "assets", "models", "unit_classifier.json"),
    ],
  };
}

function walkFiles(root) {
  if (!root || !fs.existsSync(root)) return [];
  const result = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const fullPath = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(fullPath);
      else if (entry.isFile()) result.push(fullPath);
    }
  };
  visit(root);
  return result;
}

function collectSupportFiles(paths, { maxDiagnosticImages = 80 } = {}) {
  const diagnostics = [];
  for (const directory of paths.diagnosticDirs || []) {
    for (const filePath of walkFiles(directory)) {
      if (!IMAGE_EXTENSIONS.has(path.extname(filePath).toLowerCase())) continue;
      diagnostics.push({
        filePath,
        relativePath: path.relative(directory, filePath).replaceAll("\\", "/"),
        modifiedMs: fs.statSync(filePath).mtimeMs,
      });
    }
  }
  diagnostics.sort((a, b) => b.modifiedMs - a.modifiedMs);

  const candidates = diagnostics.slice(0, maxDiagnosticImages).map((file) => ({
    filePath: file.filePath,
    archivePath: `diagnostics/${file.relativePath}`,
    modifiedMs: file.modifiedMs,
  }));

  for (const directory of paths.logDirs || []) {
    for (const filePath of walkFiles(directory)) {
      if (!LOG_EXTENSIONS.has(path.extname(filePath).toLowerCase())) continue;
      candidates.push({
        filePath,
        archivePath: `logs/${path.relative(directory, filePath).replaceAll("\\", "/")}`,
        modifiedMs: fs.statSync(filePath).mtimeMs,
      });
    }
  }

  for (const filePath of paths.metadataFiles || []) {
    if (!fs.existsSync(filePath) || path.extname(filePath).toLowerCase() !== ".json") continue;
    candidates.push({
      filePath,
      archivePath: `metadata/${path.basename(filePath)}`,
      modifiedMs: fs.statSync(filePath).mtimeMs,
    });
  }

  const unique = new Map();
  for (const candidate of candidates) {
    let archivePath = candidate.archivePath;
    let suffix = 2;
    while (unique.has(archivePath)) {
      const extension = path.posix.extname(candidate.archivePath);
      const stem = candidate.archivePath.slice(0, -extension.length);
      archivePath = `${stem}-${suffix}${extension}`;
      suffix += 1;
    }
    unique.set(archivePath, { ...candidate, archivePath });
  }
  return [...unique.values()];
}

function createSupportBundle({ outputPath, paths, appVersion = "unknown" }) {
  const files = collectSupportFiles(paths);
  const zip = new AdmZip();
  for (const file of files) {
    zip.addLocalFile(
      file.filePath,
      path.posix.dirname(file.archivePath),
      path.posix.basename(file.archivePath),
    );
  }
  const manifest = {
    generatedAt: new Date().toISOString(),
    appVersion,
    platform: process.platform,
    arch: process.arch,
    diagnosticImages: files.filter((file) => file.archivePath.startsWith("diagnostics/")).length,
    logs: files.filter((file) => file.archivePath.startsWith("logs/")).length,
    includedFiles: files.map((file) => file.archivePath),
  };
  zip.addFile("support-manifest.json", Buffer.from(JSON.stringify(manifest, null, 2)));
  zip.writeZip(outputPath);
  return { outputPath, fileCount: files.length };
}

module.exports = {
  buildDiagnosticLaunch,
  collectSupportFiles,
  createSupportBundle,
  getSupportPaths,
};
