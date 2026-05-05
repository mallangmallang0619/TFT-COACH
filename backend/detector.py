"""
Computer Vision Detection Pipeline

Processes captured frames to extract game state:
  - Template matching for components, champions, UI elements
  - OCR for stage, HP, gold, augment names
  - Phase detection from UI layout analysis
NEVER TESTED
"""

from __future__ import annotations
import logging
import time
from pathlib import Path
from typing import Optional

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
except ImportError:
    pytesseract = None

from config import (
    TEMPLATE_DIR,
    COMPONENT_TEMPLATE_DIR,
    CHAMPION_TEMPLATE_DIR,
    CONFIDENCE_THRESHOLD,
    COMPONENT_MATCH_THRESHOLD,
    CHAMPION_MATCH_THRESHOLD,
    OCR_CONFIDENCE_MIN,
    BOARD_HEX_GRID,
    COMPONENT_IDS,
    LOG_DETECTION_FRAMES,
    LOG_FRAME_DIR,
    GameROIs,
)
from game_state import (
    GameState,
    GamePhase,
    DetectedComponent,
    DetectedChampion,
    DetectedAugment,
    DetectionConfidence,
)

logger = logging.getLogger(__name__)


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
        self.champion_templates: dict[str, np.ndarray] = {}
        self.ui_templates: dict[str, np.ndarray] = {}
        self._loaded = False

    def load(self):
        """Load all template images from disk."""
        self.component_templates = self._load_dir(COMPONENT_TEMPLATE_DIR)
        self.champion_templates = self._load_dir(CHAMPION_TEMPLATE_DIR)
        self.ui_templates = self._load_dir(TEMPLATE_DIR / "ui")
        self._loaded = True

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

    def __init__(self, templates: Optional[TemplateStore] = None):
        self.templates = templates or TemplateStore()
        self.rois = GameROIs()
        self._frame_count = 0

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
            state.detection_ms = (time.time() - t_start) * 1000
            return state

        # 2. Core stats (always detect these during a game)
        state.stage, state.stage_confidence = self._ocr_stage(frame)
        state.player_hp = self._ocr_number(frame, self.rois.player_hp, "HP")
        state.gold = self._ocr_number(frame, self.rois.gold, "Gold")
        state.level = self._ocr_number(frame, self.rois.level, "Level")

        # 3. Item components on bench
        state.held_components = self._detect_components(frame)
        state.component_ids = [c.component_id for c in state.held_components]

        # 4. Board champions (only during planning/combat)
        if state.phase in (GamePhase.PLANNING, GamePhase.COMBAT):
            state.board_champions = self._detect_board_champions(frame)
            state.bench_champions = self._detect_bench_champions(frame)

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
        """Detect the augment selection overlay by checking for darkened background."""
        if region.size == 0:
            return False
        # Augment screen has a dark semi-transparent overlay
        mean_brightness = np.mean(region)
        # Also check for the characteristic augment card borders
        gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.count_nonzero(edges) / edges.size
        # Augment screen: relatively dark with structured edges
        return mean_brightness < 80 and edge_density > 0.02

    def _is_blank_or_loading(self, region: np.ndarray) -> bool:
        """Check if a region is mostly blank (not in game)."""
        if region.size == 0:
            return True
        return np.std(region) < 15  # Very low variance = blank/solid color

    # ── OCR Detection ─────────────────────────────────────────────────────────

    def _ocr_stage(self, frame: np.ndarray) -> tuple[str, float]:
        """OCR the stage indicator (e.g., '3-2')."""
        h, w = frame.shape[:2]
        x, y, rw, rh = self.rois.stage.to_pixels(w, h)
        region = frame[y:y+rh, x:x+rw]

        text = self._ocr_region(region, whitelist="0123456789-Stage ")

        # Try to extract a stage pattern like "3-2" or "Stage 3-2"
        import re
        match = re.search(r"(\d)-(\d)", text)
        if match:
            stage_str = f"{match.group(1)}-{match.group(2)}"
            return stage_str, 0.85

        return "?", 0.0

    def _ocr_number(
        self,
        frame: np.ndarray,
        roi: "RegionOfInterest",
        label: str = "",
    ) -> int:
        """OCR a numeric value from a specific ROI."""
        h, w = frame.shape[:2]
        x, y, rw, rh = roi.to_pixels(w, h)
        region = frame[y:y+rh, x:x+rw]

        text = self._ocr_region(region, whitelist="0123456789")

        try:
            value = int(text.strip())
            return value
        except ValueError:
            logger.debug(f"OCR failed for {label}: got '{text}'")
            return 0

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

        for comp_id, template in self.templates.component_templates.items():
            matches = self._multi_template_match(
                bench_region, template, COMPONENT_MATCH_THRESHOLD
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

    # ── Champion Detection ────────────────────────────────────────────────────

    def _detect_board_champions(self, frame: np.ndarray) -> list[DetectedChampion]:
        """
        Detect champions on the board by sampling each hex position.
        """
        if not self.templates.champion_templates:
            return []

        h, w = frame.shape[:2]
        bx, by, bw, bh = self.rois.board.to_pixels(w, h)
        board_region = frame[by:by+bh, bx:bx+bw]

        if board_region.size == 0:
            return []

        detected = []
        brh, brw = board_region.shape[:2]

        for hex_pos in BOARD_HEX_GRID:
            # Extract the area around this hex
            cx = int(hex_pos.cx * brw)
            cy = int(hex_pos.cy * brh)
            r = int(hex_pos.radius * brw)

            # Bounds check
            x1 = max(0, cx - r)
            y1 = max(0, cy - r)
            x2 = min(brw, cx + r)
            y2 = min(brh, cy + r)
            hex_crop = board_region[y1:y2, x1:x2]

            if hex_crop.size == 0:
                continue

            # Check if this hex has a champion (not empty)
            if self._is_hex_empty(hex_crop):
                continue

            # Match against champion templates
            best_name = "Unknown"
            best_conf = 0.0

            for champ_name, template in self.templates.champion_templates.items():
                # Resize template to match hex crop size
                resized = cv2.resize(template, (hex_crop.shape[1], hex_crop.shape[0]))
                result = cv2.matchTemplate(hex_crop, resized, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)

                if max_val > best_conf and max_val > CHAMPION_MATCH_THRESHOLD:
                    best_conf = max_val
                    best_name = champ_name

            if best_conf > CHAMPION_MATCH_THRESHOLD:
                detected.append(DetectedChampion(
                    name=best_name,
                    board_row=hex_pos.row,
                    board_col=hex_pos.col,
                    confidence=best_conf,
                ))

        return detected

    def _detect_bench_champions(self, frame: np.ndarray) -> list[DetectedChampion]:
        """Detect champions on the bench row."""
        # Similar to board detection but for the bench region
        # Bench has 9 slots in a horizontal row
        if not self.templates.champion_templates:
            return []

        h, w = frame.shape[:2]
        bx, by, bw, bh = self.rois.champion_bench.to_pixels(w, h)
        bench_region = frame[by:by+bh, bx:bx+bw]

        if bench_region.size == 0:
            return []

        detected = []
        brh, brw = bench_region.shape[:2]
        slot_width = brw // 9

        for slot in range(9):
            sx = slot * slot_width
            slot_crop = bench_region[:, sx:sx+slot_width]

            if slot_crop.size == 0 or self._is_hex_empty(slot_crop):
                continue

            best_name = "Unknown"
            best_conf = 0.0

            for champ_name, template in self.templates.champion_templates.items():
                resized = cv2.resize(template, (slot_crop.shape[1], slot_crop.shape[0]))
                result = cv2.matchTemplate(slot_crop, resized, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, _ = cv2.minMaxLoc(result)

                if max_val > best_conf and max_val > CHAMPION_MATCH_THRESHOLD:
                    best_conf = max_val
                    best_name = champ_name

            if best_conf > CHAMPION_MATCH_THRESHOLD:
                detected.append(DetectedChampion(
                    name=best_name,
                    confidence=best_conf,
                ))

        return detected

    def _is_hex_empty(self, hex_crop: np.ndarray) -> bool:
        """Check if a hex/slot is empty (no champion placed)."""
        # Empty hexes tend to have low color variance and dark values
        hsv = cv2.cvtColor(hex_crop, cv2.COLOR_BGR2HSV)
        saturation = hsv[:, :, 1]
        # Champions have more color saturation than empty hexes
        return np.mean(saturation) < 30

    # ── Augment Detection ─────────────────────────────────────────────────────

    def _detect_augments(self, frame: np.ndarray) -> list[DetectedAugment]:
        """
        Detect augment options during the augment selection screen.
        Uses OCR to read augment names from the three card positions.
        """
        h, w = frame.shape[:2]
        ax, ay, aw, ah = self.rois.augment_panel.to_pixels(w, h)
        panel = frame[ay:ay+ah, ax:ax+aw]

        if panel.size == 0:
            return []

        ph, pw = panel.shape[:2]
        augments = []

        # Three augment cards are roughly evenly spaced horizontally
        card_width = pw // 3
        for i in range(3):
            cx = i * card_width
            card = panel[:, cx:cx+card_width]

            # The augment name is typically in the upper portion of the card
            name_region = card[:int(ph * 0.3), :]
            name_text = self._ocr_region(name_region)

            if name_text and len(name_text) > 2:
                # Detect tier by analyzing the card border color
                tier = self._detect_augment_tier(card)
                augments.append(DetectedAugment(
                    name=name_text,
                    tier=tier,
                    slot_index=i,
                    confidence=0.6,  # OCR is lower confidence
                ))

        return augments

    def _detect_augment_tier(self, card_region: np.ndarray) -> str:
        """Determine augment tier (Silver/Gold/Prismatic) from card border color."""
        # Sample the border pixels
        border = card_region[:5, :]  # Top edge
        hsv = cv2.cvtColor(border, cv2.COLOR_BGR2HSV)
        mean_hue = np.mean(hsv[:, :, 0])
        mean_sat = np.mean(hsv[:, :, 1])

        if mean_sat < 50:
            return "Silver"
        elif 20 < mean_hue < 35:  # Yellowish
            return "Gold"
        else:
            return "Prismatic"

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
