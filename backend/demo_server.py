"""
Enhanced Demo Server

Simulates a realistic TFT game for frontend development and testing.
Models actual game mechanics: round timing, PvE drops, econ with
interest, win/loss streaks, leveling, augment rounds, carousel,
and a full game arc from stage 1 through elimination or victory.

Usage:
    python backend/main.py --demo
    python backend/main.py --demo --debug    (verbose tick logging)

The demo cycles through different game scenarios to exercise all
coaching features — component hoarding, loss streaks, low HP, etc.

honestly doesn't work very well, may be more effort to fix than to just capture real games, but it's here if you want to tinker with it
i didn't make this very well
"""

from __future__ import annotations
import asyncio
import json
import logging
import random
import time
from typing import Set, Optional

import websockets
from websockets.server import WebSocketServerProtocol

from config import WEBSOCKET_HOST, WEBSOCKET_PORT
from game_state import (
    GameState,
    GamePhase,
    DetectedComponent,
    DetectedChampion,
    DetectedAugment,
    DetectionConfidence,
)
from coach import Coach

logger = logging.getLogger(__name__)


# ── Game Data ─────────────────────────────────────────────────────────────────

ROUND_SEQUENCE = [
    ("1-1", "pve"), ("1-2", "pve"), ("1-3", "pve"), ("1-4", "pve"),
    ("2-1", "pvp"), ("2-2", "pvp"), ("2-3", "pvp"), ("2-4", "pvp"),
    ("2-5", "carousel"), ("2-6", "pvp"), ("2-7", "pvp"),
    ("3-1", "pvp"), ("3-2", "augment"), ("3-3", "pvp"), ("3-4", "pvp"),
    ("3-5", "carousel"), ("3-6", "pvp"), ("3-7", "pvp"),
    ("4-1", "pvp"), ("4-2", "augment"), ("4-3", "pvp"), ("4-4", "pvp"),
    ("4-5", "carousel"), ("4-6", "pvp"), ("4-7", "pvp"),
    ("5-1", "pvp"), ("5-2", "pvp"), ("5-3", "pvp"), ("5-4", "pvp"),
    ("5-5", "carousel"), ("5-6", "pvp"), ("5-7", "pvp"),
]

COMPONENTS = [
    "bf_sword", "needlessly_large_rod", "giants_belt", "chain_vest",
    "negatron_cloak", "recurve_bow", "tear", "sparring_gloves",
]

CHAMPION_POOL = [
    ("Warwick", 1, "tank"), ("Darius", 1, "tank"), ("Poppy", 1, "tank"),
    ("Caitlyn", 1, "carry"), ("Ziggs", 1, "carry"), ("Twisted Fate", 1, "support"),
    ("Vi", 2, "tank"), ("Shen", 2, "tank"), ("Lux", 2, "support"),
    ("Zeri", 2, "carry"), ("Kog'Maw", 2, "carry"), ("Vex", 2, "tank"),
    ("Ekko", 3, "carry"), ("Senna", 3, "carry"), ("Morgana", 3, "support"),
    ("Cho'Gath", 3, "tank"), ("Illaoi", 3, "tank"), ("LeBlanc", 3, "carry"),
    ("Jinx", 4, "carry"), ("Jayce", 4, "tank"), ("Jhin", 4, "carry"),
    ("Zac", 4, "tank"), ("Ahri", 4, "carry"), ("Urgot", 4, "tank"),
    ("Kai'Sa", 5, "carry"), ("Silco", 5, "support"), ("Viktor", 5, "carry"),
]

AUGMENTS = [
    ("Cybernetic Implants", "Silver", "combat"),
    ("Featherweights", "Silver", "combat"),
    ("Metabolic Accelerator", "Silver", "sustain"),
    ("Electrocharge", "Silver", "combat"),
    ("Component Grab Bag", "Silver", "items"),
    ("Verdant Veil", "Silver", "combat"),
    ("Level Up!", "Gold", "econ"),
    ("Portable Forge", "Gold", "items"),
    ("Jeweled Lotus", "Gold", "combat"),
    ("Pandora's Items", "Gold", "items"),
    ("Ascension", "Prismatic", "combat"),
    ("Living Forge", "Prismatic", "items"),
]

