"""
Coaching Logic Engine

Analyzes the detected game state and generates actionable advice:
  - Board power estimate (no positioning factor) work in progress to optimize for early/mid game power spikes and late game scaling
  - Item slam timing and synergy-aware placement advice
  - Shred / burn item priority guidance
  - Board positioning suggestions not yet finished
  - Augment selection ratings not yet finished
  - Comp direction guidance not yet implemented, will require more detailed synergy and champion data
"""

from __future__ import annotations
import logging
from typing import Optional

from game_state import (
    GameState,
    GameStateHistory,
    GamePhase,
    CoachingAdvice,
    BoardPowerBreakdown,
    SlamRecommendation,
    PositioningSuggestion,
)
from game_data import (
    ITEM_RECIPES,
    AUGMENT_RATINGS,
    CHAMPIONS,
    TRAITS,
    SHRED_ITEMS,
    BURN_ITEMS,
)
from synergy import compute_active_synergies, detect_comp_direction

logger = logging.getLogger(__name__)

# Quick name → recipe dict for O(1) lookups
_ITEM_BY_NAME: dict[str, dict] = {r["name"]: r for r in ITEM_RECIPES}

# ── Slam Urgency by Stage ─────────────────────────────────────────────────────
# 0  = hold  |  5 = consider  |  10 = slam everything

STAGE_SLAM_URGENCY: dict[str, int] = {
    "1-1": 0, "1-2": 0, "1-3": 0, "1-4": 0,
    "2-1": 1, "2-2": 2, "2-3": 2, "2-4": 3, "2-5": 3, "2-6": 3, "2-7": 3,
    "3-1": 4, "3-2": 5, "3-3": 5, "3-4": 6, "3-5": 6, "3-6": 6, "3-7": 6,
    "4-1": 7, "4-2": 8, "4-3": 8, "4-4": 9, "4-5": 9, "4-6": 9, "4-7": 9,
    "5-1": 10, "5-2": 10, "5-3": 10, "5-4": 10, "5-5": 10, "5-6": 10, "5-7": 10,
    "6-1": 10, "6-2": 10,
}

# Item tier → base power contribution per completed item on board
_ITEM_TIER_POWER = {"S": 40, "A": 30, "B": 20, "C": 10}


