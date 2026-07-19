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
from game_data import ITEM_RECIPES, COMPONENT_IDS, COMPONENT_NAMES, SHRED_ITEMS, BURN_ITEMS
import tftacademy_live

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

# Build the champion pool from the live Set 17 CHAMPIONS dict so the demo
# generates units that the synergy/comp-detection code actually understands.
# We classify role from traits — units with tank traits go frontline, units
# with carry-flagged traits go backline.
def _build_champion_pool():
    from game_data import CHAMPIONS
    tank_traits  = {"Bastion", "Brawler", "Vanguard"}
    carry_traits = {"Sniper", "Fateweaver", "Rogue", "Conduit", "Replicator"}
    pool = []
    for name, data in CHAMPIONS.items():
        traits = set(data.get("traits", []))
        if traits & tank_traits:
            role = "tank"
        elif traits & carry_traits:
            role = "carry"
        else:
            role = "support"
        pool.append((name, data["cost"], role))
    return pool

CHAMPION_POOL = _build_champion_pool()

# Real set-17 augment names (present in the synced TFT Academy augment tier
# list) so demo-mode augment rounds exercise the live ratings database.
AUGMENTS = [
    ("Carve a Path", "Silver", "combat"),
    ("Best Friends I", "Silver", "combat"),
    ("Boxing Lessons", "Silver", "combat"),
    ("Band of Thieves", "Silver", "items"),
    ("Component Grab Bag", "Silver", "items"),
    ("Bonk!", "Silver", "combat"),
    ("Cosmic Restart", "Gold", "econ"),
    ("A Magic Roll", "Gold", "econ"),
    ("Aura Farming", "Gold", "combat"),
    ("Pandora's Items", "Gold", "items"),
    ("Birthday Present", "Prismatic", "combat"),
    ("Buried Treasures", "Prismatic", "items"),
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
        # Seven simulated opponents for the lobby standings strip.
        self.opponent_hp = [100] * 7

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

        # Opponents fight each other too — bleed them at varied rates so
        # the standings strip shows a realistic spread and eliminations.
        stage_num = float(self.stage.replace("-", "."))
        self.opponent_hp = [
            max(0, o - random.randint(0, int(stage_num * 3)))
            if o > 0 else 0
            for o in self.opponent_hp
        ]

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
            lobby_hp=sorted([self.hp] + self.opponent_hp, reverse=True),
            # A shop echoing units we hold — exercises the coach's buy calls.
            shop_units=[
                self.bench[0]["name"] if self.bench else None,
                self.board[0]["name"] if self.board else None,
                random.choice(CHAMPION_POOL)[0],
                None,
                None,
            ],
            overall_confidence=DetectionConfidence.HIGH,
        )


# ── Server ────────────────────────────────────────────────────────────────────

