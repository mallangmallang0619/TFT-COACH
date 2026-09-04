const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  checkPackagingReadiness,
  validateModelManifest,
} = require("../scripts/releaseReadiness");

function write(root, relativePath, content = "fixture") {
  const destination = path.join(root, relativePath);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, content);
}

test("packaging readiness reports every missing standalone runtime input", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tft-release-missing-"));
  try {
    const result = checkPackagingReadiness(root, { build: { extraResources: [] } });
    assert.equal(result.ready, false);
    assert.ok(result.errors.some((error) => error.includes("tft-coach-backend.exe")));
    assert.ok(result.errors.some((error) => error.includes("tesseract.exe")));
    assert.ok(result.errors.some((error) => error.includes("eng.traineddata")));
    assert.ok(result.errors.some((error) => error.includes("unit_classifier.onnx")));
    assert.ok(result.errors.some((error) => error.includes("frontend/dist/index.html")));
    assert.ok(result.errors.some((error) => error.includes("extraResources")));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("packaging readiness passes only with artifacts and resource mappings", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tft-release-ready-"));
  try {
    for (const relativePath of [
      "packaging/dist/tft-coach-backend/tft-coach-backend.exe",
      "packaging/tesseract/tesseract.exe",
      "packaging/tesseract/tessdata/eng.traineddata",
      "assets/models/unit_classifier.onnx",
      "assets/models/unit_classifier.onnx.data",
      "assets/models/unit_classifier.json",
      "frontend/dist/index.html",
    ]) write(root, relativePath);

    const result = checkPackagingReadiness(root, {
      build: {
        extraResources: [
          { from: "packaging/dist/tft-coach-backend", to: "backend" },
          { from: "packaging/tesseract", to: "tesseract" },
        ],
      },
    });
    assert.deepEqual(result, { ready: true, errors: [] });
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("model manifest validation rejects missing release metadata", () => {
  assert.deepEqual(validateModelManifest({ architecture: "efficientnet_b0" }), {
    valid: false,
    missing: [
      "set_number", "engine", "labels", "input_size", "resize_mode",
      "min_confidence", "val_accuracy", "accepted_val_precision",
      "accepted_val_coverage", "trained_at",
    ],
  });
});

test("current production model manifest satisfies the release contract", () => {
  const manifest = JSON.parse(fs.readFileSync(
    path.join(__dirname, "..", "assets", "models", "unit_classifier.json"),
    "utf8",
  ));
  assert.deepEqual(validateModelManifest(manifest), { valid: true, missing: [] });
});
