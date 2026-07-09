"""
Purchase-Tracking Roster

Board and bench units render as 3D models the portrait templates can't
identify — but the SHOP is flat art with clean name text the detector
reads reliably (detector._detect_shop). Watching the shop between frames
reveals purchases: a card that disappears while the rest of the shop stays
put was bought. Accumulated purchases are the player's roster (board +
bench combined, with star-ups from 3-copy combines), which feeds comp
direction as held units.

Known blind spots, acceptable for coaching purposes:
  - Sells aren't observable (the roster can overcount after a pivot;
    it resets every game).
  - Units gained off-shop (carousel, Support-A-Friend style drops) are
    missed.
  - A buy immediately followed by a reroll inside one capture interval
    looks like a full shop change and is skipped.
"""

from __future__ import annotations

import logging
from collections import Counter
from typing import Optional

from game_state import DetectedChampion, GameState

logger = logging.getLogger(__name__)


class RosterTracker:
    """Stateful shop-diff tracker. Feed it every detected GameState."""

    def __init__(self):
        self._copies: Counter[str] = Counter()   # 1-star-equivalent copies
        self._prev_shop: Optional[list[Optional[str]]] = None
        self._prev_stage: Optional[str] = None

    def reset(self) -> None:
        self._copies.clear()
        self._prev_shop = None
        self._prev_stage = None

    def update(self, state: GameState) -> None:
        """Diff this frame's shop against the previous one."""
        stage = state.stage if state.stage and state.stage != "?" else None
        if stage and self._is_new_game(stage):
            logger.info("Roster reset — new game detected")
            self.reset()

        shop = list(state.shop_units or [])
        if len(shop) == 5:
            if self._prev_shop is not None:
                self._diff_shop(self._prev_shop, shop)
            self._prev_shop = shop
        if stage:
            self._prev_stage = stage

    def owned_units(self) -> list[DetectedChampion]:
        """Current roster as bench-style champions (no board position)."""
        units: list[DetectedChampion] = []
        for name, n in sorted(self._copies.items()):
            threes, rem = divmod(n, 9)
            twos, ones = divmod(rem, 3)
            for star, count in ((3, threes), (2, twos), (1, ones)):
                units.extend(
                    DetectedChampion(name=name, star_level=star, confidence=0.9)
                    for _ in range(count)
                )
        return units

    @property
    def total_purchases(self) -> int:
        return sum(self._copies.values())

    # ── Internals ─────────────────────────────────────────────────────────────

    def _is_new_game(self, stage: str) -> bool:
        """The stage number going backwards means a new game started."""
        if not self._prev_stage:
            return False
        try:
            return int(stage.split("-")[0]) < int(self._prev_stage.split("-")[0])
        except (ValueError, IndexError):
            return False

    def _diff_shop(self, prev: list[Optional[str]], cur: list[Optional[str]]) -> None:
        vanished = [a for a, b in zip(prev, cur) if a and b is None]
        replaced = sum(1 for a, b in zip(prev, cur) if a and b and a != b)

        # Two or more cards swapped for different ones = reroll or round
        # rollover — the whole shop changed, nothing was necessarily bought.
        if replaced >= 2:
            return

        for name in vanished:
            self._copies[name] += 1
            logger.info(f"Purchase detected: {name} (copies: {self._copies[name]})")
