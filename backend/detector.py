"""
Computer Vision Detection Pipeline

Processes captured frames to extract game state:
  - Template matching for components, champions, UI elements
  - OCR for stage, HP, gold, augment names
  - Phase detection from UI layout analysis
"""

from __future__ import annotations
import logging
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

# Tesseract parallelizes each tiny OCR call across all cores via OpenMP,
# which burns CPU for zero benefit on our postage-stamp crops — and we
# spawn several calls per frame. Cap it before pytesseract ever runs.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

try:
    import cv2
    import numpy as np
except ImportError as _e:
    raise ImportError(
        f"Missing dependency: {_e}. "
        f"Install with: pip install opencv-python numpy --break-system-packages"
    ) from _e

try:
    import pytesseract

    # On Windows the installer puts tesseract.exe in Program Files without
    # adding it to PATH for already-running shells; point pytesseract at the
    # standard location if the plain command isn't resolvable.
    if sys.platform == "win32" and not shutil.which("tesseract"):
        _tess_exe = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
        if _tess_exe.exists():
            pytesseract.pytesseract.tesseract_cmd = str(_tess_exe)
except ImportError:
    pytesseract = None

from config import (
    TEMPLATE_DIR,
    COMPONENT_TEMPLATE_DIR,
    CHAMPION_TEMPLATE_DIR,
    ITEM_TEMPLATE_DIR,
    TRAIT_TEMPLATE_DIR,
    CONFIDENCE_THRESHOLD,
    COMPONENT_MATCH_THRESHOLD,
    CHAMPION_MATCH_THRESHOLD,
    TRAIT_MATCH_THRESHOLD,
    OCR_CONFIDENCE_MIN,
    BOARD_HEX_GRID,
    COMPONENT_IDS,
    LOG_DETECTION_FRAMES,
    LOG_FRAME_DIR,
    GameROIs,
    ShopGeometry,
    TraitPanel,
)
from game_data import find_champion_name, find_augment_rating
from unit_classifier import UnitClassifier
from game_state import (
    GameState,
    GamePhase,
    DetectedComponent,
    DetectedChampion,
    DetectedAugment,
    DetectionConfidence,
)

logger = logging.getLogger(__name__)


# ── Champion matching tuning ──────────────────────────────────────────────────
# Champions are matched on small, grayscale, blurred, circularly-masked patches.
# Working at a fixed canonical size makes matching scale-stable and cheap; the
# search window is larger than the template so we can slide for position
# tolerance, and we try a few template scales to absorb portrait-size jitter.
CANON_TEMPLATE = 60          # canonical champion patch edge (px)
CANON_SEARCH = 80            # search-window edge the patch slides within (px)
MATCH_SCALES = (0.85, 1.0, 1.15)
_MASK_CACHE: dict[int, np.ndarray] = {}

# Trait symbols are tiny tier-tinted glyphs in the left panel. Matching them needs
# multi-scale sliding (the glyph fills a varying fraction of its hexagon) and
# polarity tolerance (bronze tiers are dark-on-light, gold tiers light-on-dark),
# under a circular mask to ignore the hexagon frame. Validated 6/6 on a real frame.
TRAIT_SEARCH = 52
TRAIT_SIZES = (26, 30, 34, 38)


def _longest_nonincreasing(vals: list[int]) -> list[int]:
    """Longest non-increasing subsequence — the standings list is sorted
    by HP, so reads breaking monotonicity are OCR junk to discard."""
    n = len(vals)
    if n <= 1:
        return list(vals)
    dp, prev = [1] * n, [-1] * n
    for i in range(n):
        for j in range(i):
            if vals[j] >= vals[i] and dp[j] + 1 > dp[i]:
                dp[i], prev[i] = dp[j] + 1, j
    k = max(range(n), key=lambda i: dp[i])
    out: list[int] = []
    while k != -1:
        out.append(vals[k])
        k = prev[k]
    return out[::-1]


