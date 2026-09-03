export const DEFAULT_BACKEND_INFO = Object.freeze({
  status: "ready",
  wsUrl: "ws://127.0.0.1:8765",
  port: 8765,
  message: "Using local development backend",
});

const VALID_STATUSES = new Set(["starting", "ready", "failed", "stopped"]);
const LOCAL_SOCKET = /^ws:\/\/(?:127\.0\.0\.1|localhost):([1-9]\d{0,4})$/;

export function normalizeBackendInfo(value) {
  if (!value || !VALID_STATUSES.has(value.status)) return DEFAULT_BACKEND_INFO;
  const match = typeof value.wsUrl === "string" ? value.wsUrl.match(LOCAL_SOCKET) : null;
  if (!value.wsUrl && value.status !== "ready") {
    return {
      status: value.status,
      wsUrl: null,
      port: null,
      message: typeof value.message === "string" ? value.message : "",
    };
  }
  const port = Number(value.port ?? match?.[1]);
  if (!match || !Number.isInteger(port) || port < 1 || port > 65535) {
    return DEFAULT_BACKEND_INFO;
  }
  return {
    status: value.status,
    wsUrl: value.wsUrl,
    port,
    message: typeof value.message === "string" ? value.message : "",
  };
}

export async function resolveBackendInfo(electronAPI) {
  if (!electronAPI?.getBackendInfo) return DEFAULT_BACKEND_INFO;
  try {
    return normalizeBackendInfo(await electronAPI.getBackendInfo());
  } catch {
    return {
      ...DEFAULT_BACKEND_INFO,
      status: "failed",
      message: "Could not contact the desktop application",
    };
  }
}
