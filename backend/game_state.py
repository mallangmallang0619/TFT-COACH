"""
Game State Data Model

Defines the complete game state as detected by the CV pipeline.
This is the single source of truth passed from backend → frontend
via WebSocket as JSON.
"""

from __future__ import annotations
from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional
import time


class GamePhase(str, Enum):
    """Current phase of the game."""
    LOADING = "loading"
    CAROUSEL = "carousel"
    PVE = "pve"
    PLANNING = "planning"
    COMBAT = "combat"
    AUGMENT_SELECT = "augment_select"
    GAME_OVER = "game_over"
    NOT_IN_GAME = "not_in_game"


class DetectionConfidence(str, Enum):
    """How confident we are in a detection result."""
    HIGH = "high"       # > 90% match
    MEDIUM = "medium"   # 80-90% match
    LOW = "low"         # 70-80% match
    GUESS = "guess"     # < 70% — likely wrong


# ── Core Data Structures ──────────────────────────────────────────────────────

class DetectedComponent(BaseModel):
    """A single item component detected on the bench or on a champion."""
    component_id: str                          # e.g., "bf_sword"
    confidence: float = 0.0                    # 0.0 - 1.0
    screen_x: int = 0                          # Pixel position (for debug overlay)
    screen_y: int = 0


class DetectedChampion(BaseModel):
    """A champion detected on the board or bench."""
    name: str                                  # e.g., "Jinx"
    star_level: int = 1                        # 1, 2, or 3
    cost: int = 1                              # 1-5 gold cost tier
    items: list[str] = Field(default_factory=list)  # Completed item names
    board_row: Optional[int] = None            # Row on board (0-3), None if on bench
    board_col: Optional[int] = None            # Column on board (0-6)
    confidence: float = 0.0


class DetectedAugment(BaseModel):
    """An augment option shown during augment selection."""
    name: str
    tier: str = "Silver"                       # Silver / Gold / Prismatic
    slot_index: int = 0                        # 0, 1, or 2 (left, center, right)
    confidence: float = 0.0


class ActiveSynergy(BaseModel):
    """A trait/synergy currently active on the board."""
    name: str                                  # e.g., "Gunner"
    count: int = 0                             # Number of units contributing
    breakpoint: int = 0                        # Next activation threshold
    is_active: bool = False


# ── Coaching Output ───────────────────────────────────────────────────────────

class SlamRecommendation(BaseModel):
    """A specific item slam recommendation."""
    item_name: str
    component_1: str
    component_2: str
    tier: str                                  # S / A / B / C
    slam_urgency: str                          # "slam_now" / "consider" / "hold"
    reason: str                                # Human-readable explanation
    # Set when the item is in the build of the comp the player is going:
    for_unit: Optional[str] = None             # unit that builds it
    for_comp: Optional[str] = None             # comp label


class PositioningSuggestion(BaseModel):
    """A positioning change recommendation."""
    champion_name: str
    from_row: Optional[int] = None
    from_col: Optional[int] = None
    to_row: int
    to_col: int
    reason: str


class BoardPowerBreakdown(BaseModel):
    """0-100 board-strength score with explainable source contributions."""
    champion_base: float = 0.0
    meta_bonus: float = 0.0
    synergy_bonus: float = 0.0
    composition_bonus: float = 0.0
    item_bonus: float = 0.0
    augment_bonus: float = 0.0
    total: float = 0.0
    label: str = "Unknown"
    source: str = "none"
    confidence: float = 0.0
    meta_patch: Optional[str] = None
    meta_rank: Optional[str] = None
    meta_games_analyzed: int = 0
    meta_updated_at: int = 0
    meta_synced_at: Optional[str] = None
    item_data_known: bool = False
    strongest_meta_unit: Optional[str] = None
    weakest_meta_unit: Optional[str] = None


class CompSuggestion(BaseModel):
    """
    A comp the player appears to be building — or could pivot into —
    based on their currently fielded champions and active synergies.
    """
    name: str                                  # e.g., "5 Meeple Reroll"
    match_score: float = 0.0                   # 0.0 - 1.0, how well the board matches this comp
    is_primary: bool = False                   # True for the top-ranked comp this round
    progress: str = ""                         # e.g., "3 / 5 Meeple, 2 / 4 Stargazer"
    held_units: list[str] = Field(default_factory=list)   # Comp units already on board
    missing_units: list[str] = Field(default_factory=list) # Comp units still to find
    next_breakpoint: Optional[int] = None      # Units needed for next trait tier
    next_breakpoint_trait: Optional[str] = None
    power_at_next_breakpoint: float = 0.0      # Estimated synergy power gained
    direction_tip: str = ""                    # Human-readable advice

    # ── External tier list (TFT Academy) ────────────────────────────────
    # Populated when this suggestion can be matched to an entry in META_COMPS.
    # `tftacademy_name` may differ from `name` (TFT Academy uses carry-centric
    # labels like "Yi Marawlers"; our internal names are trait-centric).
    tftacademy_name: Optional[str] = None
    tftacademy_tier: Optional[str] = None      # S / A / B / C / X
    tftacademy_trend: Optional[str] = None     # rising / falling / new / ""

    # ── Scraped comp detail (present for META_COMPS-backed suggestions) ──
    # board_layout: TFT Academy's recommended final board, one entry per
    # unit: {"name", "board_index" (0-27; row = idx // 7, row 0 = front),
    # "stars", "items": [item names]}.
    board_layout: list[dict] = Field(default_factory=list)
    # Augments TFT Academy recommends for this comp (display names).
    recommended_augments: list[str] = Field(default_factory=list)
    # Human-readable notes on why the score got context boosts (items/augments).
    context_notes: list[str] = Field(default_factory=list)
    # True when the player clicked this comp to lock it as their direction.
    is_pinned: bool = False


