import React, { useEffect, useMemo, useState } from "react";
import { useCoachSocket } from "./useCoachSocket";

const COLORS = {
  bg: "#0d0f14",
  panel: "#151821",
  border: "#282d3a",
  text: "#eef0f6",
  muted: "#8f96a8",
  cyan: "#42d9c8",
  green: "#48d597",
  amber: "#f2b84b",
  red: "#ff6874",
};

function StatusCard({ label, value, detail, tone = COLORS.cyan }) {
  return (
    <div className="cc-card cc-status-card">
      <div className="cc-eyebrow">{label}</div>
      <div className="cc-status-value">
        <span className="cc-dot" style={{ background: tone, boxShadow: `0 0 12px ${tone}80` }} />
        {value}
      </div>
      <div className="cc-detail">{detail}</div>
    </div>
  );
}

function ActionButton({ icon, title, detail, onClick, busy, disabled, accent = COLORS.cyan }) {
  return (
    <button
      className="cc-action"
      onClick={onClick}
      disabled={busy || disabled}
      style={{ "--action-accent": accent }}
    >
      <span className="cc-action-icon">{busy ? "…" : icon}</span>
      <span>
        <strong>{busy ? `${title}…` : title}</strong>
        <small>{detail}</small>
      </span>
      <span className="cc-chevron">›</span>
    </button>
  );
}