SCENARIOS = [
    {
        "name": "Component Hoarder",
        "desc": "Collects components but doesn't slam — triggers item slam advice",
        "slam_tendency": 0.1,
        "econ_skill": 0.7,
        "fight_skill": 0.3,
    },
    {
        "name": "Aggressive Slammer",
        "desc": "Slams items early — shows strong item recommendations",
        "slam_tendency": 0.95,
        "econ_skill": 0.5,
        "fight_skill": 0.7,
    },
    {
        "name": "Greedy Econ",
        "desc": "High gold, low HP — triggers HP danger warnings",
        "slam_tendency": 0.5,
        "econ_skill": 0.95,
        "fight_skill": 0.35,
    },
    {
        "name": "Loss Streaker",
        "desc": "Intentional early losses — triggers loss streak detection",
        "slam_tendency": 0.3,
        "econ_skill": 0.8,
        "fight_skill": 0.15,
    },
]


# ── Game Simulation ───────────────────────────────────────────────────────────

class SimulatedGame:
    """Simulates a full TFT game with realistic mechanics."""

    def __init__(self, scenario: Optional[dict] = None):
        self.scenario = scenario or random.choice(SCENARIOS)
        self.round_index = 0
        self.hp = 100
        self.gold = 0
        self.level = 1
        self.xp = 0
        self.xp_needed = 2
        self.components: list[str] = []
        self.completed_items: list[str] = []
        self.board: list[dict] = []
        self.bench: list[dict] = []
        self.win_streak = 0
        self.loss_streak = 0
        self.chosen_augments: list[str] = []
        self.current_augment_choices: list[tuple] = []
        self.round_tick = 0
        self.ticks_per_round = 6
        self.is_over = False
        self.placement = 0

        logger.info(f"Scenario: {self.scenario['name']} — {self.scenario['desc']}")

    @property
    def stage(self) -> str:
        if self.round_index >= len(ROUND_SEQUENCE):
            return "5-7"
        return ROUND_SEQUENCE[self.round_index][0]

    @property
    def round_type(self) -> str:
        if self.round_index >= len(ROUND_SEQUENCE):
            return "pvp"
        return ROUND_SEQUENCE[self.round_index][1]

    def tick(self) -> GameState:
        """Advance one tick and return state."""
        self.round_tick += 1
        if self.round_tick >= self.ticks_per_round:
            self.round_tick = 0
            self._advance_round()
        return self._build_state()

    def _advance_round(self):
        if self.is_over:
            return

        rtype = self.round_type
        if rtype == "pve":
            self._process_pve()
        elif rtype == "pvp":
            self._process_pvp()
        elif rtype == "carousel":
            self._process_carousel()
        elif rtype == "augment":
            self._process_augment()

        self._gain_xp()

        if self.hp <= 0:
            self.is_over = True
            self.placement = random.randint(5, 8)
            logger.info(f"Game over — placement #{self.placement}")
            return

        self.round_index = min(self.round_index + 1, len(ROUND_SEQUENCE) - 1)

        # Maybe slam items based on scenario tendency
        if random.random() < self.scenario["slam_tendency"] and len(self.components) >= 2:
            self.components.pop(0)
            if self.components:
                self.components.pop(0)
            self.completed_items.append("slammed_item")

    def _process_pve(self):
        self.gold += 3 + random.randint(0, 1)
        if random.random() < 0.7:
            self.components.append(random.choice(COMPONENTS))
        if random.random() < 0.2:
            self.components.append(random.choice(COMPONENTS))
        if random.random() < 0.5:
            pool = [c for c in CHAMPION_POOL if c[1] <= 2]
            self._add_to_bench(random.choice(pool))

    def _process_pvp(self):
        board_power = (
            len(self.board) * 2
            + len(self.completed_items) * 3
            + self.level
            + sum(u.get("star", 1) for u in self.board)
        )
        roll = random.random() * 50 + board_power * self.scenario["fight_skill"]
        won = roll > 25

        if won:
            self.win_streak += 1
            self.loss_streak = 0
        else:
            self.loss_streak += 1
            self.win_streak = 0
            stage_num = float(self.stage.replace("-", "."))
            dmg = max(2, int(stage_num * 2)) + random.randint(0, int(stage_num * 1.5))
            self.hp = max(0, self.hp - dmg)

        interest = min(self.gold // 10, 5)
        streak_gold = min(max(self.win_streak, self.loss_streak), 3)
        self.gold += 5 + interest + streak_gold

        # Spend sometimes
        if self.scenario["econ_skill"] < 0.6 or self.gold > 60:
            self.gold = max(0, self.gold - random.randint(0, min(15, self.gold)))

    def _process_carousel(self):
        self.components.append(random.choice(COMPONENTS))
        self.gold += 1

    def _process_augment(self):
        tier_pool = {
            "3-2": [a for a in AUGMENTS if a[1] in ("Silver", "Gold")],
            "4-2": [a for a in AUGMENTS if a[1] in ("Gold", "Prismatic")],
        }
        pool = tier_pool.get(self.stage, AUGMENTS)
        self.current_augment_choices = random.sample(pool, min(3, len(pool)))
        if self.current_augment_choices:
            self.chosen_augments.append(self.current_augment_choices[0][0])

    def _gain_xp(self):
        stage_num = int(self.stage.split("-")[0])
        if stage_num >= 2:
            self.xp += 2
        thresholds = {1: 2, 2: 2, 3: 6, 4: 10, 5: 20, 6: 36, 7: 56, 8: 80}
        threshold = thresholds.get(self.level, 100)
        while self.xp >= threshold and self.level < 9:
            self.xp -= threshold
            self.level += 1
            self.xp_needed = thresholds.get(self.level, 100)
            self._fill_board()
            threshold = thresholds.get(self.level, 100)

    def _add_to_bench(self, champ_tuple):
        name, cost, role = champ_tuple
        if len(self.bench) < 9:
            self.bench.append({"name": name, "cost": cost, "role": role, "star": 1})

    def _fill_board(self):
        while len(self.board) < self.level:
            if self.bench:
                unit = self.bench.pop(0)
            else:
                max_cost = min(self.level, 5)
                pool = [c for c in CHAMPION_POOL if c[1] <= max_cost]
                champ = random.choice(pool)
                unit = {"name": champ[0], "cost": champ[1], "role": champ[2], "star": 1}

            row, col = self._get_position(unit["role"])
            unit["row"] = row
            unit["col"] = col
            self.board.append(unit)

    def _get_position(self, role: str) -> tuple[int, int]:
        used = {(u.get("row", -1), u.get("col", -1)) for u in self.board}
        if role == "tank":
            preferred = [(3, c) for c in range(7)] + [(2, c) for c in range(7)]
        elif role == "carry":
            preferred = [(0, 6), (0, 5), (0, 0), (0, 1), (1, 6), (1, 5)]
        else:
            preferred = [(0, 3), (0, 4), (1, 3), (1, 4), (0, 2)]
        for pos in preferred:
            if pos not in used:
                return pos
        for r in range(4):
            for c in range(7):
                if (r, c) not in used:
                    return (r, c)
        return (0, 0)

    def _build_state(self) -> GameState:
        rtype = self.round_type
        if self.is_over:
            phase = GamePhase.GAME_OVER
        elif rtype == "augment" and self.round_tick < 3:
            phase = GamePhase.AUGMENT_SELECT
        elif rtype == "carousel":
            phase = GamePhase.CAROUSEL
        elif self.round_tick < 2:
            phase = GamePhase.PLANNING
        else:
            phase = GamePhase.COMBAT

        board_champs = [
            DetectedChampion(
                name=u["name"], star_level=u.get("star", 1), cost=u["cost"],
                board_row=u.get("row", 0), board_col=u.get("col", 0),
                confidence=0.82 + random.random() * 0.15,
            )
            for u in self.board
        ]

        bench_champs = [
            DetectedChampion(
                name=u["name"], star_level=u.get("star", 1), cost=u["cost"],
                confidence=0.80 + random.random() * 0.12,
            )
            for u in self.bench[:9]
        ]

        augment_options = []
        if phase == GamePhase.AUGMENT_SELECT and self.current_augment_choices:
            augment_options = [
                DetectedAugment(name=n, tier=t, slot_index=i, confidence=0.65 + random.random() * 0.2)
                for i, (n, t, _) in enumerate(self.current_augment_choices)
            ]

        return GameState(
            frame_number=self.round_index * self.ticks_per_round + self.round_tick,
            phase=phase,
            phase_confidence=0.88 + random.random() * 0.1,
            stage=self.stage,
            stage_confidence=0.92 + random.random() * 0.06,
            player_hp=self.hp,
            gold=self.gold,
            level=self.level,
            xp_current=self.xp,
            xp_needed=self.xp_needed,
            component_ids=list(self.components),
            held_components=[
                DetectedComponent(component_id=c, confidence=0.85 + random.random() * 0.1)
                for c in self.components
            ],
            board_champions=board_champs,
            bench_champions=bench_champs,
            augment_options=augment_options,
            selected_augments=list(self.chosen_augments),
            overall_confidence=DetectionConfidence.HIGH,
        )


# ── Server ────────────────────────────────────────────────────────────────────

class DemoServer:
    """WebSocket server running simulated TFT games in a loop."""

    def __init__(self):
        self.clients: Set[WebSocketServerProtocol] = set()
        self.coach = Coach()
        self.is_running = False
        self._game: Optional[SimulatedGame] = None
        self._scenario_index = 0
        self._tick = 0
        self._paused = False

    async def start(self):
        logger.info(f"Demo server starting on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
        self.is_running = True
        async with websockets.serve(
            self._handle_client, WEBSOCKET_HOST, WEBSOCKET_PORT, ping_interval=20,
        ):
            logger.info("Demo server running — connect frontend at http://localhost:5173")
            logger.info("Scenarios:")
            for i, s in enumerate(SCENARIOS):
                logger.info(f"  [{i}] {s['name']}: {s['desc']}")
            await self._simulation_loop()

    async def stop(self):
        self.is_running = False

    async def _handle_client(self, websocket: WebSocketServerProtocol):
        self.clients.add(websocket)
        logger.info(f"Frontend connected. Clients: {len(self.clients)}")
        try:
            async for raw in websocket:
                await self._handle_message(websocket, raw)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)

    async def _handle_message(self, websocket: WebSocketServerProtocol, raw: str):
        try:
            msg = json.loads(raw)
            t = msg.get("type", "")

            if t == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
            elif t == "restart_game":
                idx = msg.get("scenario")
                if idx is not None and 0 <= idx < len(SCENARIOS):
                    self._game = SimulatedGame(SCENARIOS[idx])
                else:
                    self._game = SimulatedGame()
                logger.info(f"Game restarted: {self._game.scenario['name']}")
            elif t == "pause":
                self._paused = not self._paused
                logger.info(f"Demo {'paused' if self._paused else 'resumed'}")
            elif t == "next_round":
                if self._game:
                    self._game.round_tick = self._game.ticks_per_round - 1
            elif t == "override_components":
                if self._game:
                    self._game.components = msg.get("components", [])
            elif t == "override_stage":
                if self._game:
                    target = msg.get("stage", "")
                    for i, (s, _) in enumerate(ROUND_SEQUENCE):
                        if s == target:
                            self._game.round_index = i
                            break
        except json.JSONDecodeError:
            pass

    async def _simulation_loop(self):
        while self.is_running:
            scenario = SCENARIOS[self._scenario_index % len(SCENARIOS)]
            self._game = SimulatedGame(scenario)
            self._scenario_index += 1

            logger.info(f"{'=' * 50}")
            logger.info(f"Starting game: {scenario['name']}")
            logger.info(f"{'=' * 50}")

            while self.is_running and not self._game.is_over:
                if self._paused:
                    await asyncio.sleep(0.5)
                    continue

                self._tick += 1
                state = self._game.tick()
                advice = self.coach.analyze(state)
                state.advice = advice
                await self._broadcast(state)
                await asyncio.sleep(0.5)

            if self._game and self._game.is_over:
                logger.info(f"Game ended — placement #{self._game.placement}")
                for _ in range(6):
                    state = self._game._build_state()
                    state.advice = self.coach.analyze(state)
                    await self._broadcast(state)
                    await asyncio.sleep(0.5)
                logger.info("Next game in 3 seconds...")
                await asyncio.sleep(3.0)

    async def _broadcast(self, state: GameState):
        if not self.clients:
            return
        scenario_name = self._game.scenario["name"] if self._game else "None"
        payload = json.dumps({
            "type": "game_state",
            "data": state.to_frontend_json(),
            "demo": True,
            "scenario": scenario_name,
            "stats": {
                "frames_processed": self._tick,
                "avg_detection_ms": 11.3 + random.random() * 5,
                "connected_clients": len(self.clients),
            },
        })
        dead = set()
        for client in self.clients:
            try:
                await client.send(payload)
            except websockets.exceptions.ConnectionClosed:
                dead.add(client)
        self.clients -= dead