class CoachingAdvice(BaseModel):
    """Complete coaching output for the current game state."""
    # Board power estimate (no positioning factor)
    board_power: float = 0.0
    board_power_breakdown: BoardPowerBreakdown = Field(default_factory=BoardPowerBreakdown)

    # Item advice
    slam_urgency_level: str = "low"            # low / medium / high / critical
    slam_urgency_message: str = ""
    slam_recommendations: list[SlamRecommendation] = Field(default_factory=list)

    # Positioning advice
    positioning_suggestions: list[PositioningSuggestion] = Field(default_factory=list)
    positioning_template: Optional[str] = None  # Recommended template name

    # Augment advice (only populated during augment selection)
    augment_ratings: list[dict] = Field(default_factory=list)

    # Comp direction (populated from board champions + active synergies)
    comp_suggestions: list[CompSuggestion] = Field(default_factory=list)

    # Shop buy calls: cards in the current shop worth buying, strongest
    # first. Each: {"name", "slot", "reason", "priority" (1 = strongest)}.
    shop_actions: list[dict] = Field(default_factory=list)

    # General tips
    tips: list[str] = Field(default_factory=list)


# ── Full Game State ───────────────────────────────────────────────────────────

class GameState(BaseModel):
    """
    Complete snapshot of the game state at a single moment.
    This is serialized to JSON and sent to the frontend every capture cycle.
    """
    # Metadata
    timestamp: float = Field(default_factory=time.time)
    frame_number: int = 0
    detection_ms: float = 0.0                  # How long detection took

    # Game phase
    phase: GamePhase = GamePhase.NOT_IN_GAME
    phase_confidence: float = 0.0

    # Core stats
    stage: str = "1-1"
    stage_confidence: float = 0.0
    player_hp: int = 100
    gold: int = 0
    level: int = 1
    xp_current: int = 0
    xp_needed: int = 2

    # Board state
    board_champions: list[DetectedChampion] = Field(default_factory=list)
    bench_champions: list[DetectedChampion] = Field(default_factory=list)

    # Items
    held_components: list[DetectedComponent] = Field(default_factory=list)
    component_ids: list[str] = Field(default_factory=list)  # Simplified list for coach

    # Synergies
    active_synergies: list[ActiveSynergy] = Field(default_factory=list)

    # Augments (only during selection)
    augment_options: list[DetectedAugment] = Field(default_factory=list)
    selected_augments: list[str] = Field(default_factory=list)  # Already chosen augments

    # Completed items sitting on the item bench (craftables, artifacts,
    # radiants, emblems — anything that isn't a basic component), top to
    # bottom. Display names.
    held_items: list[str] = Field(default_factory=list)

    # All eight HP slots from the right-side list, in standings order
    # (non-increasing; 0 = eliminated, -1 = unreadable). Includes our HP.
    lobby_hp: list[int] = Field(default_factory=list)

    # The five shop card names (None = empty/unreadable slot). Read via
    # name-banner OCR; feeds the purchase-tracking roster.
    shop_units: list[Optional[str]] = Field(default_factory=list)

    # The comp the player clicked to lock as their direction (matched
    # against suggestion names / TFT Academy names). Set by the server
    # from the frontend's pin_comp message.
    pinned_comp: Optional[str] = None

    # Coaching (populated by coach.py)
    advice: Optional[CoachingAdvice] = None

    # Detection quality
    overall_confidence: DetectionConfidence = DetectionConfidence.LOW

    def to_frontend_json(self) -> dict:
        """
        Serialize to a dict optimized for the frontend.
        Strips internal fields and flattens where useful.
        """
        data = self.model_dump()
        # Remove raw pixel coordinates the frontend doesn't need
        for comp in data.get("held_components", []):
            comp.pop("screen_x", None)
            comp.pop("screen_y", None)
        return data


class GameStateHistory:
    """
    Maintains a rolling window of game states for trend detection.
    Useful for detecting streaks, HP loss rate, econ trajectory, etc.
    """

    def __init__(self, max_size: int = 60):
        self.states: list[GameState] = []
        self.max_size = max_size

    def push(self, state: GameState):
        self.states.append(state)
        if len(self.states) > self.max_size:
            self.states.pop(0)

    @property
    def latest(self) -> Optional[GameState]:
        return self.states[-1] if self.states else None

    def hp_delta(self, lookback: int = 10) -> int:
        """How much HP has changed in the last N states."""
        if len(self.states) < 2:
            return 0
        start = max(0, len(self.states) - lookback)
        return self.states[-1].player_hp - self.states[start].player_hp

    def is_loss_streaking(self, lookback: int = 5) -> bool:
        """Detect if player is on a loss streak (HP dropping consistently)."""
        if len(self.states) < lookback:
            return False
        recent = self.states[-lookback:]
        drops = sum(1 for i in range(1, len(recent)) if recent[i].player_hp < recent[i-1].player_hp)
        return drops >= lookback - 1

    def stage_changed(self) -> bool:
        """Did the stage change between the last two captures?"""
        if len(self.states) < 2:
            return False
        return self.states[-1].stage != self.states[-2].stage

    def phase_changed(self) -> bool:
        """Did the game phase change?"""
        if len(self.states) < 2:
            return False
        return self.states[-1].phase != self.states[-2].phase
