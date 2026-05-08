"""
 WebSocket Server

Async WebSocket server that:
  1. Runs the capture → detect → coach pipeline in a loop
  2. Broadcasts the latest game state to all connected frontend clients
  3. Handles client messages (e.g., manual overrides, settings changes)
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
from typing import Set

import websockets
from websockets.server import WebSocketServerProtocol

from config import WEBSOCKET_HOST, WEBSOCKET_PORT, CAPTURE_FPS
from capture import ScreenCapture
from detector import Detector, TemplateStore
from coach import Coach
from game_state import GameState, GamePhase
from game_data import ITEM_RECIPES, COMPONENT_IDS, COMPONENT_NAMES, SHRED_ITEMS, BURN_ITEMS
import tftacademy_live

logger = logging.getLogger(__name__)


class TFTCoachServer:
    """
    Main server that coordinates capture, detection, coaching,
    and WebSocket broadcasting.
    """

    def __init__(self):
        self.capture = ScreenCapture()
        self.templates = TemplateStore()
        self.detector = Detector(self.templates)
        self.coach = Coach()

        self.clients: Set[WebSocketServerProtocol] = set()
        self.latest_state: GameState = GameState()
        self.is_running = False

        # Stats
        self._frames_processed = 0
        self._total_detection_ms = 0.0

    async def start(self):
        """Start the WebSocket server and capture loop."""
        logger.info(f"Starting TFT Coach server on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")

        # Load templates
        logger.info("Loading template images...")
        self.templates.load()

        # Background refresh of the TFT Academy tier list (cache-checked,
        # debounced — does nothing if recently refreshed).
        tftacademy_live.schedule_background_refresh(initial_delay_seconds=2.0)

        # Start WebSocket server and capture loop concurrently
        self.is_running = True
        async with websockets.serve(
            self._handle_client,
            WEBSOCKET_HOST,
            WEBSOCKET_PORT,
            ping_interval=20,
            ping_timeout=10,
        ):
            logger.info("WebSocket server started. Waiting for frontend connection...")
            await self._capture_loop()

    async def stop(self):
        """Gracefully shut down the server."""
        self.is_running = False
        for client in self.clients.copy():
            await client.close()
        logger.info("Server stopped.")

    # ── WebSocket Handlers ────────────────────────────────────────────────────

    # ── Game Data Payload ─────────────────────────────────────────────────────

    @staticmethod
    def _build_game_data_payload() -> str:
        """Serialize game_data.py into a JSON message for the frontend."""
        return json.dumps({
            "type": "game_data",
            "item_recipes": [
                {
                    "recipe": list(r["recipe"]),
                    "name": r["name"].strip(),
                    "tier": r["tier"],
                    "type": r["type"],
                    "slam": r["slam"],
                    "shred": r["shred"],
                    "burn": r["burn"],
                }
                for r in ITEM_RECIPES
            ],
            "component_ids": COMPONENT_IDS,
            "component_names": COMPONENT_NAMES,
            "shred_items": sorted(SHRED_ITEMS),
            "burn_items": sorted(BURN_ITEMS),
        })

    async def _handle_client(self, websocket: WebSocketServerProtocol):
        """Handle a new WebSocket client connection."""
        self.clients.add(websocket)
        client_id = id(websocket)
        logger.info(f"Frontend connected (client {client_id}). Total clients: {len(self.clients)}")

        # Re-check TFT Academy when the overlay opens. Debounced internally
        # so frequent reconnects don't hammer the upstream site.
        tftacademy_live.schedule_background_refresh(initial_delay_seconds=0.0)

        try:
            # Push game data first so the frontend can update its recipe table
            await websocket.send(self._build_game_data_payload())
            # Then send current state immediately on connect
            await self._send_state(websocket)

            # Listen for client messages
            async for message in websocket:
                await self._handle_message(websocket, message)

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Client {client_id} disconnected")
        finally:
            self.clients.discard(websocket)

    async def _handle_message(self, websocket: WebSocketServerProtocol, raw: str):
        """Process an incoming message from the frontend."""
        try:
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            if msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))

            elif msg_type == "override_stage":
                # Manual stage override (for testing)
                stage = msg.get("stage", "")
                if stage:
                    self.latest_state.stage = stage
                    logger.info(f"Stage manually overridden to: {stage}")

            elif msg_type == "override_components":
                # Manual component override (for testing)
                components = msg.get("components", [])
                self.latest_state.component_ids = components
                logger.info(f"Components manually overridden: {components}")

            elif msg_type == "request_state":
                await self._send_state(websocket)

            elif msg_type == "set_capture_fps":
                fps = msg.get("fps", CAPTURE_FPS)
                self.capture._frame_interval = 1.0 / max(1, min(fps, 10))
                logger.info(f"Capture FPS set to: {fps}")

            elif msg_type == "request_game_data":
                await websocket.send(self._build_game_data_payload())

            else:
                logger.debug(f"Unknown message type: {msg_type}")

        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from client: {raw[:100]}")

    async def _send_state(self, websocket: WebSocketServerProtocol):
        """Send the latest game state to a specific client."""
        try:
            payload = json.dumps({
                "type": "game_state",
                "data": self.latest_state.to_frontend_json(),
                "stats": {
                    "frames_processed": self._frames_processed,
                    "avg_detection_ms": (
                        self._total_detection_ms / self._frames_processed
                        if self._frames_processed > 0 else 0
                    ),
                    "connected_clients": len(self.clients),
                },
            })
            await websocket.send(payload)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def _broadcast_state(self):
        """Send the latest game state to ALL connected clients."""
        if not self.clients:
            return

        payload = json.dumps({
            "type": "game_state",
            "data": self.latest_state.to_frontend_json(),
            "stats": {
                "frames_processed": self._frames_processed,
                "avg_detection_ms": (
                    self._total_detection_ms / self._frames_processed
                    if self._frames_processed > 0 else 0
                ),
                "connected_clients": len(self.clients),
            },
        })

        # Broadcast to all clients, removing dead connections
        dead = set()
        for client in self.clients:
            try:
                await client.send(payload)
            except websockets.exceptions.ConnectionClosed:
                dead.add(client)

        self.clients -= dead

    # ── Capture Loop ──────────────────────────────────────────────────────────

    async def _capture_loop(self):
        """
        Main loop: capture → detect → coach → broadcast.
        Runs continuously while the server is active.
        """
        game_found_logged = False
        game_lost_logged = False

        while self.is_running:
            try:
                # Try to find the game window
                if not self.capture.is_game_visible:
                    if self.capture.locate_game():
                        game_found_logged = True
                        game_lost_logged = False
                        logger.info("Game window detected — starting capture")
                    else:
                        if not game_lost_logged:
                            logger.info("Waiting for game window...")
                            game_lost_logged = True
                            game_found_logged = False

                        # Send "not in game" state
                        self.latest_state = GameState(phase=GamePhase.NOT_IN_GAME)
                        await self._broadcast_state()
                        await asyncio.sleep(2.0)  # Check less frequently when no game
                        continue

                # Capture frame
                frame = self.capture.grab_frame()
                if frame is None:
                    await asyncio.sleep(0.5)
                    continue

                # Run detection (CPU-intensive — run in executor to avoid blocking)
                loop = asyncio.get_event_loop()
                state = await loop.run_in_executor(
                    None, self.detector.detect, frame
                )

                # Run coaching logic
                advice = self.coach.analyze(state)
                state.advice = advice

                # Update latest state
                self.latest_state = state
                self._frames_processed += 1
                self._total_detection_ms += state.detection_ms

                # Broadcast to connected frontends
                await self._broadcast_state()

                # Log periodically
                if self._frames_processed % 30 == 0:
                    avg_ms = self._total_detection_ms / self._frames_processed
                    logger.info(
                        f"Frame {self._frames_processed}: "
                        f"stage={state.stage} hp={state.player_hp} "
                        f"gold={state.gold} components={len(state.component_ids)} "
                        f"detection={state.detection_ms:.1f}ms (avg {avg_ms:.1f}ms)"
                    )

                # Yield to event loop
                await asyncio.sleep(0)

            except Exception as e:
                logger.error(f"Capture loop error: {e}", exc_info=True)
                await asyncio.sleep(1.0)