class Coach:
    """
    Generates coaching advice from the detected game state.
    Maintains history for trend-based recommendations.
    """

    def __init__(self):
        self.history = GameStateHistory(max_size=120)

    def analyze(self, state: GameState) -> CoachingAdvice:
        """Generate coaching advice for the current game state."""
        self.history.push(state)
        advice = CoachingAdvice()

        if state.phase == GamePhase.NOT_IN_GAME:
            return advice

        # ── Active Synergies ──────────────────────────────────────────────────
        # The detector doesn't populate synergies yet — derive them from the
        # board champions so downstream logic (board power, comp direction,
        # tips) all sees a consistent view.
        if not state.active_synergies and state.board_champions:
            state.active_synergies = compute_active_synergies(state.board_champions)

        # ── Board Power ───────────────────────────────────────────────────────
        power, breakdown = self._calculate_board_power(state)
        advice.board_power = round(power, 1)
        advice.board_power_breakdown = breakdown

        # ── Item Slam Analysis ────────────────────────────────────────────────
        self._analyze_items(state, advice)

        # ── Positioning Analysis ──────────────────────────────────────────────
        self._analyze_positioning(state, advice)

        # ── Comp Direction ────────────────────────────────────────────────────
        self._analyze_comp_direction(state, advice)

        # ── Augment Analysis ──────────────────────────────────────────────────
        if state.phase == GamePhase.AUGMENT_SELECT:
            self._analyze_augments(state, advice)

        # ── General Tips ──────────────────────────────────────────────────────
        self._generate_tips(state, advice)

        return advice

    # ── Board Power ───────────────────────────────────────────────────────────

    def _calculate_board_power(
        self, state: GameState
    ) -> tuple[float, BoardPowerBreakdown]:
        """
        Estimate board combat power without considering positioning.

        Formula (all values additive):
          champion contribution = cost × star_level² × item_multiplier
            where item_multiplier = 1 + 0.3 per completed item
          synergy bonus = power_per_breakpoint[current_tier] from TRAITS
          item bonus = _ITEM_TIER_POWER[tier] per completed item on board

        Higher = stronger board.  Typical ranges:
          Early game  (stage 2): 20–60
          Mid game    (stage 3): 80–160
          Late game   (stage 4+): 160–350+
        """
        champion_power = 0.0
        synergy_power = 0.0
        item_power = 0.0

        for champ in state.board_champions:
            champ_data = CHAMPIONS.get(champ.name)
            cost = champ_data["cost"] if champ_data else champ.cost
            base = cost * (champ.star_level ** 2)

            # Each completed item on this champion multiplies their effectiveness
            item_mult = 1.0
            for item_name in champ.items:
                item_data = _ITEM_BY_NAME.get(item_name)
                tier = item_data["tier"] if item_data else "B"
                item_power += _ITEM_TIER_POWER.get(tier, 20)
                item_mult += 0.3

            champion_power += base * item_mult

        for synergy in state.active_synergies:
            if not synergy.is_active:
                continue
            trait_data = TRAITS.get(synergy.name)
            if not trait_data:
                synergy_power += synergy.count * 2.0
                continue
            # Walk breakpoints to find the current activation tier
            bp_index = 0
            for i, bp in enumerate(trait_data["breakpoints"]):
                if synergy.count >= bp:
                    bp_index = i
            powers = trait_data["power_per_breakpoint"]
            if bp_index < len(powers):
                synergy_power += powers[bp_index]

        total = champion_power + synergy_power + item_power
        breakdown = BoardPowerBreakdown(
            champion_base=round(champion_power, 1),
            synergy_bonus=round(synergy_power, 1),
            item_bonus=round(item_power, 1),
            total=round(total, 1),
        )
        return total, breakdown

    # ── Item Analysis ─────────────────────────────────────────────────────────

    def _analyze_items(self, state: GameState, advice: CoachingAdvice):
        """
        Analyze held components and generate synergy-aware slam recommendations.

        Priority order (all else equal):
          1. Slam urgency (slam_now > consider > hold)
          2. Shred / burn items  — always valuable; move up the list
          3. Item tier (S > A > B > C)
        """
        components = state.component_ids
        urgency = STAGE_SLAM_URGENCY.get(state.stage, 5)

        # ── Urgency level & message ───────────────────────────────────────────
        if urgency <= 1:
            advice.slam_urgency_level = "low"
            advice.slam_urgency_message = (
                "Early game — hold components if possible. "
                "Only slam S-tier items or shred/burn items that fit your comp."
            )
        elif urgency <= 4:
            advice.slam_urgency_level = "medium"
            advice.slam_urgency_message = (
                "Mid game — strongly consider slamming. "
                "Holding components costs HP and streak gold. "
                "Prioritize shred and burn items even before your carry items."
            )
        elif urgency <= 7:
            advice.slam_urgency_level = "high"
            advice.slam_urgency_message = (
                "Slam NOW. Every round without completed items is lost HP. "
                "Slam shred (Ionic Spark, Last Whisper) and burn (Morellonomicon, "
                "Sunfire Cape, Redemption) first — they win fights regardless of comp."
            )
        else:
            advice.slam_urgency_level = "critical"
            advice.slam_urgency_message = (
                "CRITICAL — Slam everything immediately. "
                "Slam on synergy-active carries first; "
                "even a random tank beats holding components at this stage."
            )

        # Low-HP escalation
        if state.player_hp <= 40:
            if advice.slam_urgency_level in ("low", "medium"):
                advice.slam_urgency_level = "high"
                advice.slam_urgency_message = (
                    "Low HP — you need to stabilize NOW. Slam any shred, burn, or "
                    "carry item onto a synergy-active unit to start winning rounds."
                )
            # Even at "high" urgency level, the per-item `urgency` value may
            # be < 7, leaving B/C-tier items in the "hold" branch below. At
            # low HP, holding any item is wrong — bump the floor so every
            # craftable goes through the slam_now path.
            urgency = max(urgency, 7)

        # ── Find synergy-active board champions ───────────────────────────────
        synergy_carry_names = self._synergy_active_carries(state)
        synergy_tank_names  = self._synergy_active_tanks(state)

        # ── Generate recommendations ──────────────────────────────────────────
        for i, comp1 in enumerate(components):
            for j in range(i + 1, len(components)):
                comp2 = components[j]
                recipe_key = tuple(sorted([comp1, comp2]))

                for item in ITEM_RECIPES:
                    if tuple(sorted(item["recipe"])) != recipe_key:
                        continue

                    is_shred = item.get("shred", False)
                    is_burn  = item.get("burn", False)
                    parts: list[str] = []

                    # ── Determine slam urgency ────────────────────────────────
                    if item["slam"] or item["tier"] == "S":
                        slam_rec = "slam_now"
                        parts.append(f"{item['name']} is universally strong — always worth slamming.")

                    elif is_shred or is_burn:
                        slam_rec = "slam_now" if urgency >= 2 else "consider"
                        if is_shred:
                            parts.append(
                                f"{item['name']} shreds enemy resistances — "
                                "critical vs armor/MR-stacking frontlines and amplifies every "
                                "other damage source on your board."
                            )
                        if is_burn:
                            parts.append(
                                f"{item['name']} applies burn/Grievous Wounds — "
                                "counters healing champions and shields. "
                                "Essential in most lobbies; build it early."
                            )

                    elif item["tier"] == "A" and urgency >= 4:
                        slam_rec = "slam_now"
                        parts.append(
                            f"At stage {state.stage}, {item['name']} is worth slamming "
                            "to preserve HP — holding A-tier items loses you rounds."
                        )

                    elif item["tier"] == "A":
                        slam_rec = "consider"
                        parts.append(
                            f"{item['name']} is a solid A-tier item. "
                            "Slam it if it fits your current carry."
                        )

                    else:
                        slam_rec = "hold" if urgency < 7 else "slam_now"
                        parts.append(
                            f"{item['name']} is situational. "
                            + (
                                "Slam it anyway — holding components at this stage is wrong."
                                if urgency >= 7 else
                                "Hold if you can make something better later."
                            )
                        )

                    # ── Synergy-aware placement advice ────────────────────────
                    if item["type"] in ("carry", "utility"):
                        if synergy_carry_names:
                            parts.append(
                                f"Place on a synergy-active carry "
                                f"({', '.join(synergy_carry_names[:2])}) for maximum value — "
                                "items on synergy-active units deal significantly more damage "
                                "than the same item on a random tank."
                            )
                        else:
                            parts.append(
                                "Slam on your primary carry, not a tank — "
                                "carry items waste their stats on frontline units."
                            )

                    elif item["type"] in ("tank", "support"):
                        if synergy_tank_names:
                            parts.append(
                                f"Slam on a synergy-active frontliner "
                                f"({synergy_tank_names[0]}) rather than a random 1-cost holder. "
                                "A tank with active synergies provides more combat value per item."
                            )
                        else:
                            parts.append(
                                "Place on your tankiest frontliner to maximize its value."
                            )

                    advice.slam_recommendations.append(SlamRecommendation(
                        item_name=item["name"],
                        component_1=comp1,
                        component_2=comp2,
                        tier=item["tier"],
                        slam_urgency=slam_rec,
                        reason=" ".join(parts),
                    ))

        # ── Sort: urgency → shred/burn priority → tier ────────────────────────
        tier_order    = {"S": 0, "A": 1, "B": 2, "C": 3}
        urgency_order = {"slam_now": 0, "consider": 1, "hold": 2}

        advice.slam_recommendations.sort(key=lambda r: (
            urgency_order.get(r.slam_urgency, 3),
            0 if (_ITEM_BY_NAME.get(r.item_name, {}).get("shred") or
                  _ITEM_BY_NAME.get(r.item_name, {}).get("burn")) else 1,
            tier_order.get(r.tier, 4),
        ))

    def _synergy_active_carries(self, state: GameState) -> list[str]:
        """Board carry/DPS champions that contribute to at least one active synergy."""
        active = {s.name for s in state.active_synergies if s.is_active}
        result = []
        for champ in state.board_champions:
            data = CHAMPIONS.get(champ.name)
            if not data:
                continue
            # Carries tend to be in back rows (row >= 2)
            is_backline = champ.board_row is None or champ.board_row >= 2
            if is_backline and any(t in active for t in data.get("traits", [])):
                result.append(champ.name)
        return result

    def _synergy_active_tanks(self, state: GameState) -> list[str]:
        """Board frontline champions that contribute to at least one active synergy."""
        active = {s.name for s in state.active_synergies if s.is_active}
        result = []
        for champ in state.board_champions:
            data = CHAMPIONS.get(champ.name)
            if not data:
                continue
            is_frontline = champ.board_row is not None and champ.board_row < 2
            if is_frontline and any(t in active for t in data.get("traits", [])):
                result.append(champ.name)
        return result

    # ── Positioning Analysis ──────────────────────────────────────────────────

    def _analyze_positioning(self, state: GameState, advice: CoachingAdvice):
        """Analyze board positioning and suggest improvements."""
        if not state.board_champions:
            return

        frontline = [c for c in state.board_champions if c.board_row is not None and c.board_row < 2]
        backline  = [c for c in state.board_champions if c.board_row is not None and c.board_row >= 2]

        if len(frontline) == 0 and len(backline) > 0:
            advice.positioning_template = "Standard Frontline"
            advice.tips.append(
                "You have no units in the front rows. Move at least 2–3 tanky "
                "units forward to absorb damage for your carries."
            )

        if len(state.board_champions) >= 4:
            positions = [
                (c.board_row, c.board_col)
                for c in state.board_champions
                if c.board_row is not None and c.board_col is not None
            ]
            if self._is_overly_clumped(positions):
                advice.tips.append(
                    "Your units are clumped — spread them out to reduce AoE "
                    "damage from abilities like Morellonomicon or Sunfire Cape."
                )

        carries_in_center = [
            c for c in state.board_champions
            if c.board_row is not None and c.board_col is not None
            and c.board_row >= 2 and 2 <= c.board_col <= 4
        ]
        if carries_in_center:
            advice.tips.append(
                "Consider moving your carry to a corner position (column 0 or 6, "
                "row 3) to maximize the distance enemies need to travel to reach them."
            )

    def _is_overly_clumped(self, positions: list[tuple[int, int]]) -> bool:
        if len(positions) < 3:
            return False
        close_pairs = sum(
            1
            for i in range(len(positions))
            for j in range(i + 1, len(positions))
            if abs(positions[i][0] - positions[j][0]) <= 1
            and abs(positions[i][1] - positions[j][1]) <= 1
        )
        total_pairs = len(positions) * (len(positions) - 1) / 2
        return (close_pairs / total_pairs) > 0.7 if total_pairs > 0 else False

    # ── Comp Direction Analysis ───────────────────────────────────────────────

    def _analyze_comp_direction(self, state: GameState, advice: CoachingAdvice):
        """
        Identify which comps the current board is matching, surface them as
        suggestions, and add a top-line tip when a clear primary comp emerges.
        """
        # Skip the very early game — too few units to draw conclusions
        if len(state.board_champions) < 2:
            return

        suggestions = detect_comp_direction(
            state.active_synergies,
            state.board_champions,
            state.bench_champions,
        )
        if not suggestions:
            return

        advice.comp_suggestions = suggestions
        primary = suggestions[0]

        # Promote the primary comp's direction tip into the visible tips list
        if primary.match_score >= 0.45:
            advice.tips.append(f"Comp direction: {primary.direction_tip}")
        elif primary.match_score >= 0.25 and len(state.board_champions) >= 4:
            # Lower confidence — phrase as a flexible suggestion
            advice.tips.append(
                f"Possible comp direction ({primary.progress}): "
                f"{primary.direction_tip}"
            )

        # If a low-tier comp ranks first AND a higher-tier comp is also viable,
        # nudge the player toward the better choice on TFT Academy's list.
        better = self._find_better_meta_alternative(suggestions)
        if better:
            advice.tips.append(
                f"Heads up: {better.tftacademy_name} ({better.tftacademy_tier}-tier "
                f"on TFT Academy) is a stronger pivot than {primary.name} "
                f"({primary.tftacademy_tier or '—'}-tier) if you can hit it."
            )

    @staticmethod
    def _find_better_meta_alternative(suggestions):
        """Return a non-primary suggestion that ranks higher on TFT Academy's tier list."""
        if not suggestions:
            return None
        primary = suggestions[0]
        primary_tier = primary.tftacademy_tier
        # Only nudge when the primary is clearly suboptimal (C/X tier on TFT Academy)
        if primary_tier not in ("C", "X"):
            return None
        for s in suggestions[1:]:
            if s.tftacademy_tier in ("S", "A") and s.match_score >= primary.match_score - 0.15:
                return s
        return None

    # ── Augment Analysis ──────────────────────────────────────────────────────

    def _analyze_augments(self, state: GameState, advice: CoachingAdvice):
        """Rate detected augment options."""
        for aug in state.augment_options:
            rating_data = AUGMENT_RATINGS.get(aug.name)
            if rating_data:
                advice.augment_ratings.append({
                    "name": aug.name,
                    "tier": aug.tier,
                    "rating": rating_data["rating"],
                    "tip": rating_data["tip"],
                    "slot_index": aug.slot_index,
                })
            else:
                advice.augment_ratings.append({
                    "name": aug.name,
                    "tier": aug.tier,
                    "rating": "?",
                    "tip": (
                        f"'{aug.name}' is not in the database — "
                        "evaluate based on your current comp and items."
                    ),
                    "slot_index": aug.slot_index,
                })

    # ── General Tips ──────────────────────────────────────────────────────────

    def _generate_tips(self, state: GameState, advice: CoachingAdvice):
        """Generate situational tips based on game state and history."""

        # Low HP warning
        if state.player_hp <= 30:
            advice.tips.append(
                f"You're at {state.player_hp} HP — danger zone. "
                "Prioritize your strongest board NOW over long-term plans. "
                "Slam shred and burn items immediately to stabilize."
            )

        # Econ reminders
        if state.gold >= 50 and state.player_hp > 50:
            advice.tips.append(
                "50+ gold with healthy HP — you're earning max interest. "
                "Level or roll only when you need to; every extra gold is free income."
            )
        elif state.gold >= 50 and state.player_hp <= 50:
            advice.tips.append(
                "50+ gold but low HP. Spend down to find upgrades and stabilize "
                "before your health reaches a critical threshold."
            )

        # Loss streak
        if self.history.is_loss_streaking():
            hp_lost = abs(self.history.hp_delta(lookback=5))
            advice.tips.append(
                f"Loss streak detected — down ~{hp_lost} HP recently. "
                "Either commit to the streak for extra gold, or slam items on "
                "synergy-active units and level up to stabilize."
            )

        # Stage-specific reminders
        stage = state.stage
        if stage == "2-1":
            advice.tips.append(
                "Stage 2-1: First PvP round. Focus on econ and collecting pairs. "
                "Don't over-slam yet unless you have S-tier or shred/burn items."
            )
        elif stage == "3-2":
            advice.tips.append(
                "Stage 3-2: First augment. Pick based on your items and board "
                "direction. Econ augments are safest if you're unsure of your comp."
            )
        elif stage == "4-2":
            advice.tips.append(
                "Stage 4-2: Second augment. You should have a clear direction — "
                "pick augments that amplify your existing synergies and carries."
            )

        # Component hoarding
        if len(state.component_ids) >= 6:
            advice.tips.append(
                f"Holding {len(state.component_ids)} components — too many! "
                "Slam immediately. Prioritize shred (Ionic Spark, Last Whisper, "
                "Frozen Heart) and burn (Morellonomicon, Sunfire Cape, Redemption) "
                "on synergy-active champions first."
            )

        # Shred / burn gap detection
        self._check_shred_burn_gap(state, advice)

    def _check_shred_burn_gap(self, state: GameState, advice: CoachingAdvice):
        """Warn if the board is missing shred or burn items."""
        if len(state.board_champions) < 4:
            return  # Too early to flag — board isn't formed yet

        board_items = [item for c in state.board_champions for item in c.items]
        has_shred = any(item in SHRED_ITEMS for item in board_items)
        has_burn  = any(item in BURN_ITEMS  for item in board_items)

        if not has_shred:
            advice.tips.append(
                "No shred items on your board (Ionic Spark, Last Whisper, "
                "Frozen Heart, Giant Slayer, Statikk Shiv). "
                "Shred cuts enemy Armor/MR and dramatically increases your "
                "whole board's effective damage — build one when possible."
            )

        if not has_burn:
            advice.tips.append(
                "No burn items on your board (Morellonomicon, Sunfire Cape, "
                "Redemption). Burn applies Grievous Wounds and counters "
                "healing champions and shields — essential in most lobbies. "
                "Morellonomicon (Rod + Belt) on a mage carry is particularly effective."
            )
