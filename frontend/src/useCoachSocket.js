/**
 * TFT Coach — WebSocket Hook
 *
 * React hook that manages the WebSocket connection to the Python backend.
 * Provides real-time game state updates and methods to send commands.
 *
 * Usage:
 *   const { gameState, isConnected, sendCommand } = useCoachSocket();
 */

import { useState, useEffect, useRef, useCallback } from "react";

const WS_URL = "ws://localhost:8765";
const RECONNECT_DELAY_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 50;

/**
 * @typedef {Object} GameState
 * @property {string} phase - Current game phase
 * @property {string} stage - Game stage (e.g., "3-2")
 * @property {number} player_hp - Player HP
 * @property {number} gold - Current gold
 * @property {number} level - Player level
 * @property {string[]} component_ids - Held component IDs
 * @property {Object[]} board_champions - Champions on board
 * @property {Object[]} augment_options - Augment choices (during selection)
 * @property {Object} advice - Coaching advice from the engine
 */

export function useCoachSocket() {
  const [gameState, setGameState] = useState(null);
  const [gameData, setGameData] = useState(() => {
    try {
      const saved = localStorage.getItem("tft_coach_game_data");
      return saved ? JSON.parse(saved) : null;
    } catch { return null; }
  });
  const [isConnected, setIsConnected] = useState(false);
  const [serverStats, setServerStats] = useState(null);
  const [isDemo, setIsDemo] = useState(false);

  const wsRef = useRef(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimer = useRef(null);

  const connect = useCallback(() => {
    // Clean up existing connection
    if (wsRef.current) {
      wsRef.current.close();
    }

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("[TFT Coach] Connected to backend");
        setIsConnected(true);
        reconnectAttempts.current = 0;

        // Request initial state
        ws.send(JSON.stringify({ type: "request_state" }));
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);

          if (msg.type === "game_state") {
            setGameState(msg.data);
            if (msg.stats) setServerStats(msg.stats);
            if (msg.demo !== undefined) setIsDemo(msg.demo);
          } else if (msg.type === "game_data") {
            // Item recipes, component list, shred/burn sets from game_data.py
            setGameData(msg);
            try { localStorage.setItem("tft_coach_game_data", JSON.stringify(msg)); } catch {}
          } else if (msg.type === "pong") {
            // Heartbeat response — connection is alive
          }
        } catch (err) {
          console.warn("[TFT Coach] Failed to parse message:", err);
        }
      };

      ws.onclose = () => {
        console.log("[TFT Coach] Disconnected from backend");
        setIsConnected(false);
        wsRef.current = null;

        // Auto-reconnect
        if (reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
          reconnectAttempts.current += 1;
          reconnectTimer.current = setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };

      ws.onerror = (err) => {
        console.warn("[TFT Coach] WebSocket error:", err);
      };
    } catch (err) {
      console.error("[TFT Coach] Failed to create WebSocket:", err);
    }
  }, []);

  // Connect on mount, cleanup on unmount
  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) wsRef.current.close();
    };
  }, [connect]);

  // Heartbeat ping every 15s
  useEffect(() => {
    const interval = setInterval(() => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 15000);
    return () => clearInterval(interval);
  }, []);

  /**
   * Send a command to the backend.
   * @param {string} type - Command type
   * @param {Object} payload - Command data
   */
  const sendCommand = useCallback((type, payload = {}) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type, ...payload }));
    }
  }, []);

  /**
   * Override the detected stage (for testing).
   */
  const overrideStage = useCallback(
    (stage) => sendCommand("override_stage", { stage }),
    [sendCommand]
  );

  /**
   * Override detected components (for testing).
   */
  const overrideComponents = useCallback(
    (components) => sendCommand("override_components", { components }),
    [sendCommand]
  );

  return {
    gameState,
    gameData,
    isConnected,
    isDemo,
    serverStats,
    sendCommand,
    overrideStage,
    overrideComponents,
    reconnect: connect,
  };
}

export default useCoachSocket;
