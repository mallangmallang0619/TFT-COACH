"""
 WebSocket Server

Async WebSocket server that:
  1. Runs the capture → detect → coach pipeline in a loop
  2. Broadcasts the latest game state to all connected frontend clients
  3. Handles client messages (e.g., manual overrides, settings changes)
"""

from __future__ import annotations
import asyncio
import datetime
import json
import logging
import os
import time
from pathlib import Path
from typing import Set

import cv2
import websockets
from websockets.server import WebSocketServerProtocol

from config import WEBSOCKET_HOST, WEBSOCKET_PORT, CAPTURE_FPS
from capture import ScreenCapture
from detector import Detector, TemplateStore
from coach import Coach
from harvest import BenchHarvester, training_stats
from roster import RosterTracker
from augment_tracker import AugmentSelectionTracker, WindowsClickMonitor
from game_state import GameState, GamePhase, TrainingCollectionStatus
from game_data import (
    ACTIVE_ENGINE,
    ACTIVE_SET_NAME,
    ACTIVE_SET_NUMBER,
    ITEM_RECIPES,
    COMPONENT_IDS,
    COMPONENT_NAMES,
    SHRED_ITEMS,
    BURN_ITEMS,
)
from unit_details import UnitDetailCollector, unit_detail_collection_enabled
import tftacademy_live
import tactics_live

logger = logging.getLogger(__name__)

_COLLECTION_DIAGNOSTIC_INTERVAL_SECONDS = 120.0
_COLLECTION_DIAGNOSTIC_MIN_EVENT_GAP_SECONDS = 10.0
_COLLECTION_DIAGNOSTIC_PURCHASE_GAP_SECONDS = 5.0
_COLLECTION_DIAGNOSTIC_KEEP = 12
_COLLECTION_DIAGNOSTIC_DIR = Path(__file__).parent / "_debug" / "session"


def _apply_purchase_roster_fallback(
    state: GameState,
    owned_units: list,
) -> None:
    """Use purchase history only when the classifier saw no live units.

    Purchase history cannot observe sells. Mixing it into a classifier-read
    board/bench lets stale units distort comp selection and overwrites the
    honest detection source.
    """
    if state.board_champions or state.bench_champions or not owned_units:
        return
    state.bench_champions = list(owned_units)
    state.unit_detection_source = "purchase_roster"


def _coaching_state_with_roster_fallback(
    state: GameState,
    owned_units: list,
) -> GameState:
    """Return a coaching-only roster estimate without changing live UI data."""
    if state.board_champions or state.bench_champions or not owned_units:
        return state
    coaching_state = state.model_copy(deep=True)
    _apply_purchase_roster_fallback(coaching_state, owned_units)
    return coaching_state


