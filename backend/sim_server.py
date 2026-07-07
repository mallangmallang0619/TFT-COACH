"""
Simulation Server — drive the real frontend with synthesized screenshots.

Unlike demo_server.py (which fabricates GameState objects directly), this server
runs the *actual* CV + coaching pipeline: it synthesizes a board frame from the
real champion portrait templates (see simulate_screenshot.py), runs the real
Detector and Coach on it, then broadcasts the result over the same WebSocket the
live capture server uses. So the frontend renders genuine detector → coach output
with deterministic, repeatable input — useful for UI work without a live game.

It cycles through a rotation of comps (from the TFT Academy cache), spending a few
seconds on each so you can watch the overlay update as the "board" changes.

Usage:
    python backend/main.py --sim
    python backend/main.py --sim --debug
    # rotation + timing are configurable in main.py via --sim-comps / --sim-dwell
"""

from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional, Set

from websocket_server import TFTCoachServer
from detector import Detector, TemplateStore
from coach import Coach
from game_state import GameState, GamePhase
import simulate_screenshot as sim

logger = logging.getLogger(__name__)

# Default rotation: a spread of S/A/B/C comps that all have champion templates.
DEFAULT_COMPS = [
    "set-17-the-big-bang-meepsie",
    "set-17-gnar-printer",
    "set-17-samira-knock-up-copy",
    "set-17-dark-star",
    "set-17-invader-zed",
]

# Per-board "ground-truth" HUD stats. The synthetic frame has no real HUD digits
# for OCR to read, so we stamp plausible values onto the state after detection,
# keyed by how far into the rotation we are (gives the overlay some variety).
_HUD_CYCLE = [
    {"stage": "3-5", "player_hp": 78, "gold": 52, "level": 8},
    {"stage": "4-1", "player_hp": 61, "gold": 40, "level": 8},
    {"stage": "4-6", "player_hp": 44, "gold": 30, "level": 9},
    {"stage": "3-2", "player_hp": 90, "gold": 48, "level": 7},
    {"stage": "5-1", "player_hp": 33, "gold": 22, "level": 9},
]


@dataclass
class _Board:
    """A precomputed rotation entry."""
    slug: str
    label: str
    state: Optional[GameState] = None  # cached after first detection


class SimulationServer(TFTCoachServer):
    """TFTCoachServer variant whose frame source is synthesized comps."""

    def __init__(self, comps: Optional[list[str]] = None, dwell_seconds: float = 6.0):
        # Deliberately do NOT call super().__init__(): it constructs a
        # ScreenCapture (and imports mss / grabs a display handle), which sim
        # mode doesn't need. We replicate just the fields the server uses.
        self.templates = TemplateStore()
        self.detector = Detector(self.templates)
        self.coach = Coach()

        self.clients: Set = set()
        self.latest_state: GameState = GameState()
        self.is_running = False
        self._frames_processed = 0
        self._total_detection_ms = 0.0

        self.dwell_seconds = dwell_seconds
        self.boards = [_Board(slug=s, label=s) for s in (comps or DEFAULT_COMPS)]
        self._idx = 0

    # ── Frame source ──────────────────────────────────────────────────────────

    def _compute_board(self, board: _Board, hud: dict) -> GameState:
        """Synthesize → detect → stamp ground truth → coach for one board."""
        units, label = sim.units_from_comp(board.slug)
        board.label = label
        frame = sim.synthesize_frame(units, self.templates)

        state = self.detector.detect(frame)

        # The synthetic frame is a planning board; force the phase in case the
        # heuristic wavers, and stamp HUD stats OCR can't read off fake digits.
        state.phase = GamePhase.PLANNING
        state.stage = hud["stage"]
        state.stage_confidence = 0.9
        state.player_hp = hud["player_hp"]
        state.gold = hud["gold"]
        state.level = hud["level"]

        # Stamp intended star levels (CV can't read pips yet) so board power and
        # comp-direction advice reflect the real comp.
        stars = sim.star_map(units)
        for champ in state.board_champions:
            champ.star_level = stars.get((champ.board_row, champ.board_col), 1)

        advice = self.coach.analyze(state)
        state.advice = advice
        return state

    async def _capture_loop(self):
        """Rotate through synthesized boards, broadcasting each via the real loop."""
        logger.info(
            f"SIM MODE — rotating {len(self.boards)} boards, "
            f"{self.dwell_seconds:.0f}s each. Connect the frontend to watch."
        )
        loop = asyncio.get_event_loop()

        while self.is_running:
            board = self.boards[self._idx]
            hud = _HUD_CYCLE[self._idx % len(_HUD_CYCLE)]

            if board.state is None:
                # Detection is CPU-heavy (~1s); run it off the event loop so
                # WebSocket pings/handshakes aren't starved.
                try:
                    board.state = await loop.run_in_executor(
                        None, self._compute_board, board, hud
                    )
                except Exception as e:
                    logger.error(f"Failed to build board {board.slug!r}: {e}",
                                 exc_info=True)
                    self._idx = (self._idx + 1) % len(self.boards)
                    await asyncio.sleep(0.5)
                    continue

            self.latest_state = board.state
            self._frames_processed += 1
            self._total_detection_ms += board.state.detection_ms

            champ_names = [c.name for c in board.state.board_champions]
            logger.info(
                f"▶ {board.label} — {len(champ_names)} champs, "
                f"power {board.state.advice.board_power if board.state.advice else '—'}: "
                f"{', '.join(champ_names)}"
            )
            await self._broadcast_state()

            self._idx = (self._idx + 1) % len(self.boards)
            await asyncio.sleep(self.dwell_seconds)
