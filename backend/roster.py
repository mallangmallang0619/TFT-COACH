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
        self._prev_gold: Optional[int] = None
        self._reset_pending = False

    def reset(self) -> None:
        self._copies.clear()
        self._prev_shop = None
        self._prev_stage = None
        self._prev_gold = None
        self._reset_pending = False

    def update(self, state: GameState) -> list[str]:
        """
        Diff this frame's shop against the previous one.

        Returns the champions purchased in this frame (shop slot order) so
        callers can pair them with newly-occupied bench slots — that pairing
        is the auto-labeling source for unit-classifier training data.
        """
        stage = state.stage if state.stage and state.stage != "?" else None
        if stage:
            # A single OCR misread ("4-5" seen as "1-5") must not wipe the
            # roster — require the stage regression on two consecutive
            # frames before treating it as a new game.
            if self._is_new_game(stage):
                if self._reset_pending:
                    logger.info("Roster reset — new game detected")
                    self.reset()
                else:
                    self._reset_pending = True
            else:
                self._reset_pending = False

        purchases: list[str] = []
        shop = list(state.shop_units or [])
        gold = state.gold if state.gold is not None and state.gold >= 0 else None

        # A shop with no readable card is an obscured shop (carousel,
        # transitions, overlays) — diffing against it would count every
        # previous card as "purchased". Skip the frame and keep the old
        # baseline; when the shop reappears with new cards, the ≥2-replaced
        # guard treats it as a refresh.
        if len(shop) == 5 and any(shop):
            if self._prev_shop is not None:
                purchases = self._diff_shop(self._prev_shop, shop)
                if purchases and not self._gold_supports_purchase(gold):
                    logger.debug(
                        f"Ignoring vanished cards {purchases} — gold did not drop"
                    )
                    purchases = []
                for name in purchases:
                    self._copies[name] += 1
                    logger.info(
                        f"Purchase detected: {name} (copies: {self._copies[name]})"
                    )
            self._prev_shop = shop

        # While a reset is pending, keep the old stage baseline — updating
        # it to the regressed value would make the confirming second frame
        # look like normal progression.
        if stage and not self._reset_pending:
            self._prev_stage = stage
        if gold is not None:
            self._prev_gold = gold
        return purchases

    def _gold_supports_purchase(self, gold: Optional[int]) -> bool:
        """Purchases cost gold — if we can read both frames' gold and it
        didn't drop, the vanished cards weren't bought (misread/occlusion)."""
        if gold is None or self._prev_gold is None:
            return True   # can't verify — don't block real purchases
        return gold < self._prev_gold

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

    def _diff_shop(
        self, prev: list[Optional[str]], cur: list[Optional[str]]
    ) -> list[str]:
        """Returns the cards that look purchased; caller applies them."""
        vanished = [a for a, b in zip(prev, cur) if a and b is None]
        replaced = sum(1 for a, b in zip(prev, cur) if a and b and a != b)

        # Two or more cards swapped for different ones = reroll or round
        # rollover — the whole shop changed, nothing was necessarily bought.
        if replaced >= 2:
            return []

        # Three or more cards gone at once within a single capture interval
        # is almost certainly the shop being obscured mid-read, not a
        # triple-buy — don't poison the roster (or the training labels).
        if len(vanished) >= 3:
            return []

        return vanished