def _collection_diagnostic_due(
    now: float,
    last_saved_at: float,
    *,
    capture_changed: bool = False,
    purchase_event: bool = False,
) -> bool:
    """Return whether periodic or event evidence should be persisted."""
    elapsed = now - last_saved_at
    return (
        elapsed >= _COLLECTION_DIAGNOSTIC_INTERVAL_SECONDS
        or (
            capture_changed
            and elapsed >= _COLLECTION_DIAGNOSTIC_MIN_EVENT_GAP_SECONDS
        )
        or (
            purchase_event
            and elapsed >= _COLLECTION_DIAGNOSTIC_PURCHASE_GAP_SECONDS
        )
    )


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
        self.roster = RosterTracker()
        # Set 18 UE5 animations made shop-to-bench auto-labels too noisy.
        # Collect many unlabeled board/bench crops instead; the developer sorts
        # them afterward with scripts/sort_training_inbox.py.
        collect_unit_details = unit_detail_collection_enabled(
            os.environ.get("TFT_COACH_COLLECT_UNIT_DETAILS")
        )
        detail_collector = UnitDetailCollector() if collect_unit_details else None
        self.harvester = BenchHarvester(
            manual_inbox=True,
            detail_collector=detail_collector,
        )
        if detail_collector is not None:
            logger.info(
                "Star/item training collection enabled at %s",
                detail_collector.out_dir,
            )
        self.augment_click_monitor = WindowsClickMonitor()
        self.augment_selection_tracker = AugmentSelectionTracker()

        # Hex template matching can't identify live 3D unit models and eats
        # ~2.3s/frame — turn it off so the loop runs at real capture FPS.
        # The roster (shop tracking) supplies held units instead.
        self.detector.match_board_units = False
        self.detector.stabilize_unit_predictions = True

        self.clients: Set[WebSocketServerProtocol] = set()
        self.latest_state: GameState = GameState()
        self.is_running = False

        # Stats
        self._frames_processed = 0
        self._total_detection_ms = 0.0
        # Pending large HP change awaiting a confirming second frame.
        self._hp_candidate: int | None = None
        self._not_in_game_frames = 0
        self._tracking_session_active = False
        self._selected_augments: list[str] = []
        # Comp the player locked via the UI (None = follow suggestions).
        self._pinned_comp: str | None = None
        self._initial_reviewed_crop_count = 0
        self._last_capture_method: str | None = None
        self._last_diagnostic_at = 0.0
        self._last_diagnostic_path: str | None = None

    def _reset_tracking_session(self) -> None:
        """Drop frame-to-frame state when the game window changes or closes."""
        self.roster.reset()
        self.harvester.reset()
        self._hp_candidate = None
        self._not_in_game_frames = 0
        self._tracking_session_active = False
        self._selected_augments.clear()
        self.augment_selection_tracker.reset()

    async def start(self):
        """Start the WebSocket server and capture loop."""
        logger.info(f"Starting TFT Coach server on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")

        # Load templates
        logger.info("Loading template images...")
        self.templates.load()
        crop_count, champion_count, ready_count = training_stats()
        self._initial_reviewed_crop_count = (
            self.harvester.manual_inbox_count()
            if self.harvester.manual_inbox
            else crop_count
        )
        if self.harvester.manual_inbox:
            logger.info(
                "Manual training inbox active; "
                f"{self._initial_reviewed_crop_count} unsorted crops waiting in "
                f"{self.harvester.out_dir / '_inbox'}"
            )
        if self.detector.unit_classifier.available:
            logger.info(
                f"Unit classifier active ({len(self.detector.unit_classifier.labels)} classes)"
            )
        else:
            logger.info(
                "Unit classifier inactive (no trained model); "
                f"collector has {crop_count} crops across {champion_count} champions, "
                f"{ready_count} ready at 50+ reviewed crops"
            )

        # Background refresh of the TFT Academy tier list (cache-checked,
        # debounced — does nothing if recently refreshed). include_details
        # pulls per-comp unit/item/augment data so the comp matcher can
        # surface accurate "you have X, need Y" suggestions.
        tftacademy_live.schedule_background_refresh(
            initial_delay_seconds=2.0,
            include_details=True,
        )
        tactics_live.schedule_periodic_refresh(initial_delay_seconds=3.0)

        # Start WebSocket server and capture loop concurrently. The click
        # monitor is read-only and exists solely to map a confirmed augment
        # screen exit back to one of the three OCR'd card slots.
        if self.augment_click_monitor.start():
            logger.info("Automatic augment selection tracking active")
        self.is_running = True
        try:
            async with websockets.serve(
                self._handle_client,
                WEBSOCKET_HOST,
                WEBSOCKET_PORT,
                ping_interval=20,
                ping_timeout=10,
            ):
                logger.info("WebSocket server started. Waiting for frontend connection...")
                await self._capture_loop()
        finally:
            self.augment_click_monitor.stop()

    async def stop(self):
        """Gracefully shut down the server."""
        self.is_running = False
        self.augment_click_monitor.stop()
        self.capture.close()
        for client in self.clients.copy():
            await client.close()
        logger.info("Server stopped.")

    # ── WebSocket Handlers ────────────────────────────────────────────────────

    # ── Game Data Payload ─────────────────────────────────────────────────────

    def _build_game_data_payload(self) -> str:
        """Serialize game_data.py into a JSON message for the frontend."""
        from config import PROTOCOL_VERSION
        crop_count, champion_count, ready_count = training_stats()
        return json.dumps({
            "type": "game_data",
            "protocol": PROTOCOL_VERSION,
            "set": {
                "number": ACTIVE_SET_NUMBER,
                "name": ACTIVE_SET_NAME,
                "engine": ACTIVE_ENGINE,
            },
            "classifier_status": {
                "active": self.detector.unit_classifier.available,
                "dataset": f"set{ACTIVE_SET_NUMBER}",
                "crops": crop_count,
                "champions": champion_count,
                "ready_classes": ready_count,
            },
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
        tactics_live.schedule_background_refresh(initial_delay_seconds=0.0)

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

            elif msg_type == "pin_comp":
                # Player clicked a comp to lock it as their direction
                # (null/empty name unpins).
                self._pinned_comp = (msg.get("name") or "").strip() or None
                logger.info(f"Comp pinned: {self._pinned_comp or '(unpinned)'}")

            elif msg_type == "select_augment":
                name = (msg.get("name") or "").strip()
                selected = bool(msg.get("selected", True))
                if name:
                    if selected and name not in self._selected_augments:
                        self._selected_augments.append(name)
                    elif not selected and name in self._selected_augments:
                        self._selected_augments.remove(name)
                    logger.info(f"Selected augments: {self._selected_augments}")

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

        # Broadcast to all clients, removing dead connections. Iterate over a
        # snapshot — clients can connect/disconnect (mutating the set) while
        # we're suspended in await client.send().
        dead = set()
        for client in tuple(self.clients):
            try:
                await client.send(payload)
            except websockets.exceptions.ConnectionClosed:
                dead.add(client)

        self.clients -= dead

    def _collection_status(
        self,
        state: GameState,
        purchases: list[str],
    ) -> TrainingCollectionStatus:
        telemetry = self.harvester.telemetry()
        trusted = self.capture.is_training_capture_trusted
        readable_shop = sum(bool(name) for name in state.shop_units)

        if not trusted:
            collection_state = "paused"
            reason = self.capture.capture_trust_reason
        elif self.harvester.manual_inbox and state.phase != GamePhase.PLANNING:
            collection_state = "waiting"
            reason = "Waiting for planning phase to avoid moving/combat units"
        elif (
            self.harvester.manual_inbox
            and telemetry["manual_inbox_cap"] is not None
            and telemetry["inbox_crops"] >= telemetry["manual_inbox_cap"]
        ):
            collection_state = "waiting"
            reason = "Manual inbox full; sort or reject crops to resume"
        elif (
            self.harvester.manual_inbox
            and telemetry["manual_game_cap"] is not None
            and telemetry["manual_game_crops"] >= telemetry["manual_game_cap"]
        ):
            collection_state = "waiting"
            reason = "This game reached its training-crop limit"
        elif state.phase not in {GamePhase.PLANNING, GamePhase.COMBAT, GamePhase.PVE}:
            collection_state = "waiting"
            reason = f"Waiting during {state.phase.value.replace('_', ' ')}"
        elif self.harvester.manual_inbox:
            collection_state = "collecting"
            reason = "Manual inbox: collecting visible board and bench units"
        elif readable_shop == 0:
            collection_state = "waiting"
            reason = "Capture is trusted, but no champion names are readable in the shop"
        elif purchases:
            collection_state = "collecting"
            reason = f"Confirmed purchase: {', '.join(purchases)}"
        elif self.roster.pending_purchase_names:
            collection_state = "collecting"
            reason = (
                "Confirming purchase: "
                + ", ".join(self.roster.pending_purchase_names)
            )
        else:
            collection_state = "collecting"
            reason = f"Watching {readable_shop}/5 readable shop slots"

        return TrainingCollectionStatus(
            mode=telemetry["mode"],
            state=collection_state,
            reason=reason,
            capture_trusted=trusted,
            recognized_shop_slots=readable_shop,
            shop_units=list(state.shop_units),
            detected_purchases=list(purchases),
            pending_purchases=list(self.roster.pending_purchase_names),
            session_crops_saved=telemetry["session_crops_saved"],
            total_clean_crops=(
                telemetry["inbox_crops"]
                if self.harvester.manual_inbox
                else self._initial_reviewed_crop_count
                + telemetry["session_crops_saved"]
            ),
            rejected_crops=telemetry["rejected_crops"],
            rejection_reasons=telemetry["rejection_reasons"],
            skipped_events=telemetry["skipped_events"],
            tracked_slots=telemetry["tracked_slots"],
            last_event=telemetry["last_event"],
            last_save_at=telemetry["last_save_at"],
            last_saved_label=telemetry["last_saved_label"],
            last_diagnostic_path=self._last_diagnostic_path,
        )

    def _maybe_save_collection_diagnostic(
        self,
        frame,
        state: GameState,
        *,
        capture_changed: bool = False,
        purchase_event: bool = False,
    ) -> None:
        """Persist a bounded stream of annotated frames for capture debugging."""
        now = time.monotonic()
        if not _collection_diagnostic_due(
            now,
            self._last_diagnostic_at,
            capture_changed=capture_changed,
            purchase_event=purchase_event,
        ):
            return

        annotated = frame.copy()
        height, width = annotated.shape[:2]
        for label, roi, color in (
            ("BENCH CROP", self.detector.rois.champion_bench_capture, (255, 120, 0)),
            ("LANDING STRIP", self.detector.rois.champion_bench, (255, 180, 0)),
            ("SHOP", self.detector.rois.shop, (0, 220, 255)),
        ):
            x, y, rw, rh = roi.to_pixels(width, height)
            cv2.rectangle(annotated, (x, y), (x + rw, y + rh), color, 3)
            cv2.putText(
                annotated,
                label,
                (x + 4, max(24, y - 6)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                color,
                2,
            )

        status = state.collection_status
        lines = [
            f"capture={state.capture_method} trusted={status.capture_trusted}",
            f"shop={status.recognized_shop_slots}/5 purchases={status.detected_purchases}",
            f"saved={status.session_crops_saved} rejected={status.rejected_crops}",
            f"event={(status.last_event or status.reason)[:100]}",
        ]
        for index, line in enumerate(lines):
            cv2.putText(
                annotated,
                line,
                (24, 36 + index * 30),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (255, 255, 255),
                2,
            )

        try:
            _COLLECTION_DIAGNOSTIC_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            event_suffix = "_purchase" if purchase_event else ""
            path = _COLLECTION_DIAGNOSTIC_DIR / (
                f"capture_{stamp}_{state.capture_method}{event_suffix}.jpg"
            )
            if not cv2.imwrite(str(path), annotated, [cv2.IMWRITE_JPEG_QUALITY, 82]):
                logger.warning(f"Could not save collection diagnostic: {path}")
                return
            self._last_diagnostic_at = now
            self._last_diagnostic_path = str(path)
            state.collection_status.last_diagnostic_path = str(path)
            logger.info(f"Collection diagnostic saved: {path}")

            files = sorted(
                _COLLECTION_DIAGNOSTIC_DIR.glob("capture_*.jpg"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for old in files[_COLLECTION_DIAGNOSTIC_KEEP:]:
                try:
                    old.unlink()
                except OSError:
                    pass
        except OSError as error:
            logger.warning(f"Could not save collection diagnostic: {error}")

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
                        self._reset_tracking_session()
                        game_found_logged = True
                        game_lost_logged = False
                        logger.info("Game window detected — starting capture")
                    else:
                        if self._tracking_session_active:
                            self._reset_tracking_session()
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
                    self.roster.suspend_observation()
                    self.harvester.suspend_observation(
                        self.capture.capture_trust_reason
                    )
                    await asyncio.sleep(0.5)
                    continue

                # Run detection (CPU-intensive — run in executor to avoid blocking)
                loop = asyncio.get_event_loop()
                state = await loop.run_in_executor(
                    None, self.detector.detect, frame
                )
                state.capture_method = self.capture.capture_method
                capture_changed = state.capture_method != self._last_capture_method
                if capture_changed:
                    logger.info(
                        f"Capture mode: {state.capture_method} "
                        f"({self.capture.capture_trust_reason})"
                    )
                    self._last_capture_method = state.capture_method

                # Never let launcher/loading/closed-window frames poison the
                # roster or harvester baselines. Two consecutive misses force
                # a fresh window lookup, which also handles a game launched
                # after the backend and windows recreated by display changes.
                if state.phase == GamePhase.NOT_IN_GAME:
                    self._not_in_game_frames += 1
                    self.latest_state = state
                    await self._broadcast_state()
                    if self._not_in_game_frames >= 2:
                        self.capture.window = None
                        self._reset_tracking_session()
                        await asyncio.sleep(0.5)
                    else:
                        await asyncio.sleep(0)
                    continue

                self._not_in_game_frames = 0
                self._tracking_session_active = True

                # Track purchases BEFORE the last-good patching below: the
                # roster's gold-drop guard must see the RAW reading. Patching
                # a failed gold read with the previous frame's value makes
                # gold look readable-but-unchanged, which vetoed every
                # purchase on frames where gold OCR failed — and with it all
                # harvester training crops.
                purchases: list[str] = []
                if self.capture.is_training_capture_trusted:
                    purchases = self.roster.update(state)
                    saved = 0
                    if (
                        not self.harvester.manual_inbox
                        or state.phase == GamePhase.PLANNING
                    ):
                        saved = self.harvester.process(
                            frame,
                            purchases,
                            self.roster.pending_purchase_names,
                        )
                    if purchases:
                        logger.info(
                            f"Confirmed shop purchase(s): {purchases}; "
                            f"shop={state.shop_units}"
                        )
                    if saved:
                        logger.info(
                            f"Saved {saved} training crop(s) this frame; "
                            f"session total={self.harvester.saved_count}"
                        )
                else:
                    # A desktop fallback can contain the overlay, another app,
                    # or a stale TFT frame. Never let it create purchase labels
                    # or training crops. Preserve confirmed owned units, but
                    # require a fresh direct-window shop baseline afterward.
                    self.roster.suspend_observation()
                    self.harvester.suspend_observation(
                        self.capture.capture_trust_reason
                    )

                state.collection_status = self._collection_status(state, purchases)
                self._maybe_save_collection_diagnostic(
                    frame,
                    state,
                    capture_changed=capture_changed,
                    purchase_event=bool(purchases),
                )

                # A single frame's OCR can fail while the region is obscured
                # (combat effects, transitions) — hold the last good reading
                # instead of flashing zeros at the user.
                prev = self.latest_state
                if state.stage in ("?", "") and prev.stage not in ("?", ""):
                    state.stage = prev.stage
                for field in ("player_hp", "gold", "level"):
                    if getattr(state, field) < 0:
                        setattr(state, field, max(0, getattr(prev, field, 0)))

                # Guard HP against single-frame misreads of another player's
                # row (scouting shifts, list animations): a jump bigger than
                # any one round can deal must repeat on the next frame to be
                # believed.
                if (
                    prev.phase != GamePhase.NOT_IN_GAME
                    and prev.player_hp > 0
                    and state.player_hp > 0
                ):
                    if abs(state.player_hp - prev.player_hp) > 25:
                        if (
                            self._hp_candidate is not None
                            and abs(state.player_hp - self._hp_candidate) <= 6
                        ):
                            self._hp_candidate = None   # confirmed twice
                        else:
                            self._hp_candidate = state.player_hp
                            state.player_hp = prev.player_hp
                    else:
                        self._hp_candidate = None

                auto_augment = self.augment_selection_tracker.observe(
                    state.phase,
                    state.augment_options,
                    state.timestamp,
                    self.augment_click_monitor.recent(),
                    self.capture.window,
                )
                if (
                    auto_augment
                    and auto_augment not in self._selected_augments
                ):
                    self._selected_augments.append(auto_augment)
                    logger.info(
                        f"Augment selected automatically: {auto_augment}"
                    )

                # Run coaching logic
                state.pinned_comp = self._pinned_comp
                state.selected_augments = list(self._selected_augments)
                # Purchase history cannot observe sells or board placement.
                # It may keep comp advice useful during a one-frame classifier
                # miss, but must never be broadcast as detected bench units.
                coaching_state = _coaching_state_with_roster_fallback(
                    state, self.roster.owned_units()
                )
                advice = self.coach.analyze(coaching_state)
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
                        f"capture={state.capture_method} "
                        f"shop={state.collection_status.recognized_shop_slots}/5 "
                        f"purchases={state.collection_status.detected_purchases} "
                        f"crops=+{state.collection_status.session_crops_saved} "
                        f"rejected={state.collection_status.rejected_crops} "
                        f"detection={state.detection_ms:.1f}ms (avg {avg_ms:.1f}ms)"
                    )

                # Yield to event loop
                await asyncio.sleep(0)

            except Exception as e:
                logger.error(f"Capture loop error: {e}", exc_info=True)
                await asyncio.sleep(1.0)
