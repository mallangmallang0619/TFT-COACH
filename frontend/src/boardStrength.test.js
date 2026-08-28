import test from "node:test";
import assert from "node:assert/strict";

import { getBoardStrengthPresentation } from "./boardStrength.js";

test("traits-only fallback keeps Board Strength but hides a misleading score", () => {
  assert.deepEqual(
    getBoardStrengthPresentation(12.4, { source: "traits_only", label: "Strong" }),
    {
      available: false,
      score: null,
      tabLabel: "📈 Board Strength",
      status: "MODEL NEEDED",
    }
  );
});

test("a detected board exposes its rounded live strength", () => {
  assert.deepEqual(
    getBoardStrengthPresentation(71.6, { source: "detected_board", label: "Strong" }),
    {
      available: true,
      score: 72,
      tabLabel: "📈 Strength 72",
      status: "STRONG",
    }
  );
});

test("missing detection still provides an honest Board Strength destination", () => {
  assert.deepEqual(getBoardStrengthPresentation(null, null), {
    available: false,
    score: null,
    tabLabel: "📈 Board Strength",
    status: "MODEL NEEDED",
  });
});

test("roster estimates are not presented as observed board strength", () => {
  assert.equal(
    getBoardStrengthPresentation(64, { source: "roster_estimate", label: "Average" }).available,
    false
  );
});

test("an observed-board source without a numeric score remains unavailable", () => {
  assert.equal(
    getBoardStrengthPresentation(null, { source: "detected_board", label: "Strong" }).available,
    false
  );
});
