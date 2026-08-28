const test = require("node:test");
const assert = require("node:assert/strict");

const {
  COMPACT_OVERLAY_HEIGHT,
  COMPACT_OVERLAY_WIDTH,
  FULL_OVERLAY_WIDTH,
  getOverlayBounds,
} = require("./windowSizing");

test("full overlay fills the work area height and stays right-aligned", () => {
  const workArea = { x: 0, y: 40, width: 2560, height: 1400 };

  assert.deepEqual(getOverlayBounds(workArea, false), {
    x: 2560 - FULL_OVERLAY_WIDTH,
    y: 40,
    width: FULL_OVERLAY_WIDTH,
    height: 1400,
  });
});

test("compact overlay becomes a small window inset from the top-right", () => {
  const workArea = { x: -1920, y: 0, width: 1920, height: 1040 };

  assert.deepEqual(getOverlayBounds(workArea, true), {
    x: -COMPACT_OVERLAY_WIDTH - 12,
    y: 12,
    width: COMPACT_OVERLAY_WIDTH,
    height: COMPACT_OVERLAY_HEIGHT,
  });
});

test("overlay bounds are clamped to unusually small work areas", () => {
  const workArea = { x: 10, y: 20, width: 280, height: 50 };

  assert.deepEqual(getOverlayBounds(workArea, true), {
    x: 10,
    y: 20,
    width: 280,
    height: 50,
  });
});
