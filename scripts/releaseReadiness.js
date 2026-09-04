const fs = require("node:fs");
const path = require("node:path");

const REQUIRED_PACKAGE_FILES = [
  "packaging/dist/tft-coach-backend/tft-coach-backend.exe",
  "packaging/tesseract/tesseract.exe",
  "packaging/tesseract/tessdata/eng.traineddata",
  "assets/models/unit_classifier.onnx",
  "assets/models/unit_classifier.onnx.data",
  "assets/models/unit_classifier.json",
  "frontend/dist/index.html",
];

const REQUIRED_MODEL_FIELDS = [
  "architecture",
  "set_number",
  "engine",
  "labels",
  "input_size",
  "resize_mode",
  "min_confidence",
  "val_accuracy",
  "accepted_val_precision",
  "accepted_val_coverage",
  "trained_at",
];

function validateModelManifest(manifest) {
  const missing = REQUIRED_MODEL_FIELDS.filter((field) => {
    const value = manifest?.[field];
    if (value === undefined || value === null || value === "") return true;
    if (field === "labels") return !Array.isArray(value) || value.length < 2;
    return false;
  });
  return { valid: missing.length === 0, missing };
}

function hasResourceMapping(packageJson, source, destination) {
  const resources = packageJson?.build?.extraResources || [];
  return resources.some((entry) => (
    entry && typeof entry === "object"
    && String(entry.from || "").replaceAll("\\", "/") === source
    && String(entry.to || "").replaceAll("\\", "/") === destination
  ));
}

function checkPackagingReadiness(root, packageJson) {
  const errors = [];
  for (const relativePath of REQUIRED_PACKAGE_FILES) {
    if (!fs.existsSync(path.join(root, relativePath))) {
      errors.push(`Missing packaging input: ${relativePath}`);
    }
  }
  if (!hasResourceMapping(
    packageJson,
    "packaging/dist/tft-coach-backend",
    "backend",
  )) {
    errors.push("electron-builder extraResources must map packaged backend to backend");
  }
  if (!hasResourceMapping(packageJson, "packaging/tesseract", "tesseract")) {
    errors.push("electron-builder extraResources must map packaged Tesseract to tesseract");
  }
  return { ready: errors.length === 0, errors };
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function runCli(root = path.resolve(__dirname, ".."), args = process.argv.slice(2)) {
  const modelPath = path.join(root, "assets", "models", "unit_classifier.json");
  let manifest;
  try {
    manifest = readJson(modelPath);
  } catch (error) {
    console.error(`[release] Could not read model manifest: ${error.message}`);
    return 1;
  }
  const modelResult = validateModelManifest(manifest);
  if (!modelResult.valid) {
    console.error(`[release] Model manifest is missing: ${modelResult.missing.join(", ")}`);
    return 1;
  }
  console.log(
    `[release] Model manifest OK: Set ${manifest.set_number} ${manifest.architecture}, ` +
    `${manifest.labels.length} labels, validation accuracy ${manifest.val_accuracy}`
  );
  if (args.includes("--model-only")) return 0;

  let packageJson;
  try {
    packageJson = readJson(path.join(root, "package.json"));
  } catch (error) {
    console.error(`[release] Could not read package.json: ${error.message}`);
    return 1;
  }
  const packageResult = checkPackagingReadiness(root, packageJson);
  if (!packageResult.ready) {
    console.error("[release] Standalone packaging is not ready:");
    for (const error of packageResult.errors) console.error(`  - ${error}`);
    console.error("[release] Follow docs/IMPROVEMENT_PLAN.md Milestones 2–3 before packaging.");
    return 1;
  }
  console.log("[release] Standalone packaging inputs are ready.");
  return 0;
}

if (require.main === module) {
  process.exitCode = runCli();
}

module.exports = {
  checkPackagingReadiness,
  runCli,
  validateModelManifest,
};