class DemoServer:
    """WebSocket server running simulated TFT games in a loop."""

    # Default ms between simulation ticks. Adjustable via `set_tick_speed`.
    DEFAULT_TICK_MS = 500
    MIN_TICK_MS = 50
    MAX_TICK_MS = 5000

    def __init__(self):
        self.clients: Set[WebSocketServerProtocol] = set()
        self.coach = Coach()
        self.is_running = False
        self._game: Optional[SimulatedGame] = None
        self._scenario_index = 0
        # Comp the player locked via the UI (None = follow suggestions).
        self._pinned_comp: Optional[str] = None
        self._tick = 0
        self._paused = False
        self._tick_ms = self.DEFAULT_TICK_MS
        self._step_once = False  # one-shot: advance a single tick while paused

    async def start(self):
        logger.info(f"Demo server starting on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
        self.is_running = True
        # Kick off a background TFT Academy refresh — this checks the live
        # tier list and updates META_COMPS if the patch has changed. Safe to
        # call on every startup; refresh_async is internally debounced.
        # include_details pulls per-comp units/items so the comp matcher has
        # canonical, current-patch data to compare against the player's board.
        tftacademy_live.schedule_background_refresh(
            initial_delay_seconds=2.0,
            include_details=True,
        )
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

    @staticmethod
    def _build_game_data_payload() -> str:
        """Item recipes + component metadata for the frontend."""
        from config import PROTOCOL_VERSION
        return json.dumps({
            "type": "game_data",
            "protocol": PROTOCOL_VERSION,
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

    def _build_demo_info_payload(self) -> str:
        """Demo-mode metadata: scenarios + current sim controls."""
        return json.dumps({
            "type": "demo_info",
            "scenarios": [
                {"index": i, "name": s["name"], "desc": s["desc"]}
                for i, s in enumerate(SCENARIOS)
            ],
            "current_scenario": self._scenario_index % len(SCENARIOS),
            "paused": self._paused,
            "tick_ms": self._tick_ms,
            "tick_bounds": [self.MIN_TICK_MS, self.MAX_TICK_MS],
        })

    async def _handle_client(self, websocket: WebSocketServerProtocol):
        self.clients.add(websocket)
        logger.info(f"Frontend connected. Clients: {len(self.clients)}")
        # New connection — re-check TFT Academy. Debounced internally, so
        # rapid reconnects won't hammer the upstream site.
        tftacademy_live.schedule_background_refresh(initial_delay_seconds=0.0)
        try:
            # Push static game data and demo-mode metadata immediately so
            # the frontend can render craftable items + dev controls without
            # waiting for the first state broadcast.
            await websocket.send(self._build_game_data_payload())
            await websocket.send(self._build_demo_info_payload())

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
        except json.JSONDecodeError:
            return

        if t == "ping":
            await websocket.send(json.dumps({"type": "pong"}))
            return

        if t == "request_game_data":
            await websocket.send(self._build_game_data_payload())
            return

        if t == "request_demo_info":
            await websocket.send(self._build_demo_info_payload())
            return

        if t == "restart_game":
            idx = msg.get("scenario")
            if idx is not None and 0 <= idx < len(SCENARIOS):
                self._scenario_index = idx
                self._game = SimulatedGame(SCENARIOS[idx])
            else:
                self._game = SimulatedGame()
            logger.info(f"Game restarted: {self._game.scenario['name']}")
            await self._broadcast_demo_info()
            return

        if t == "pin_comp":
            self._pinned_comp = (msg.get("name") or "").strip() or None
            logger.info(f"Comp pinned: {self._pinned_comp or '(unpinned)'}")
            return

        if t == "pause":
            # Allow explicit `paused` field, otherwise toggle
            if "paused" in msg and isinstance(msg["paused"], bool):
                self._paused = msg["paused"]
            else:
                self._paused = not self._paused
            logger.info(f"Demo {'paused' if self._paused else 'resumed'}")
            await self._broadcast_demo_info()
            return

        if t == "step":
            self._step_once = True
            return

        if t == "next_round":
            if self._game:
                self._game.round_tick = self._game.ticks_per_round - 1
            return

        if t == "set_tick_speed":
            try:
                ms = int(msg.get("tick_ms", self.DEFAULT_TICK_MS))
            except (TypeError, ValueError):
                return
            self._tick_ms = max(self.MIN_TICK_MS, min(self.MAX_TICK_MS, ms))
            logger.info(f"Tick speed: {self._tick_ms}ms")
            await self._broadcast_demo_info()
            return

        if not self._game:
            return  # remaining commands need an active game

        if t == "override_components":
            self._game.components = msg.get("components", [])
            return

        if t == "override_stage":
            target = msg.get("stage", "")
            for i, (s, _) in enumerate(ROUND_SEQUENCE):
                if s == target:
                    self._game.round_index = i
                    self._game.round_tick = 0
                    break
            return

        if t == "set_hp":
            try:
                hp = int(msg.get("hp", self._game.hp))
            except (TypeError, ValueError):
                return
            self._game.hp = max(0, min(100, hp))
            return

        if t == "set_gold":
            try:
                gold = int(msg.get("gold", self._game.gold))
            except (TypeError, ValueError):
                return
            self._game.gold = max(0, min(999, gold))
            return

        if t == "set_level":
            try:
                level = int(msg.get("level", self._game.level))
            except (TypeError, ValueError):
                return
            self._game.level = max(1, min(10, level))
            return

        if t == "force_phase":
            phase = msg.get("phase", "")
            # Map a UI-friendly phase onto round_tick / round_type so the
            # next _build_state picks it up. We override round_type by
            # bumping round_index to one of known type.
            phase_map = {
                "planning": ("pvp", 0),
                "combat":   ("pvp", 3),
                "augment_select": ("augment", 0),
                "carousel": ("carousel", 0),
            }
            target = phase_map.get(phase)
            if target is None:
                return
            rtype, tick = target
            for i, (_, rt) in enumerate(ROUND_SEQUENCE):
                if rt == rtype and i >= self._game.round_index:
                    self._game.round_index = i
                    self._game.round_tick = tick
                    if rtype == "augment":
                        # Generate fresh augment choices so the panel populates
                        self._game._process_augment()
                    break

    def _analyze(self, state: GameState) -> None:
        """Stamp the pinned comp and run the coach (advice set in place)."""
        state.pinned_comp = self._pinned_comp
        state.advice = self.coach.analyze(state)

    async def _broadcast_demo_info(self):
        """Push current sim-control state to every connected client."""
        if not self.clients:
            return
        payload = self._build_demo_info_payload()
        dead = set()
        # Snapshot — clients can connect/disconnect (mutating the set) while
        # we're suspended in await client.send().
        for client in tuple(self.clients):
            try:
                await client.send(payload)
            except websockets.exceptions.ConnectionClosed:
                dead.add(client)
        self.clients -= dead

    async def _simulation_loop(self):
        while self.is_running:
            scenario = SCENARIOS[self._scenario_index % len(SCENARIOS)]
            self._game = SimulatedGame(scenario)

            logger.info(f"{'=' * 50}")
            logger.info(f"Starting game: {scenario['name']}")
            logger.info(f"{'=' * 50}")

            # Push fresh demo info now that we have a new scenario active
            await self._broadcast_demo_info()

            while self.is_running and not self._game.is_over:
                if self._paused and not self._step_once:
                    # Still emit a state every ~0.5s while paused so the UI
                    # reflects any overrides (set_hp, override_components, ...)
                    state = self._game._build_state()
                    self._analyze(state)
                    await self._broadcast(state)
                    await asyncio.sleep(0.5)
                    continue

                self._step_once = False
                self._tick += 1
                state = self._game.tick()
                self._analyze(state)
                await self._broadcast(state)
                await asyncio.sleep(self._tick_ms / 1000.0)

            if self._game and self._game.is_over:
                logger.info(f"Game ended — placement #{self._game.placement}")
                for _ in range(6):
                    state = self._game._build_state()
                    self._analyze(state)
                    await self._broadcast(state)
                    await asyncio.sleep(self._tick_ms / 1000.0)
                logger.info("Next game in 3 seconds...")
                await asyncio.sleep(3.0)
                self._scenario_index += 1

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
        # Snapshot — clients can connect/disconnect (mutating the set) while
        # we're suspended in await client.send().
        for client in tuple(self.clients):
            try:
                await client.send(payload)
            except websockets.exceptions.ConnectionClosed:
                dead.add(client)
        self.clients -= dead
