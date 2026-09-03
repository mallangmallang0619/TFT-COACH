import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_BACKEND_INFO,
  normalizeBackendInfo,
  resolveBackendInfo,
} from "./backendConnection.js";

test("browser development falls back to the default local backend", async () => {
  assert.deepEqual(await resolveBackendInfo(undefined), DEFAULT_BACKEND_INFO);
});

test("Electron backend information is normalized", async () => {
  const api = {
    getBackendInfo: async () => ({
      message: "Listening",
      port: 49321,
      status: "ready",
      wsUrl: "ws://127.0.0.1:49321",
    }),
  };

  assert.deepEqual(await resolveBackendInfo(api), {
    message: "Listening",
    port: 49321,
    status: "ready",
    wsUrl: "ws://127.0.0.1:49321",
  });
});

test("unsafe or malformed backend information cannot change the socket host", () => {
  assert.deepEqual(
    normalizeBackendInfo({ status: "ready", wsUrl: "wss://example.com/steal" }),
    DEFAULT_BACKEND_INFO,
  );
  assert.deepEqual(
    normalizeBackendInfo({ status: "mystery", wsUrl: "ws://127.0.0.1:9000" }),
    DEFAULT_BACKEND_INFO,
  );
});

test("startup state is preserved before a port has been allocated", () => {
  assert.deepEqual(
    normalizeBackendInfo({ status: "starting", message: "Launching", wsUrl: null }),
    { status: "starting", message: "Launching", wsUrl: null, port: null },
  );
});