export default function ControlCenter() {
  const {
    backendRuntime,
    backendProtocol,
    gameState,
    isConnected,
    isDemo,
    restartBackend,
  } = useCoachSocket();
  const [overlayVisible, setOverlayVisible] = useState(true);
  const [busyAction, setBusyAction] = useState(null);
  const [notice, setNotice] = useState(null);

  const api = typeof window !== "undefined" ? window.electronAPI : null;
  useEffect(() => {
    document.title = "TFT Coach Control Center";
    api?.getOverlayVisibility?.().then(setOverlayVisible);
    return api?.onOverlayVisibility?.(setOverlayVisible);
  }, [api]);

  const gameStatus = useMemo(() => {
    if (!isConnected) return { value: "Waiting", detail: "The detection engine is not connected", tone: COLORS.amber };
    if (isDemo) return { value: "Demo mode", detail: `Scenario stage ${gameState?.stage || "—"}`, tone: COLORS.cyan };
    if (!gameState || gameState.phase === "not_in_game") {
      return { value: "TFT not detected", detail: "Open TFT and enter a game when you are ready", tone: COLORS.muted };
    }
    return {
      value: "Game detected",
      detail: `Stage ${gameState.stage || "—"} · Level ${gameState.level || "—"} · ${gameState.gold ?? "—"} gold`,
      tone: COLORS.green,
    };
  }, [gameState, isConnected, isDemo]);

  const engineStatus = {
    ready: { value: "Ready", tone: COLORS.green },
    starting: { value: "Starting", tone: COLORS.amber },
    failed: { value: "Needs attention", tone: COLORS.red },
    stopped: { value: "Stopped", tone: COLORS.muted },
  }[backendRuntime.status] || { value: "Unknown", tone: COLORS.muted };

  const captureMethod = gameState?.capture_method || "waiting";
  const collection = gameState?.collection_status;

  const runAction = async (name, action, successMessage) => {
    setBusyAction(name);
    setNotice(null);
    try {
      const result = await action();
      if (result?.canceled) return;
      if (result?.ok === false) throw new Error(result.message || "The action failed");
      setNotice({ tone: "success", message: successMessage(result) });
    } catch (error) {
      setNotice({ tone: "error", message: error?.message || "The action failed" });
    } finally {
      setBusyAction(null);
    }
  };

  const toggleOverlay = () => runAction(
    "overlay",
    () => api.setOverlayVisibility?.(!overlayVisible),
    () => `Overlay ${overlayVisible ? "hidden" : "shown"}.`,
  );
  const runDiagnostic = () => runAction(
    "diagnostic",
    () => api.runDiagnostic?.(),
    (result) => result?.path
      ? `Diagnostic saved: ${result.path}`
      : "Diagnostic capture completed.",
  );
  const exportBundle = () => runAction(
    "export",
    () => api.exportSupportBundle?.(),
    (result) => `Support ZIP saved with ${result.fileCount} files: ${result.outputPath}`,
  );
  const restart = () => runAction(
    "restart",
    restartBackend,
    () => "Detection engine restarted.",
  );

  return (
    <div className="cc-shell">
      <style>{`
        :root { color-scheme: dark; font-family: Inter, "Segoe UI", system-ui, sans-serif; }
        html, body, #root { background: ${COLORS.bg} !important; overflow: auto !important; }
        * { box-sizing: border-box; }
        button { font: inherit; }
        .cc-shell { min-height: 100vh; color: ${COLORS.text}; background:
          radial-gradient(circle at 78% -10%, #173c4655, transparent 34%), ${COLORS.bg}; }
        .cc-topbar { height: 66px; padding: 0 30px; display: flex; align-items: center;
          justify-content: space-between; border-bottom: 1px solid ${COLORS.border}; background: #101219dd; }
        .cc-brand { display: flex; align-items: center; gap: 12px; }
        .cc-mark { width: 34px; height: 34px; border: 1px solid #45dccd88; border-radius: 10px;
          display: grid; place-items: center; color: ${COLORS.cyan}; font-weight: 900; background: #42d9c812; }
        .cc-brand strong { display: block; letter-spacing: .12em; font-size: 14px; }
        .cc-brand span { display: block; color: ${COLORS.muted}; font-size: 11px; margin-top: 2px; }
        .cc-window-actions { display: flex; gap: 8px; }
        .cc-hide { border: 1px solid ${COLORS.border}; background: #181b24; color: ${COLORS.muted};
          border-radius: 8px; padding: 8px 13px; cursor: pointer; }
        .cc-hide:hover { color: ${COLORS.text}; border-color: #3a4050; }
        .cc-quit:hover { color: ${COLORS.red}; border-color: #ff687466; }
        .cc-content { max-width: 1120px; margin: 0 auto; padding: 32px; }
        .cc-hero h1 { font-size: 29px; letter-spacing: -.03em; margin: 0 0 8px; }
        .cc-hero p { margin: 0; color: ${COLORS.muted}; line-height: 1.55; }
        .cc-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 26px; }
        .cc-card { border: 1px solid ${COLORS.border}; background: ${COLORS.panel}; border-radius: 13px; padding: 18px; }
        .cc-eyebrow { color: ${COLORS.muted}; font-size: 10px; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; }
        .cc-status-value { display: flex; align-items: center; gap: 9px; margin-top: 13px; font-size: 17px; font-weight: 750; }
        .cc-dot { width: 8px; height: 8px; border-radius: 50%; flex: 0 0 auto; }
        .cc-detail { color: ${COLORS.muted}; margin-top: 8px; font-size: 12px; line-height: 1.45; min-height: 35px; }
        .cc-section-title { margin: 30px 0 12px; display: flex; justify-content: space-between; align-items: end; }
        .cc-section-title h2 { margin: 0; font-size: 16px; }
        .cc-section-title span { color: ${COLORS.muted}; font-size: 11px; }
        .cc-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
        .cc-action { --action-accent: ${COLORS.cyan}; position: relative; display: grid;
          grid-template-columns: 38px 1fr 18px; gap: 12px; align-items: center; text-align: left;
          padding: 14px; color: ${COLORS.text}; background: #151821; border: 1px solid ${COLORS.border};
          border-radius: 11px; cursor: pointer; transition: transform .12s, border-color .12s, background .12s; }
        .cc-action:hover:not(:disabled) { transform: translateY(-1px); border-color: var(--action-accent); background: #191d27; }
        .cc-action:disabled { opacity: .52; cursor: wait; }
        .cc-action-icon { width: 36px; height: 36px; border-radius: 9px; display: grid; place-items: center;
          background: color-mix(in srgb, var(--action-accent) 12%, transparent); color: var(--action-accent); font-size: 17px; }
        .cc-action strong { display: block; font-size: 13px; }
        .cc-action small { display: block; color: ${COLORS.muted}; font-size: 11px; margin-top: 4px; line-height: 1.35; }
        .cc-chevron { color: #697083; font-size: 22px; }
        .cc-notice { margin-top: 15px; padding: 12px 14px; border-radius: 9px; font-size: 12px; line-height: 1.45;
          overflow-wrap: anywhere; border: 1px solid; }
        .cc-notice.success { color: #76e3b2; border-color: #48d59744; background: #48d5970c; }
        .cc-notice.error { color: #ff929b; border-color: #ff687444; background: #ff68740c; }
        .cc-footer { margin-top: 28px; padding-top: 18px; border-top: 1px solid ${COLORS.border};
          color: #747b8d; font-size: 11px; display: flex; justify-content: space-between; }
        @media (max-width: 820px) { .cc-grid { grid-template-columns: 1fr; } .cc-actions { grid-template-columns: 1fr; } }
      `}</style>

      <header className="cc-topbar">
        <div className="cc-brand">
          <div className="cc-mark">T</div>
          <div><strong>TFT COACH</strong><span>Control Center</span></div>
        </div>
        <div className="cc-window-actions">
          <button className="cc-hide" onClick={() => api?.minimizeControlCenter?.()}>
            Minimize
          </button>
          <button className="cc-hide cc-quit" onClick={() => api?.quitApplication?.()}>
            Quit TFT Coach
          </button>
        </div>
      </header>

      <main className="cc-content">
        <section className="cc-hero">
          <h1>Your coaching setup</h1>
          <p>Manage the detector, overlay, diagnostics, and files here. You can leave this window closed while playing.</p>
        </section>

        <section className="cc-grid">
          <StatusCard
            label="Detection engine"
            value={engineStatus.value}
            detail={backendRuntime.message || "Waiting for status"}
            tone={engineStatus.tone}
          />
          <StatusCard label="Game" {...gameStatus} />
          <StatusCard
            label="Capture & collection"
            value={captureMethod === "window" ? "Direct capture" : captureMethod.replaceAll("_", " ")}
            detail={collection
              ? `${collection.session_crops_saved || 0} crops saved this session · ${collection.state || "waiting"}`
              : "Collection details appear after TFT is detected"}
            tone={captureMethod === "window" ? COLORS.green : COLORS.muted}
          />
        </section>

        <div className="cc-section-title">
          <h2>Quick actions</h2>
          <span>Diagnostic capture can take a moment while the model loads.</span>
        </div>
        <section className="cc-actions">
          <ActionButton
            icon={overlayVisible ? "◫" : "▣"}
            title={overlayVisible ? "Hide overlay" : "Show overlay"}
            detail="Toggle the in-game coaching window"
            onClick={toggleOverlay}
            busy={busyAction === "overlay"}
          />
          <ActionButton
            icon="↻"
            title="Restart detection engine"
            detail="Use this if capture or live data stops updating"
            onClick={restart}
            busy={busyAction === "restart"}
            accent={COLORS.amber}
          />
          <ActionButton
            icon="◎"
            title="Run diagnostic capture"
            detail="Capture and annotate the current TFT window"
            onClick={runDiagnostic}
            busy={busyAction === "diagnostic"}
            accent={COLORS.green}
          />
          <ActionButton
            icon="ZIP"
            title="Export support ZIP"
            detail="Package recent diagnostics, logs, and model metadata"
            onClick={exportBundle}
            busy={busyAction === "export"}
          />
          <ActionButton
            icon="▤"
            title="Open diagnostics folder"
            detail="Review screenshots and annotated captures"
            onClick={() => runAction("diagnostics-folder", () => api.openDiagnosticsFolder?.(), () => "Opened diagnostics folder.")}
            busy={busyAction === "diagnostics-folder"}
          />
          <ActionButton
            icon="≡"
            title="Open logs folder"
            detail="Inspect backend startup and detection messages"
            onClick={() => runAction("logs-folder", () => api.openLogsFolder?.(), () => "Opened logs folder.")}
            busy={busyAction === "logs-folder"}
          />
        </section>

        {notice && <div className={`cc-notice ${notice.tone}`}>{notice.message}</div>}

        <footer className="cc-footer">
          <span>Backend protocol {backendProtocol ?? "—"}</span>
          <span>This window stays available on the taskbar · Ctrl+Shift+H toggles the overlay</span>
        </footer>
      </main>
    </div>
  );
}