def _circular_mask(size: int) -> np.ndarray:
    """A filled white circle on black, cached per size — masks out hex corners."""
    mask = _MASK_CACHE.get(size)
    if mask is None:
        mask = np.zeros((size, size), dtype=np.uint8)
        cv2.circle(mask, (size // 2, size // 2), size // 2 - 1, 255, -1)
        _MASK_CACHE[size] = mask
    return mask


def _prep_gray(img: np.ndarray, size: int) -> np.ndarray:
    """Grayscale → resize to `size`² → light blur. The common front-end for both
    templates and crops so they're compared in the same robust feature space."""
    if img.ndim == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    img = cv2.resize(img, (size, size), interpolation=cv2.INTER_AREA)
    return cv2.GaussianBlur(img, (3, 3), 0)


def _prep_trait_gray(img: np.ndarray, size: int) -> np.ndarray:
    """Like _prep_gray but composites a transparent trait icon onto black first
    (CDragon trait icons are white glyphs on alpha)."""
    if img.ndim == 3 and img.shape[2] == 4:
        alpha = img[:, :, 3:4] / 255.0
        img = (img[:, :, :3] * alpha).astype(np.uint8)
    return _prep_gray(img, size)


class TemplateStore:
    """
    Loads and caches template images for matching.

    Templates are organized by category:
      assets/templates/components/bf_sword.png
      assets/templates/champions/jinx.png
      assets/templates/ui/augment_frame.png
    """

    def __init__(self):
        self.component_templates: dict[str, np.ndarray] = {}
        self.item_templates: dict[str, np.ndarray] = {}
        self.champion_templates: dict[str, np.ndarray] = {}
        # Per-scale canonical grayscale champion patches, keyed by name then
        # pixel size — precomputed so matching doesn't re-grayscale/resize per hex.
        self.champion_gray: dict[str, dict[int, np.ndarray]] = {}
        # Per-scale grayscale trait glyphs, same idea (built from RGBA icons).
        self.trait_gray: dict[str, dict[int, np.ndarray]] = {}
        self.ui_templates: dict[str, np.ndarray] = {}
        self._loaded = False

    def load(self):
        """Load all template images from disk."""
        self.component_templates = self._load_dir(COMPONENT_TEMPLATE_DIR)
        self.item_templates = self._load_dir(ITEM_TEMPLATE_DIR)
        self.champion_templates = self._load_dir(CHAMPION_TEMPLATE_DIR)
        self.ui_templates = self._load_dir(TEMPLATE_DIR / "ui")
        self._build_champion_gray()
        self._build_trait_gray()
        self._loaded = True

    def _build_trait_gray(self):
        """Load trait icons (RGBA) and precompute per-scale grayscale glyphs."""
        self.trait_gray = {}
        if not TRAIT_TEMPLATE_DIR.exists():
            return
        for img_path in TRAIT_TEMPLATE_DIR.glob("*.png"):
            img = cv2.imread(str(img_path), cv2.IMREAD_UNCHANGED)
            if img is None:
                continue
            self.trait_gray[img_path.stem] = {
                sz: _prep_trait_gray(img, sz) for sz in TRAIT_SIZES
            }

    def _build_champion_gray(self):
        """Precompute each champion's canonical grayscale patch at every match
        scale, so the hot detection loop just slides cached arrays."""
        self.champion_gray = {}
        sizes = sorted({int(CANON_TEMPLATE * s) for s in MATCH_SCALES})
        for name, bgr in self.champion_templates.items():
            self.champion_gray[name] = {sz: _prep_gray(bgr, sz) for sz in sizes}

        total = (
            len(self.component_templates)
            + len(self.champion_templates)
            + len(self.ui_templates)
        )
        logger.info(
            f"Loaded {total} templates: "
            f"{len(self.component_templates)} components, "
            f"{len(self.champion_templates)} champions, "
            f"{len(self.ui_templates)} UI elements"
        )

    def _load_dir(self, dir_path: Path) -> dict[str, np.ndarray]:
        """Load all .png images from a directory."""
        templates = {}
        if not dir_path.exists():
            logger.warning(f"Template directory not found: {dir_path}")
            return templates

        for img_path in dir_path.glob("*.png"):
            img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
            if img is not None:
                templates[img_path.stem] = img
            else:
                logger.warning(f"Failed to load template: {img_path}")

        return templates

    @property
    def is_loaded(self) -> bool:
        return self._loaded


class Detector:
    """
    Main detection pipeline. Takes a captured frame and extracts
    the complete game state using template matching and OCR.
    """

    # Trait counts only change when the board changes — re-OCR them at most
    # every N frames while the detected trait names stay the same. Row
    # (symbol) matching is also cached, at a shorter interval since it is
    # the change detector.
    TRAIT_COUNT_REFRESH_FRAMES = 6
    TRAIT_ROWS_REFRESH_FRAMES = 3

    def __init__(self, templates: Optional[TemplateStore] = None):
        self.templates = templates or TemplateStore()
        self.rois = GameROIs()
        self._frame_count = 0

        # Live frames render units as 3D models the portrait templates can't
        # identify — hex matching there costs ~2.3s/frame and yields only
        # false positives, so the live server turns it off. Synthetic sim
        # frames use real portraits and keep it on.
        self.match_board_units = True

        # CNN unit classifier for live 3D models — a no-op until a trained
        # model exists in assets/models/ (see scripts/train_classifier.py).
        self.unit_classifier = UnitClassifier()

        # Lobby HP standings — refreshed every N frames (they only change
        # after combats) and served from cache in between.
        self._lobby_cache: list[int] = []
        self._lobby_age = 10**6

        # Held completed-item scan cache (change-gated — see
        # _detect_held_items).
        self._held_items_thumb: Optional[np.ndarray] = None
        self._held_items_age = 10**6
        self._held_items_cache: list[str] = []

        # (trait names tuple, {trait: count}) + age, for count caching.
        self._trait_cache: Optional[tuple[tuple, dict]] = None
        self._trait_cache_age = 0
        # Cached trait-panel rows (symbol matching ≈0.7s/frame).
        self._trait_rows_cache: Optional[list[tuple[str, float, float]]] = None
        self._trait_rows_age = 0

        # Last accepted HP — anchors the next read. Late game the player
        # list shrinks and shifts as players die, so "tallest glyphs" alone
        # drifts; the candidate closest to the previous value is ours.
        self._last_hp: Optional[int] = None

        if not self.templates.is_loaded:
            self.templates.load()

    def detect(self, frame: np.ndarray) -> GameState:
        """
        Run the full detection pipeline on a captured frame.
        Returns a GameState with all detected information.
        """
        t_start = time.time()
        self._frame_count += 1

        state = GameState(frame_number=self._frame_count)

        # 1. Detect game phase first — it determines which other detections to run
        state.phase, state.phase_confidence = self._detect_phase(frame)

        if state.phase == GamePhase.NOT_IN_GAME:
            self._last_hp = None   # new game → drop the HP anchor
            state.detection_ms = (time.time() - t_start) * 1000
            return state

        # 2. Core stats (always detect these during a game)
        state.stage, state.stage_confidence = self._ocr_stage(frame)
        state.player_hp = self._ocr_player_hp(frame)

        # Lobby standings (all players' HP, sorted by standing) — context
        # for the coach. A full read costs ~0.7-1.1s, but standings shift
        # only after combats, so a cached read every ~15 frames is plenty.
        self._lobby_age += 1
        if self._lobby_age >= 15:
            lobby = self._read_lobby_hp(frame)
            if lobby:
                self._lobby_cache, self._lobby_age = lobby, 0
        state.lobby_hp = self._lobby_cache
        state.gold = self._ocr_number(frame, self.rois.gold, "Gold")
        state.level = self._ocr_number(frame, self.rois.level, "Level")

        # 3. Item components on bench, plus completed/artifact/radiant
        # items the game hands out that aren't components at all.
        state.held_components = self._detect_components(frame)
        state.component_ids = [c.component_id for c in state.held_components]
        state.held_items = self._detect_held_items(frame)

        # 4. Board champions (only during planning/combat)
        if state.phase in (GamePhase.PLANNING, GamePhase.COMBAT):
            if self.match_board_units:
                state.board_champions = self._detect_board_champions(frame)
                state.bench_champions = self._detect_bench_champions(frame)
            elif self.unit_classifier.available:
                # Live mode with a trained model: identify the 3D unit
                # models directly (one batched ONNX pass for board+bench).
                state.board_champions, state.bench_champions = (
                    self._detect_units_cnn(frame)
                )
            # Live frames render units as 3D models the portrait templates
            # can't identify — hex matching produces misses and false
            # positives. The HUD trait panel is 2D and matches reliably, so
            # whenever it reads anything, it is the synergy source of truth
            # (synthetic sim frames have no panel and fall back to the
            # board-derived synergies in the coach).
            panel_synergies = self._synergies_from_trait_panel(frame)
            if panel_synergies:
                state.active_synergies = panel_synergies

            # Shop card names — feeds the purchase-tracking roster, which
            # is the reliable source of "what units does the player own"
            # while board/bench unit ID isn't viable on live frames.
            state.shop_units = self._detect_shop(frame)

        # 5. Augment options (only during augment selection)
        if state.phase == GamePhase.AUGMENT_SELECT:
            state.augment_options = self._detect_augments(frame)

        # 6. Overall detection confidence
        state.overall_confidence = self._assess_confidence(state)
        state.detection_ms = (time.time() - t_start) * 1000

        # Debug: save annotated frame
        if LOG_DETECTION_FRAMES and self._frame_count % 30 == 0:
            self._save_debug_frame(frame, state)

        return state

    # ── Phase Detection ───────────────────────────────────────────────────────

    def _detect_phase(self, frame: np.ndarray) -> tuple[GamePhase, float]:
        """
        Determine the current game phase by analyzing UI layout.

        Strategy:
        - Check for augment selection overlay (large centered panel)
        - Check for carousel (distinct visual pattern)
        - Check for shop visibility (planning vs combat)
        - Check for game-over screen
        """
        h, w = frame.shape[:2]

        # Check for augment selection — look for the darkened overlay
        augment_roi = self.rois.augment_panel.to_pixels(w, h)
        augment_region = frame[
            augment_roi[1]:augment_roi[1]+augment_roi[3],
            augment_roi[0]:augment_roi[0]+augment_roi[2]
        ]

        if self._is_augment_screen(augment_region):
            return GamePhase.AUGMENT_SELECT, 0.85

        # Check if we're in a game at all — look for the stage indicator
        stage_roi = self.rois.stage.to_pixels(w, h)
        stage_region = frame[
            stage_roi[1]:stage_roi[1]+stage_roi[3],
            stage_roi[0]:stage_roi[0]+stage_roi[2]
        ]

        if self._is_blank_or_loading(stage_region):
            return GamePhase.NOT_IN_GAME, 0.70

        # Default to planning phase (safest assumption during a game)
        return GamePhase.PLANNING, 0.60

    def _is_augment_screen(self, region: np.ndarray) -> bool:
        """Detect the augment selection overlay.

        The overlay dims the whole screen dark but shows three brightly-lit augment
        cards in the center. The old "dark + some edges" test fired on any dark,
        noisy/textured board; we additionally require a meaningful patch of bright,
        card-like pixels, which a dimmed board never has.
        """
        if region.size == 0:
            return False
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        mean_brightness = float(np.mean(gray))
        bright_frac = float(np.mean(gray > 150))  # the augment cards are bright
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.count_nonzero(edges) / edges.size
        # Dark dimmed background + bright structured cards.
        return mean_brightness < 90 and bright_frac > 0.04 and edge_density > 0.02

    def _is_blank_or_loading(self, region: np.ndarray) -> bool:
        """Check if a region is mostly blank (not in game)."""
        if region.size == 0:
            return True
        return np.std(region) < 15  # Very low variance = blank/solid color

    # ── OCR Detection ─────────────────────────────────────────────────────────

    def _ocr_stage(self, frame: np.ndarray) -> tuple[str, float]:
        """
        OCR the stage indicator (e.g., '3-2').

        The text's x position shifts with the top bar's round-icon count
        (stage 1-2 bars have fewer icons, pushing it right), so the ROI is
        a wide band and the value is regex-extracted. The glyphs are small
        — 2x upscale before thresholding is what makes them readable.
        """
        if pytesseract is None:
            return "?", 0.0
        h, w = frame.shape[:2]
        x, y, rw, rh = self.rois.stage.to_pixels(w, h)
        region = frame[y:y+rh, x:x+rw]
        if region.size == 0:
            return "?", 0.0

        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary) > 128:
            binary = cv2.bitwise_not(binary)
        try:
            text = pytesseract.image_to_string(
                binary, config="--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789-"
            ).strip()
        except Exception:
            return "?", 0.0

        match = re.search(r"([1-7])-([1-7])", text)
        if match:
            return f"{match.group(1)}-{match.group(2)}", 0.85
        # OCR sometimes drops the dash ("1-4" reads "14") — accept exactly
        # two plausible stage digits.
        digits = re.sub(r"\D", "", text)
        if len(digits) == 2 and "1" <= digits[0] <= "7" and "1" <= digits[1] <= "7":
            return f"{digits[0]}-{digits[1]}", 0.6

        return "?", 0.0

    def _ocr_number(
        self,
        frame: np.ndarray,
        roi: "RegionOfInterest",
        label: str = "",
    ) -> int:
        """OCR a numeric value from a specific ROI.

        Returns -1 when nothing readable was found — distinct from a real
        "0" on screen, so callers can hold the last good value across
        frames where the region is obscured (combat effects, transitions).
        """
        h, w = frame.shape[:2]
        x, y, rw, rh = roi.to_pixels(w, h)
        region = frame[y:y+rh, x:x+rw]

        text = self._ocr_region(region, whitelist="0123456789")

        try:
            value = int(text.strip())
            return value
        except ValueError:
            logger.debug(f"OCR failed for {label}: got '{text}'")
            return -1

    # The player list's HP-number column at the right edge. Deliberately
    # narrow — it excludes summoner names and background scenery while
    # still containing our enlarged row's digits (which protrude left).
    # Raw frame ratios (like the trait panel) — at 16:9 the adaptive
    # viewport is the whole frame.
    _PLAYER_LIST_STRIP = (0.915, 0.08, 0.978, 0.82)   # x1, y1, x2, y2

    def _ocr_player_hp(self, frame: np.ndarray) -> int:
        """
        Read OUR hp from the right-side player list.

        The list reorders by standing every round, so a fixed-position crop
        reads whichever player happens to sit at that height. Our own row is
        rendered enlarged (bigger portrait, bigger digits), so instead OCR
        the whole list strip and take the number drawn with the tallest
        glyphs; ties go to the leftmost box since our row also protrudes
        left. Falls back to the fixed ROI if the strip read fails.
        """
        if pytesseract is None:
            return 0
        h, w = frame.shape[:2]
        x1r, y1r, x2r, y2r = self._PLAYER_LIST_STRIP
        strip = frame[int(y1r * h):int(y2r * h), int(x1r * w):int(x2r * w)]
        if strip.size == 0:
            return self._ocr_number(frame, self.rois.player_hp, "HP")

        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

        # Geometric pass first — the most reliable AND the cheapest: find
        # the enlarged row by the height of its white digit-stroke band and
        # OCR just that band (a few tiny crops, vs. two whole-strip passes).
        # It also recovers rows the strip passes miss outright: big bold
        # single digits, glyphs rendered hollow by the global thresholds.
        found = self._find_enlarged_hp_row(gray, strip)
        if found is not None:
            self._last_hp = found[0]
            return found[0]

        # Two binarizations, candidates merged: global Otsu handles typical
        # frames; adaptive rescues our enlarged row when it protrudes onto
        # bright arena scenery that pulls the global threshold too high.
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(otsu) > 128:
            otsu = cv2.bitwise_not(otsu)
        adaptive = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 41, 12,
        )

        # Tesseract often reports conf=0 for the large-font row we actually
        # want, so confidence can't be used as a gate. Instead: HP digits
        # live in the left ~72% of the strip (the right side is the portrait
        # column, whose circular frames OCR as tall junk digits); among the
        # remaining boxes the tallest glyphs are our enlarged row.
        candidates: list[tuple[int, int, int]] = []   # (height, -left, value)
        for binary in (otsu, adaptive):
            try:
                data = pytesseract.image_to_data(
                    binary,
                    config="--psm 11 --oem 3 -c tessedit_char_whitelist=0123456789",
                    output_type=pytesseract.Output.DICT,
                )
            except Exception as e:
                logger.debug(f"player-list OCR failed: {e}")
                continue
            strip_w = binary.shape[1]
            for i, raw in enumerate(data.get("text") or []):
                txt = (raw or "").strip()
                if not txt.isdigit():
                    continue
                L, T = data["left"][i], data["top"][i]
                W, H = data["width"][i], data["height"][i]
                if L > strip_w * 0.72:
                    continue
                # HP digits also END before the portrait column — boxes
                # reaching into it are portrait rings / item icons that
                # happen to start left enough (seen live: an icon smear
                # read as "44" with the tallest box in the strip, beating
                # the real value).
                if L + W > strip_w * 0.80:
                    continue
                # ...and a bounded size: the enlarged row's digits measure
                # at most ~5.6% of the strip height on real frames; bigger
                # boxes are scenery artifacts.
                if H > 0.065 * binary.shape[0]:
                    continue
                # Digit glyphs have a stable shape: width ≈ 0.68-0.79 of
                # height per character (measured across real frames). UI
                # edges and combat effects OCR as boxes far outside that
                # band — vertical lines read as skinny-tall "1"s, smears
                # as wide blobs.
                aspect = W / max(1, H * len(txt))
                if 0.45 <= aspect <= 0.90:
                    value = int(txt)
                    if 1 <= value <= 100:
                        candidates.append((H, -L, value))
                elif aspect > 0.90 and 1.2 * H <= W <= 3.2 * H:
                    # A clearly-wider-than-tall box that read as too few
                    # digits usually means tesseract merged the enlarged
                    # row's big bold glyphs into one ("17" read as "7").
                    # Re-reading just the box reliably separates them.
                    value = self._reread_hp_box(gray, L, T, W, H)
                    if value is not None:
                        candidates.append((H, -L, value))

        if candidates:
            # With an anchor from the previous frame, the candidate closest
            # to it is our row — HP moves in small steps, other players'
            # totals differ. Without one (game start), the tallest glyphs
            # are our enlarged row.
            pick = None
            if self._last_hp is not None:
                near = [c for c in candidates if abs(c[2] - self._last_hp) <= 25]
                if near:
                    pick = min(near, key=lambda c: (abs(c[2] - self._last_hp), -c[0]))
            if pick is None:
                pick = max(candidates)
            self._last_hp = pick[2]
            return pick[2]
        return self._ocr_number(frame, self.rois.player_hp, "HP")

    @staticmethod
    def _find_enlarged_hp_row(gray2x: np.ndarray, strip_bgr: np.ndarray) -> Optional[tuple[int, int]]:
        """
        Locate OUR row in the player list geometrically and read its HP.

        Our row renders enlarged, so its white digit glyphs form a taller
        vertical run of white pixels than any other row. White = all
        channels bright AND near-gray (colored arena art fails the gray
        test); solid spell-glow rows saturate the zone and are excluded;
        surviving candidate bands are validated by OCR itself — glow edges
        read as nothing, the digit row reads as a number.

        Returns (hp value, run height in 2x pixels) or None.
        """
        mask, x0, x1, all_runs = Detector._hp_strip_runs(gray2x, strip_bgr)
        # Regular rows' glyph runs measure ~22-30px here; the enlarged row
        # ~40-90. Anything bigger is scenery that survived the masks.
        runs = [r for r in all_runs if 34 <= r[0] <= 110]

        for height, ys, ye in sorted(runs, reverse=True)[:3]:
            pad = 8
            # Extend past the zone edge when the digits reach it — a
            # 3-digit "100" at game start pokes past and read as "10".
            x_ext = int(gray2x.shape[1] * 0.80)
            band = gray2x[max(0, ys - pad):ye + pad, x0:x_ext]
            cols = np.where(mask[ys:ye + 1].sum(axis=0) > 0)[0]
            b0, b1 = 0, band.shape[1]
            if cols.size:
                b0 = max(0, cols[0] - pad)
                b1 = (band.shape[1] if cols[-1] >= (x1 - x0) - 4
                      else min(band.shape[1], cols[-1] + 1 + pad))
            value = Detector._read_hp_band(band, b0, b1, height)
            if value is not None and value >= 1:
                return value, height
        return None

    @staticmethod
    def _read_hp_digits(band: np.ndarray) -> Optional[int]:
        """Local-Otsu OCR of a digit band; None when nothing plausible."""
        if band.size == 0:
            return None
        _, local = cv2.threshold(band, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(local) > 128:
            local = cv2.bitwise_not(local)
        for psm in (8, 7):
            try:
                txt = pytesseract.image_to_string(
                    local,
                    config=f"--psm {psm} --oem 3 -c tessedit_char_whitelist=0123456789",
                ).strip()
            except Exception:
                return None
            if txt.isdigit() and 0 <= int(txt) <= 100:
                return int(txt)
        return None

    @staticmethod
    def _read_hp_band(band: np.ndarray, b0: int, b1: int, glyph_h: int) -> Optional[int]:
        """
        Read the HP number from a row band. The white mask can miss the
        LEADING digit when it sits over bright frame ornaments ("97"
        masking down to "7"), so the crop starts 1.8 glyph-heights left of
        the masked cluster and the value is taken from tesseract's WORD
        BOXES: the rightmost digit-word whose box height matches the glyph
        height. Digits right-align; ornament fragments read at the wrong
        size or position and are ignored.
        """
        # Margin on BOTH sides: a crop ending right at the glyphs makes
        # tesseract merge them into one read ("97" as a single "7" box).
        ext0 = max(0, b0 - int(1.8 * glyph_h))
        ext1 = min(band.shape[1], b1 + glyph_h)
        crop = band[:, ext0:ext1]
        if crop.size == 0:
            return None
        _, local = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(local) > 128:
            local = cv2.bitwise_not(local)
        try:
            data = pytesseract.image_to_data(
                local,
                config="--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789",
                output_type=pytesseract.Output.DICT,
            )
        except Exception:
            return None
        best = None   # ((digit_count, box_height, right_edge), value)
        for i, raw in enumerate(data.get("text") or []):
            txt = (raw or "").strip()
            if not (txt.isdigit() and 0 <= int(txt) <= 100):
                continue
            bh = data["height"][i]
            if not (0.45 * glyph_h <= bh <= 1.35 * glyph_h):
                continue
            # Most digits, then tallest, then rightmost: portrait art at
            # the band's right edge can OCR as a lone digit, and it must
            # not outrank the actual multi-digit HP number.
            key = (len(txt), bh, data["left"][i] + data["width"][i])
            if best is None or key > best[0]:
                best = (key, int(txt))
        if best is not None:
            return best[1]
        # Word segmentation can fail on single big digits — fall back to a
        # plain read of the tightly-masked crop.
        return Detector._read_hp_digits(band[:, b0:b1])

    @staticmethod
    def _hp_strip_runs(
        gray2x: np.ndarray, strip_bgr: np.ndarray
    ) -> tuple[np.ndarray, int, int, list[tuple[int, int, int]]]:
        """
        Shared front-end for the player-list readers: white digit-stroke
        mask over the HP-digit zone plus the vertical runs of texty rows.
        Returns (mask, x0, x1, runs) with runs as (height, y_start, y_end).
        """
        bgr = cv2.resize(
            strip_bgr, (gray2x.shape[1], gray2x.shape[0]), interpolation=cv2.INTER_CUBIC
        )
        sh, sw = gray2x.shape[:2]
        x0, x1 = int(sw * 0.25), int(sw * 0.72)
        zone = bgr[:, x0:x1].astype(np.int16)
        bright = zone.min(axis=2) > 185
        grayish = (zone.max(axis=2) - zone.min(axis=2)) < 45
        mask = (bright & grayish).astype(np.uint8)
        rowsum = mask.sum(axis=1)
        texty = (rowsum >= 4) & (rowsum <= (x1 - x0) * 0.35)

        runs: list[tuple[int, int, int]] = []
        y = 0
        while y < sh:
            if texty[y]:
                y2 = y
                while y2 + 1 < sh and texty[y2 + 1]:
                    y2 += 1
                runs.append((y2 - y + 1, y, y2))
                y = y2 + 1
            else:
                y += 1
        return mask, x0, x1, runs

    def _read_lobby_hp(self, frame: np.ndarray) -> list[int]:
        """
        Read EVERY player's HP from the right-side list, top to bottom.

        The list is sorted by standing, so values are non-increasing —
        after OCR'ing each row's digit band, the longest non-increasing
        subsequence keeps the consistent reads and drops junk (glow bands
        that read as a digit, a truncated read on the scouted player's
        shifted pill). Eliminated players read as 0. Partial lists are
        fine; the coach only needs the shape of the lobby.
        """
        if pytesseract is None:
            return []
        h, w = frame.shape[:2]
        x1r, y1r, x2r, y2r = self._PLAYER_LIST_STRIP
        strip = frame[int(y1r * h):int(y2r * h), int(x1r * w):int(x2r * w)]
        if strip.size == 0:
            return []
        gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)

        mask, x0, x1, runs = self._hp_strip_runs(gray, strip)
        values: list[int] = []
        for height, ys, ye in runs:
            if not (12 <= height <= 110):
                continue
            pad = 8
            # The OCR band extends past the run-detection zone (x1 = 0.72)
            # toward the portraits (~0.80): three-digit values ("100") poke
            # past the zone edge and were reading as "10" with the trailing
            # digit amputated — game start showed the whole lobby at 10.
            x_ext = int(gray.shape[1] * 0.80)
            gband = gray[max(0, ys - pad):ye + pad, x0:x_ext]
            mrows = mask[max(0, ys - pad):ye + pad, :]
            mband = np.zeros(gband.shape[:2], dtype=np.uint8)
            mband[:mrows.shape[0], :mrows.shape[1]] = mrows
            cols = np.where(mask[ys:ye + 1].sum(axis=0) > 0)[0]
            b0, b1 = 0, gband.shape[1]
            if cols.size:
                if height >= 34:
                    # Enlarged (our) row: digits dominate the band; extend
                    # past the zone edge when they reach it.
                    b0 = max(0, cols[0] - pad)
                    b1 = (gband.shape[1] if cols[-1] >= (x1 - x0) - 4
                          else min(gband.shape[1], cols[-1] + 1 + pad))
                else:
                    # Regular rows: digits are the RIGHTMOST white cluster
                    # (names sit left of a clear gap); keep through to the
                    # zone edge so an under-masked digit isn't amputated.
                    gaps = np.where(np.diff(cols) > 25)[0]
                    b0 = max(0, (cols[gaps[-1] + 1] if gaps.size else cols[0]) - pad)
                    b1 = gband.shape[1]
            value = self._read_hp_band(gband, b0, b1, height)
            if value is None and height >= 34:
                # Mask-image fallback for the enlarged row's hollow glyphs
                # only — on regular rows it hallucinated digits out of the
                # white "fought recently" sword markers (read as 7s).
                value = self._read_hp_digits(mband[:, b0:b1] * 255)
            if value is not None:
                values.append(value)
        return _longest_nonincreasing(values)

    @staticmethod
    def _reread_hp_box(gray: np.ndarray, L: int, T: int, W: int, H: int) -> Optional[int]:
        """
        Re-OCR a single suspected-merged digit box from the player list.

        Works from the GRAYSCALE strip with a local Otsu threshold: the
        whole-strip binarizations render our row's big bold digits as
        hollow outlines (unreadable), while thresholding just the HP pill
        separates digits from background cleanly. Accepts only a
        multi-digit read whose per-character aspect lands back in the
        digit band — that combination is what a genuinely merged read
        looks like, while portrait rings and smears fail it.
        """
        pad = max(2, H // 4)
        crop = gray[max(0, T - pad):T + H + pad, max(0, L - pad):L + W + pad]
        if crop.size == 0:
            return None
        _, local = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(local) > 128:
            local = cv2.bitwise_not(local)
        for psm in (8, 7):   # single word first — most reliable on the pill
            try:
                txt = pytesseract.image_to_string(
                    local,
                    config=f"--psm {psm} --oem 3 -c tessedit_char_whitelist=0123456789",
                ).strip()
            except Exception:
                return None
            if not (txt.isdigit() and 2 <= len(txt) <= 3):
                continue
            if not (0.40 <= W / max(1, H * len(txt)) <= 0.95):
                continue
            value = int(txt)
            if 1 <= value <= 100:
                return value
        return None

    def _ocr_region(self, region: np.ndarray, whitelist: str = "") -> str:
        """
        Run Tesseract OCR on an image region.
        Pre-processes the image for better accuracy.
        """
        if pytesseract is None:
            logger.warning("pytesseract not installed — OCR disabled")
            return ""

        if region.size == 0:
            return ""

        # Pre-processing pipeline for OCR accuracy
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)

        # Upscale small regions for better OCR
        if gray.shape[0] < 40:
            scale = 40 / gray.shape[0]
            gray = cv2.resize(
                gray, None, fx=scale, fy=scale,
                interpolation=cv2.INTER_CUBIC
            )

        # Threshold to black & white
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        # Invert if text is light on dark background
        if np.mean(binary) > 128:
            binary = cv2.bitwise_not(binary)

        # Build Tesseract config
        config = "--psm 7 --oem 3"  # Single line mode
        if whitelist:
            config += f" -c tessedit_char_whitelist={whitelist}"

        try:
            text = pytesseract.image_to_string(binary, config=config)
            return text.strip()
        except Exception as e:
            logger.debug(f"OCR error: {e}")
            return ""

    def _detect_shop(self, frame: np.ndarray) -> list[Optional[str]]:
        """
        Read the five shop card names.

        Card art is 3D-ish splash art, but the name banner at each card's
        bottom is clean white text. One tesseract pass over the whole
        banner band (each call spawns a process — five separate calls cost
        ~0.5s), then words are assigned to card slots by x position and
        resolved against the champion roster (fuzzy, like augment names).
        Empty or unreadable slots come back as None.
        """
        if pytesseract is None:
            return [None] * 5
        h, w = frame.shape[:2]
        g = ShopGeometry()
        x0 = int(g.cards_x0 * w)
        band = frame[int(g.name_y0 * h):int(g.name_y1 * h),
                     x0:int((g.cards_x0 + 5 * g.card_pitch) * w)]
        if band.size == 0:
            return [None] * 5

        scale = 2
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(binary) > 128:
            binary = cv2.bitwise_not(binary)

        try:
            data = pytesseract.image_to_data(
                binary,
                config="--psm 11 --oem 3",
                output_type=pytesseract.Output.DICT,
            )
        except Exception as e:
            logger.debug(f"shop OCR failed: {e}")
            return [None] * 5

        pitch_px = g.card_pitch * w * scale
        slot_words: list[list[tuple[int, str]]] = [[] for _ in range(5)]
        for i, raw in enumerate(data.get("text") or []):
            txt = (raw or "").strip()
            # Names are alphabetic (plus ' and .) — drops the cost digits.
            if not txt or not any(c.isalpha() for c in txt):
                continue
            slot = int(data["left"][i] // pitch_px)
            if 0 <= slot < 5:
                slot_words[slot].append((data["left"][i], txt))

        return [
            find_champion_name(" ".join(t for _, t in sorted(words)))
            for words in slot_words
        ]

    # ── Component Detection ───────────────────────────────────────────────────

    def _detect_components(self, frame: np.ndarray) -> list[DetectedComponent]:
        """
        Detect item components on the item bench using template matching.
        """
        if not self.templates.component_templates:
            return []

        h, w = frame.shape[:2]
        x, y, rw, rh = self.rois.item_bench.to_pixels(w, h)
        bench_region = frame[y:y+rh, x:x+rw]

        if bench_region.size == 0:
            return []

        detected = []

        # Inventory icons measure ≈0.017 of the frame width on live 1440p
        # captures; the CDN templates are a fixed 64px, so resize each
        # template to a few sizes around that before matching.
        scales = sorted({max(12, int(w * s)) for s in (0.0135, 0.0165, 0.0195)})

        for comp_id, template in self.templates.component_templates.items():
            for size in scales:
                scaled = cv2.resize(template, (size, size), interpolation=cv2.INTER_AREA)
                matches = self._multi_template_match(
                    bench_region, scaled, COMPONENT_MATCH_THRESHOLD
                )
                for mx, my, conf in matches:
                    detected.append(DetectedComponent(
                        component_id=comp_id,
                        confidence=conf,
                        screen_x=x + mx,
                        screen_y=y + my,
                    ))

        # De-duplicate close matches (within 10px of each other)
        detected = self._deduplicate_detections(detected, min_distance=10)

        logger.debug(f"Detected {len(detected)} components: {[d.component_id for d in detected]}")
        return detected

    # How often (in frames) the held-item scan may rerun, and how much the
    # column thumbnail must change to trigger one.
    _HELD_ITEMS_MIN_AGE = 5
    _HELD_ITEMS_CHANGE = 4.0

    def _detect_held_items(self, frame: np.ndarray) -> list[str]:
        """
        Detect COMPLETED items (craftables, artifacts, radiants, emblems)
        sitting on the item bench — the column also holds non-component
        items the game hands out, which the component matcher can't see
        and users read as "detection is broken".

        Matching a few hundred item templates is too slow per frame, so
        the scan is change-gated: a grayscale thumbnail of the column is
        compared each frame, and the full match only reruns when the
        column's contents actually changed.
        """
        if not self.templates.item_templates:
            return []
        h, w = frame.shape[:2]
        x, y, rw, rh = self.rois.item_bench.to_pixels(w, h)
        region = frame[y:y+rh, x:x+rw]
        if region.size == 0:
            return []

        thumb = cv2.resize(
            cv2.cvtColor(region, cv2.COLOR_BGR2GRAY), (16, 96),
            interpolation=cv2.INTER_AREA,
        )
        self._held_items_age += 1
        if self._held_items_thumb is not None:
            drift = float(np.mean(cv2.absdiff(thumb, self._held_items_thumb)))
            if drift < self._HELD_ITEMS_CHANGE:
                return self._held_items_cache          # column unchanged
            if self._held_items_age < self._HELD_ITEMS_MIN_AGE:
                return self._held_items_cache          # debounce drag churn

        scales = sorted({max(12, int(w * s)) for s in (0.0135, 0.0165, 0.0195)})
        found: list[tuple[float, str, float]] = []   # (y, name, conf)
        for name, template in self.templates.item_templates.items():
            best = None
            for size in scales:
                scaled = cv2.resize(template, (size, size), interpolation=cv2.INTER_AREA)
                for mx, my, conf in self._multi_template_match(
                    region, scaled, COMPONENT_MATCH_THRESHOLD
                ):
                    if best is None or conf > best[2]:
                        best = (my, name, conf)
            if best:
                found.append(best)

        # One item per slot: group matches that landed within half a slot
        # height of each other and keep each group's most confident.
        found.sort()
        names: list[str] = []
        slot_h = rh / 10
        i = 0
        while i < len(found):
            j = i + 1
            while j < len(found) and found[j][0] - found[i][0] < slot_h * 0.5:
                j += 1
            names.append(max(found[i:j], key=lambda g: g[2])[1])
            i = j

        self._held_items_thumb = thumb
        self._held_items_age = 0
        self._held_items_cache = names
        if names:
            logger.debug(f"Held items: {names}")
        return names

    # ── Champion Detection ────────────────────────────────────────────────────

    def _match_champion(self, search_bgr: np.ndarray) -> tuple[str, float]:
        """Best (name, confidence) for a champion in a search crop.

        The crop is reduced to a canonical grayscale, blurred search window; each
        champion's cached patch is slid across it (position tolerance) at several
        scales (size tolerance) under a circular mask (ignores hex-corner
        background). Returns ("Unknown", 0.0) if nothing clears the threshold.
        """
        if search_bgr.size == 0:
            return "Unknown", 0.0
        search = _prep_gray(search_bgr, CANON_SEARCH)

        best_name, best_conf = "Unknown", 0.0
        for name, by_size in self.templates.champion_gray.items():
            for size, patch in by_size.items():
                if size > CANON_SEARCH:
                    continue
                result = cv2.matchTemplate(
                    search, patch, cv2.TM_CCOEFF_NORMED, mask=_circular_mask(size)
                )
                # Masked CCOEFF_NORMED can yield nan/inf on flat windows.
                np.nan_to_num(result, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
                max_val = float(result.max())
                if max_val > best_conf:
                    best_conf, best_name = max_val, name

        if best_conf > CHAMPION_MATCH_THRESHOLD:
            return best_name, best_conf
        return "Unknown", best_conf

    # ── Trait Detection ───────────────────────────────────────────────────────

    def _match_trait(self, search_bgr: np.ndarray) -> tuple[str, float]:
        """Best (trait_name, confidence) for a trait symbol crop.

        Each cached glyph is slid across the search window at several scales and
        in both polarities (templates are light-on-dark; bronze-tier in-game
        glyphs are dark-on-light), under a circular mask. Returns ("", 0.0) below
        threshold.
        """
        if search_bgr.size == 0 or not self.templates.trait_gray:
            return "", 0.0
        search = _prep_gray(search_bgr, TRAIT_SEARCH)
        search_inv = cv2.bitwise_not(search)

        best_name, best_conf = "", 0.0
        for name, by_size in self.templates.trait_gray.items():
            for size, glyph in by_size.items():
                mask = _circular_mask(size)
                for src in (search, search_inv):
                    result = cv2.matchTemplate(src, glyph, cv2.TM_CCOEFF_NORMED, mask=mask)
                    np.nan_to_num(result, copy=False, nan=0.0, posinf=0.0, neginf=0.0)
                    v = float(result.max())
                    if v > best_conf:
                        best_conf, best_name = v, name

        if best_conf >= TRAIT_MATCH_THRESHOLD:
            return best_name, best_conf
        return "", best_conf

    def _detect_trait_rows(self, frame: np.ndarray) -> list[tuple[str, float, float]]:
        """Scan the trait panel and return matched (trait, confidence, row_cy).

        Walks down the symbol column at the configured row pitch; rows whose
        symbol clears the threshold are reported in panel order. Duplicate names
        (a glyph matching two adjacent slots) are de-duplicated, keeping the best.
        row_cy is the row's vertical center as a frame-height ratio, so callers
        can read the count text sitting next to the symbol.
        """
        h, w = frame.shape[:2]
        p = TraitPanel()
        hw = p.symbol_w / 2
        hh = p.symbol_h / 2

        best_by_name: dict[str, tuple[float, float]] = {}   # name → (conf, cy)
        order: list[str] = []
        for i in range(p.max_rows):
            cy = p.first_row_cy + i * p.row_pitch
            if cy + hh >= 1.0:
                break
            x1, x2 = int((p.symbol_cx - hw) * w), int((p.symbol_cx + hw) * w)
            y1, y2 = int((cy - hh) * h), int((cy + hh) * h)
            crop = frame[max(0, y1):y2, max(0, x1):x2]
            name, conf = self._match_trait(crop)
            if not name:
                continue
            if name not in best_by_name:
                order.append(name)
            if conf > best_by_name.get(name, (0.0, 0.0))[0]:
                best_by_name[name] = (conf, cy)

        return [(n, best_by_name[n][0], best_by_name[n][1]) for n in order]

    def _detect_traits(self, frame: np.ndarray) -> list[tuple[str, float]]:
        """Matched trait-panel entries as (trait, confidence)."""
        return [(n, conf) for n, conf, _ in self._detect_trait_rows(frame)]

    def _synergies_from_trait_panel(self, frame: np.ndarray) -> list:
        """
        Build ActiveSynergy entries by reading the HUD trait panel.

        This is the synergy source for live frames: board units render as 3D
        models the portrait templates can't identify, but the panel's 2D trait
        glyphs match reliably. The unit count is OCR'd from the number printed
        right of each symbol; rows whose count can't be read fall back to the
        trait's first breakpoint so the synergy still registers as active.
        """
        from synergy import synergies_from_counts
        from game_data import TRAITS

        h, w = frame.shape[:2]
        p = TraitPanel()

        # Symbol matching is expensive; reuse the last row scan for a few
        # frames (traits change on board edits, which take seconds anyway).
        if (
            self._trait_rows_cache is not None
            and self._trait_rows_age < self.TRAIT_ROWS_REFRESH_FRAMES
        ):
            self._trait_rows_age += 1
            rows = self._trait_rows_cache
        else:
            rows = self._detect_trait_rows(frame)
            self._trait_rows_cache = rows
            self._trait_rows_age = 0
        row_names = tuple(name for name, _c, _y in rows)

        # Count OCR is ~9 tesseract calls; reuse cached counts while the
        # panel shows the same traits, refreshing periodically to catch
        # count-only changes (adding a second copy of a held trait).
        if (
            self._trait_cache is not None
            and self._trait_cache[0] == row_names
            and self._trait_cache_age < self.TRAIT_COUNT_REFRESH_FRAMES
        ):
            self._trait_cache_age += 1
            return synergies_from_counts(dict(self._trait_cache[1]))

        counts: dict[str, int] = {}
        for name, _conf, cy in rows:
            # Active rows show a dark badge with a bright white count digit
            # right of the symbol; inactive (greyed) rows have no badge and
            # show dim "1 / 2"-style progress under the name instead.
            x1 = int((p.symbol_cx + p.symbol_w * 0.15) * w)
            x2 = x1 + int(p.symbol_w * 0.85 * w)
            y1 = int((cy - p.symbol_h * 0.32) * h)
            y2 = int((cy + p.symbol_h * 0.32) * h)
            badge = frame[max(0, y1):y2, max(0, x1):x2]
            badge_gray = cv2.cvtColor(badge, cv2.COLOR_BGR2GRAY) if badge.size else None
            # Badge digits are pure white (~255); 215 keeps margin above
            # bright UI lines without missing real badges.
            has_badge = badge_gray is not None and float(badge_gray.max()) >= 215

            breakpoints = (TRAITS.get(name) or {}).get("breakpoints") or [1]
            if has_badge:
                # Badge digit; the breakpoint line below may leak stray
                # digits into the OCR — the first digit is the count.
                text = self._ocr_region(badge, whitelist="0123456789")
                m = re.match(r"(\d)", text.strip())
                count = int(m.group(1)) if m else breakpoints[0]
            else:
                # Greyed row: read the "count / needed" progress text that
                # sits in the lower half of the row.
                ly1 = int((cy + p.symbol_h * 0.02) * h)
                ly2 = int((cy + p.symbol_h * 0.55) * h)
                lx2 = x1 + int(p.symbol_w * 1.6 * w)
                line = frame[max(0, ly1):ly2, max(0, x1):lx2]
                text = self._ocr_region(line, whitelist="0123456789/")
                m = re.search(r"(\d)\s*/", text)
                count = int(m.group(1)) if m else max(1, breakpoints[0] - 1)
            counts[name] = count

        self._trait_cache = (row_names, dict(counts))
        self._trait_cache_age = 0
        return synergies_from_counts(counts)

    def _detect_board_champions(self, frame: np.ndarray) -> list[DetectedChampion]:
        """Detect champions on the board by sampling each hex position."""
        if not self.templates.champion_gray:
            return []

        h, w = frame.shape[:2]
        bx, by, bw, bh = self.rois.board.to_pixels(w, h)
        board_region = frame[by:by+bh, bx:bx+bw]
        if board_region.size == 0:
            return []

        detected = []
        brh, brw = board_region.shape[:2]

        for hex_pos in BOARD_HEX_GRID:
            cx = int(hex_pos.cx * brw)
            cy = int(hex_pos.cy * brh)
            r = int(hex_pos.radius * brw)

            # Core hex crop for the occupancy check, and a slightly larger search
            # window (so the matcher can slide to absorb position jitter).
            core = board_region[max(0, cy-r):cy+r, max(0, cx-r):cx+r]
            if core.size == 0 or self._is_hex_empty(core):
                continue
            sr = int(r * 1.25)
            search = board_region[max(0, cy-sr):cy+sr, max(0, cx-sr):cx+sr]

            name, conf = self._match_champion(search)
            if name != "Unknown":
                detected.append(DetectedChampion(
                    name=name,
                    board_row=hex_pos.row,
                    board_col=hex_pos.col,
                    confidence=conf,
                ))

        return detected

    def _detect_bench_champions(self, frame: np.ndarray) -> list[DetectedChampion]:
        """Detect champions on the bench row (9 horizontal slots)."""
        if not self.templates.champion_gray:
            return []

        h, w = frame.shape[:2]
        bx, by, bw, bh = self.rois.champion_bench.to_pixels(w, h)
        bench_region = frame[by:by+bh, bx:bx+bw]
        if bench_region.size == 0:
            return []

        detected = []
        brw = bench_region.shape[1]
        slot_width = brw // 9

        for slot in range(9):
            sx = slot * slot_width
            slot_crop = bench_region[:, sx:sx+slot_width]
            if slot_crop.size == 0 or self._is_hex_empty(slot_crop):
                continue

            name, conf = self._match_champion(slot_crop)
            if name != "Unknown":
                detected.append(DetectedChampion(name=name, confidence=conf))

        return detected

    def _detect_units_cnn(
        self, frame: np.ndarray
    ) -> tuple[list[DetectedChampion], list[DetectedChampion]]:
        """
        Identify live 3D unit models on board hexes and bench slots with
        the trained classifier — one batched inference pass for all 37
        positions. Empty positions fall below the confidence threshold
        (and, once an _empty class is harvested, are classified outright).
        """
        h, w = frame.shape[:2]
        crops: list[Optional[np.ndarray]] = []

        # Board hexes: a unit model stands upward from its hex, so the
        # crop is a portrait-shaped box anchored at the hex center —
        # framed like the bench training crops. Geometry is a first
        # approximation; calibrate against a live frame once a model
        # exists (diagnose_capture.py --dump-hexes).
        bx, by, bw, bh = self.rois.board.to_pixels(w, h)
        board_region = frame[by:by+bh, bx:bx+bw]
        brh, brw = board_region.shape[:2]
        for hex_pos in BOARD_HEX_GRID:
            cx = int(hex_pos.cx * brw)
            cy = int(hex_pos.cy * brh)
            r = int(hex_pos.radius * brw)
            crop = board_region[
                max(0, cy - int(2.55 * r)):min(brh, cy + r),
                max(0, cx - int(1.1 * r)):min(brw, cx + int(1.1 * r)),
            ]
            crops.append(crop)

        # Bench slots: identical cropping to the harvester, so inference
        # sees exactly what training saw.
        nx, ny, nw, nh = self.rois.champion_bench.to_pixels(w, h)
        slot_w = max(1, nw // 9)
        for slot in range(9):
            crops.append(frame[ny:ny+nh, nx + slot * slot_w: nx + (slot + 1) * slot_w])

        results = self.unit_classifier.classify_batch(crops)

        board: list[DetectedChampion] = []
        for hex_pos, (name, conf) in zip(BOARD_HEX_GRID, results):
            if name is not None:
                board.append(DetectedChampion(
                    name=name,
                    board_row=hex_pos.row,
                    board_col=hex_pos.col,
                    confidence=conf,
                ))
        bench = [
            DetectedChampion(name=name, confidence=conf)
            for name, conf in results[len(BOARD_HEX_GRID):]
            if name is not None
        ]
        return board, bench

    def _is_hex_empty(self, hex_crop: np.ndarray) -> bool:
        """Check if a hex/slot is empty (no champion placed)."""
        # Empty hexes tend to have low color variance and dark values
        hsv = cv2.cvtColor(hex_crop, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        # Champions have more color saturation than empty hexes
        return np.mean(saturation) < 30

    # ── Augment Detection ─────────────────────────────────────────────────────

    # Augment card geometry, measured on two real 2560x1440 augment
    # screens (2-1 and 3-2): the title line sits mid-card at a fixed
    # height, with the three cards centered at fixed x positions.
    _AUG_CARD_CX = (0.287, 0.500, 0.713)   # card centers (frame-width ratio)
    _AUG_NAME_Y0 = 0.484                    # title band top (frame-height ratio)
    _AUG_NAME_Y1 = 0.522                    # title band bottom

    def _detect_augments(self, frame: np.ndarray) -> list[DetectedAugment]:
        """
        Read the three augment titles during the selection screen.

        Each card's title band is OCR'd separately: the earlier single
        wide-band pass dragged inter-card art in as junk words, and one
        card's noise could poison its neighbors' word assignment. Two
        binarizations per card (the purple card gradient defeats global
        Otsu on some frames) and the more letter-rich read wins. Names
        come back raw — the coach fuzzy-resolves them against the augment
        database, which also supplies the slot tier.
        """
        if pytesseract is None:
            return []
        h, w = frame.shape[:2]
        y0, y1 = int(self._AUG_NAME_Y0 * h), int(self._AUG_NAME_Y1 * h)

        augments: list[DetectedAugment] = []
        for i, cx in enumerate(self._AUG_CARD_CX):
            band = frame[y0:y1, int((cx - 0.11) * w):int((cx + 0.11) * w)]
            if band.size == 0:
                continue
            name = self._ocr_augment_title(band)
            if len(name) >= 3:
                augments.append(DetectedAugment(
                    name=name,
                    tier="?",   # the coach fills this from the augment database
                    slot_index=i,
                    confidence=0.6,
                ))
        return augments

    @staticmethod
    def _ocr_augment_title(band: np.ndarray) -> str:
        """OCR one card's title band; returns the cleaned best read."""
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        if np.mean(otsu) > 128:
            otsu = cv2.bitwise_not(otsu)
        adaptive = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV, 41, 12,
        )
        # Titles are white glyphs on the purple card gradient — a color
        # mask (bright AND near-gray) isolates them where the grayscale
        # thresholds smear into the art. Same trick as the HP row finder.
        bgr = cv2.resize(band, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC).astype(np.int16)
        white = ((bgr.min(axis=2) > 165) & (bgr.max(axis=2) - bgr.min(axis=2) < 60))
        white_bin = (white.astype(np.uint8)) * 255

        # A read that fuzzy-resolves in the augment database beats any
        # unresolvable one regardless of length — raw letter count rewards
        # exactly the debris we're trying to avoid. White mask first so it
        # wins ties among unresolvable reads.
        best, best_score = "", (0, 0)
        for binary in (white_bin, otsu, adaptive):
            try:
                txt = pytesseract.image_to_string(
                    binary, config="--psm 7 --oem 3"
                ).strip()
            except Exception:
                continue
            # Strip OCR debris characters from tokens rather than dropping
            # whole tokens ("Preser:t" → "Presert") — the augment database
            # lookup is fuzzy and absorbs single-character damage.
            tokens = []
            for t in txt.split():
                t2 = "".join(c for c in t if c.isalpha() or c in "'’-+!")
                if t2 and any(c.isalpha() for c in t2):
                    tokens.append(t2)
            # Card art at the band's edges reads as short lowercase
            # fragments ("yi", "wf", "he") — real titles begin and end on
            # capitalized words or roman numerals.
            while tokens and tokens[0].islower() and len(tokens[0]) <= 2:
                tokens.pop(0)
            while tokens and tokens[-1].islower() and len(tokens[-1]) <= 2:
                tokens.pop()
            cand = " ".join(tokens)
            if not cand:
                continue
            matched, _ = find_augment_rating(cand)
            score = (1 if matched else 0, sum(c.isalpha() for c in cand))
            if score > best_score:
                # Return the canonical database name when it resolves —
                # the overlay then displays the real title, not the read.
                best, best_score = (matched or cand), score
        return best

    # ── Template Matching Utilities ───────────────────────────────────────────

    def _multi_template_match(
        self,
        image: np.ndarray,
        template: np.ndarray,
        threshold: float,
    ) -> list[tuple[int, int, float]]:
        """
        Find all occurrences of a template in an image above the threshold.
        Returns list of (x, y, confidence) tuples.
        """
        # Handle size mismatch
        if (template.shape[0] > image.shape[0] or
            template.shape[1] > image.shape[1]):
            # Resize template to fit within image
            scale = min(
                image.shape[0] / template.shape[0],
                image.shape[1] / template.shape[1],
            ) * 0.8
            template = cv2.resize(template, None, fx=scale, fy=scale)

        if (template.shape[0] > image.shape[0] or
            template.shape[1] > image.shape[1]):
            return []

        result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)

        matches = []
        for pt in zip(*locations[::-1]):  # x, y
            conf = result[pt[1], pt[0]]
            matches.append((int(pt[0]), int(pt[1]), float(conf)))

        return matches

    def _deduplicate_detections(
        self,
        detections: list[DetectedComponent],
        min_distance: int = 10,
    ) -> list[DetectedComponent]:
        """Remove duplicate detections that are too close together."""
        if not detections:
            return []

        # Sort by confidence (highest first)
        detections.sort(key=lambda d: d.confidence, reverse=True)
        kept = []

        for det in detections:
            is_dup = False
            for existing in kept:
                dx = abs(det.screen_x - existing.screen_x)
                dy = abs(det.screen_y - existing.screen_y)
                if dx < min_distance and dy < min_distance:
                    is_dup = True
                    break
            if not is_dup:
                kept.append(det)

        return kept

    # ── Confidence Assessment ─────────────────────────────────────────────────

    def _assess_confidence(self, state: GameState) -> DetectionConfidence:
        """Rate overall detection quality based on individual detections."""
        scores = []

        if state.stage_confidence > 0:
            scores.append(state.stage_confidence)
        if state.phase_confidence > 0:
            scores.append(state.phase_confidence)
        for comp in state.held_components:
            scores.append(comp.confidence)
        for champ in state.board_champions:
            scores.append(champ.confidence)

        if not scores:
            return DetectionConfidence.LOW

        avg = sum(scores) / len(scores)
        if avg > 0.90:
            return DetectionConfidence.HIGH
        elif avg > 0.80:
            return DetectionConfidence.MEDIUM
        elif avg > 0.70:
            return DetectionConfidence.LOW
        else:
            return DetectionConfidence.GUESS

    # ── Debug Output ──────────────────────────────────────────────────────────

    def _save_debug_frame(self, frame: np.ndarray, state: GameState):
        """Save an annotated frame for debugging."""
        LOG_FRAME_DIR.mkdir(parents=True, exist_ok=True)
        annotated = frame.copy()

        # Draw ROI rectangles
        h, w = frame.shape[:2]
        for name, roi in vars(self.rois).items():
            if isinstance(roi, type(self.rois.stage)):
                x, y, rw, rh = roi.to_pixels(w, h)
                cv2.rectangle(annotated, (x, y), (x+rw, y+rh), (0, 255, 0), 1)
                cv2.putText(
                    annotated, name, (x, y-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1
                )

        # Draw detected components
        for comp in state.held_components:
            cv2.circle(
                annotated, (comp.screen_x, comp.screen_y),
                8, (255, 0, 0), 2
            )

        path = LOG_FRAME_DIR / f"frame_{state.frame_number:06d}.png"
        cv2.imwrite(str(path), annotated)
