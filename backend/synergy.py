"""
Synergy & Comp Detection

Two pure functions that operate on the detected board state:

  compute_active_synergies(board_champions)
      → list[ActiveSynergy] with counts and breakpoints, ready to drop
      onto GameState. Each unique champion counts once per trait.

  detect_comp_direction(synergies, board_champions, bench_champions)
      → list[CompSuggestion] ranked by how well the player's current
      board matches each entry in the COMPS catalog.

Both functions are deterministic and have no I/O — making them easy to
unit-test without templates, OCR, or a running game.
"""

from __future__ import annotations

from game_state import (
    ActiveSynergy,
    CompSuggestion,
    DetectedChampion,
)
from game_data import (
    CHAMPIONS,
    TRAITS,
    COMPS,
    META_COMPS,
    META_COMPS_BY_CARRY,
)
from tftacademy_live import canonical_name


# ── Active Synergies ──────────────────────────────────────────────────────────

def compute_active_synergies(
    board_champions: list[DetectedChampion],
) -> list[ActiveSynergy]:
    """
    Compute the full list of active and partially-active synergies for
    the board.

    TFT counts trait contributions by *unique champion*: stacking a
    duplicate of the same unit (1-star + 2-star) does not double a
    trait. Bench units do NOT contribute — only board units do.
    """
    # Collect unique champion names actually placed on the board
    unique_names: set[str] = set()
    for champ in board_champions:
        if champ.board_row is None or champ.board_col is None:
            # Skip anything without a board slot — those are bench-side
            continue
        unique_names.add(champ.name)

    # Tally trait contributions across unique champions
    counts: dict[str, int] = {}
    for name in unique_names:
        data = CHAMPIONS.get(name)
        if not data:
            continue
        for trait in data.get("traits", []):
            counts[trait] = counts.get(trait, 0) + 1

    synergies: list[ActiveSynergy] = []
    for trait_name, count in counts.items():
        trait_data = TRAITS.get(trait_name)
        if trait_data:
            breakpoints = trait_data.get("breakpoints", [])
            first_bp = breakpoints[0] if breakpoints else 1
            # Next breakpoint = smallest BP greater than current count, or
            # the highest BP if we're already at the cap.
            next_bp = first_bp
            for bp in breakpoints:
                if count < bp:
                    next_bp = bp
                    break
            else:
                next_bp = breakpoints[-1] if breakpoints else first_bp
        else:
            first_bp = 2
            next_bp = max(2, count + 1)

        synergies.append(ActiveSynergy(
            name=trait_name,
            count=count,
            breakpoint=next_bp,
            is_active=count >= first_bp,
        ))

    # Sort active first, then by count descending
    synergies.sort(key=lambda s: (not s.is_active, -s.count, s.name))
    return synergies


def current_breakpoint_index(trait_name: str, count: int) -> int:
    """Return the index of the current activated breakpoint, or -1 if not active."""
    trait_data = TRAITS.get(trait_name)
    if not trait_data:
        return -1
    bp_index = -1
    for i, bp in enumerate(trait_data.get("breakpoints", [])):
        if count >= bp:
            bp_index = i
    return bp_index


def power_at_breakpoint(trait_name: str, target_count: int) -> float:
    """How much synergy power a trait grants once `target_count` units are fielded."""
    trait_data = TRAITS.get(trait_name)
    if not trait_data:
        return 0.0
    breakpoints = trait_data.get("breakpoints", [])
    powers = trait_data.get("power_per_breakpoint", [])
    bp_index = -1
    for i, bp in enumerate(breakpoints):
        if target_count >= bp:
            bp_index = i
    if 0 <= bp_index < len(powers):
        return float(powers[bp_index])
    return 0.0


# ── Comp Direction Detection ──────────────────────────────────────────────────

# Scoring weights (tuned by hand — adjust if comp ranking feels off)
_CORE_WEIGHT       = 1.0   # Each core unit on the board
_FLEX_WEIGHT       = 0.4   # Each flex unit on the board
_BENCH_CORE_WEIGHT = 0.5   # Cores sitting on the bench (held but not played)
_TRAIT_WEIGHT      = 1.5   # How much trait progress matters relative to units
_MIN_VIABLE_SCORE  = 0.20  # Drop comps below this so we only surface real fits


# ── Dynamic comps from scraped META_COMPS detail ──────────────────────────────

def _derive_target_traits(unit_names: list[str]) -> list[tuple[str, int]]:
    """
    Pick the traits with the most coverage across a scraped comp's units.
    Returns up to three (trait, unit-count) tuples — the matcher uses these
    as the breakpoint targets to score how close the player is.
    """
    counts: dict[str, int] = {}
    for name in unit_names:
        data = CHAMPIONS.get(name)
        if not data:
            continue
        for trait in data.get("traits", []):
            counts[trait] = counts.get(trait, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [(t, c) for t, c in ranked if c >= 2][:3]


def _split_cores_and_flexes(
    units: list[dict],
    main_carry: str | None,
) -> tuple[list[str], list[str]]:
    """
    Promote main carry / item-holding / 3+-cost units to "core" status —
    these are the units the matcher should weight more heavily when a comp
    is being identified. Everything else becomes "flex" filler.
    """
    cores: list[str] = []
    flexes: list[str] = []
    for u in units:
        name = canonical_name(u.get("name") or "")
        if not name:
            continue
        is_main = main_carry and name == canonical_name(main_carry)
        has_items = bool(u.get("items"))
        cost = CHAMPIONS.get(name, {}).get("cost", 0)
        if is_main or has_items or cost >= 3:
            cores.append(name)
        else:
            flexes.append(name)
    return cores, flexes


def build_comps_from_meta() -> list[dict]:
    """
    Convert scraped META_COMPS entries (with `detail.units`) into the same
    dict shape that the curated COMPS list uses, so detect_comp_direction()
    can score them with no special-casing.

    Comps without scraped detail are skipped — they fall through to the
    curated COMPS list in get_active_comps().
    """
    result: list[dict] = []
    for meta in META_COMPS:
        detail = meta.get("detail") or {}
        units = detail.get("units") or []
        if not units:
            continue

        unit_names = [
            canonical_name(u["name"]) for u in units if u.get("name")
        ]
        if not unit_names:
            continue

        main_carry_raw = (detail.get("main_champion") or {}).get("name") or meta.get("carry")
        cores, flexes = _split_cores_and_flexes(units, main_carry_raw)
        target_traits = _derive_target_traits(unit_names)

        result.append({
            "name":          meta["name"],
            "target_traits": target_traits,
            "core_units":    cores,
            "flex_units":    flexes,
            "playstyle":     (detail.get("tip") or "").strip(),
            # Carry-through fields so detect_comp_direction() can attach
            # tier info without re-querying _match_meta_comp().
            "_meta_carry":         meta.get("carry"),
            "_meta_match_traits":  meta.get("match_traits", []),
            "_meta_tier":          meta.get("tier"),
            "_meta_slug":          meta.get("slug"),
            "_meta_trend":         meta.get("trend", ""),
            "_source":             "meta",
        })
    return result


def get_active_comps() -> list[dict]:
    """
    Live comp catalog for the matcher.

    Prefers scraped META_COMPS detail (real, current-patch unit lists with
    items, items, augments, tip) and falls back to the hand-curated COMPS
    list for any name not yet covered by a scrape.
    """
    dynamic = build_comps_from_meta()
    dynamic_names = {c["name"] for c in dynamic}
    fallback = [c for c in COMPS if c["name"] not in dynamic_names]
    return dynamic + fallback


def detect_comp_direction(
    synergies: list[ActiveSynergy],
    board_champions: list[DetectedChampion],
    bench_champions: list[DetectedChampion] | None = None,
    top_n: int = 3,
) -> list[CompSuggestion]:
    """
    Rank comps by how well the current board matches each entry in COMPS.

    Returns up to `top_n` suggestions ordered by match score. The
    highest-scoring comp is flagged `is_primary=True` — that's what the
    coach should treat as "the comp the player is going for."
    """
    syn_by_name = {s.name: s for s in synergies}
    board_names = {
        c.name for c in board_champions
        if c.board_row is not None and c.board_col is not None
    }
    bench_names = {c.name for c in (bench_champions or [])}

    suggestions: list[CompSuggestion] = []

    for comp in get_active_comps():
        cores: list[str]   = comp["core_units"]
        flexes: list[str]  = comp["flex_units"]
        targets: list[tuple[str, int]] = comp["target_traits"]

        # Unit overlap
        cores_held   = [u for u in cores  if u in board_names]
        flexes_held  = [u for u in flexes if u in board_names]
        cores_bench  = [u for u in cores  if u in bench_names and u not in board_names]

        unit_total   = max(1, len(cores) + len(flexes))
        unit_score = (
            _CORE_WEIGHT * len(cores_held)
            + _FLEX_WEIGHT * len(flexes_held)
            + _BENCH_CORE_WEIGHT * len(cores_bench)
        ) / unit_total

        # Trait progress: average ratio of (current / target) across all target traits
        trait_progress = []
        next_bp_trait: str | None = None
        next_bp_count: int | None = None
        next_bp_power = 0.0

        for trait_name, target in targets:
            current = syn_by_name[trait_name].count if trait_name in syn_by_name else 0
            ratio = min(1.0, current / target) if target else 0.0
            trait_progress.append(ratio)

            # Track the closest unmet breakpoint for the headline trait
            if current < target and next_bp_trait is None:
                next_bp_trait = trait_name
                next_bp_count = target - current
                next_bp_power = power_at_breakpoint(trait_name, target)

        trait_score = sum(trait_progress) / len(trait_progress) if trait_progress else 0.0

        # Combine into a 0-1 score
        match_score = min(1.0, (trait_score * _TRAIT_WEIGHT + unit_score) / (1 + _TRAIT_WEIGHT))

        if match_score < _MIN_VIABLE_SCORE:
            continue

        # Held vs missing units (board only — bench is "not yet played")
        held = sorted(cores_held + flexes_held, key=lambda n: 0 if n in cores else 1)
        missing_cores  = [u for u in cores  if u not in board_names]
        missing_flexes = [u for u in flexes if u not in board_names]
        missing = missing_cores + missing_flexes

        # Progress label like "3/5 Meeple, 1/4 Stargazer"
        progress_parts = []
        for trait_name, target in targets:
            cur = syn_by_name[trait_name].count if trait_name in syn_by_name else 0
            progress_parts.append(f"{cur}/{target} {trait_name}")
        progress = ", ".join(progress_parts)

        # Look up TFT Academy tier rating. Dynamic comps already carry the
        # metadata; curated comps still need the heuristic lookup.
        if "_meta_tier" in comp:
            meta = {
                "name":  comp["name"],
                "tier":  comp["_meta_tier"],
                "trend": comp.get("_meta_trend", ""),
            }
        else:
            meta = _match_meta_comp(comp, board_names, syn_by_name)

        # Build a one-line tip the coach can show directly
        tip = _format_direction_tip(
            comp["name"],
            cores_held,
            cores_bench,
            missing_cores,
            next_bp_trait,
            next_bp_count,
            next_bp_power,
            comp.get("playstyle", ""),
            meta,
        )

        suggestions.append(CompSuggestion(
            name=comp["name"],
            match_score=round(match_score, 3),
            progress=progress,
            held_units=held,
            missing_units=missing[:6],     # cap to keep payload small
            next_breakpoint=next_bp_count,
            next_breakpoint_trait=next_bp_trait,
            power_at_next_breakpoint=round(next_bp_power, 1),
            direction_tip=tip,
            tftacademy_name=meta["name"] if meta else None,
            tftacademy_tier=meta["tier"] if meta else None,
            tftacademy_trend=meta.get("trend") if meta else None,
        ))

    suggestions.sort(key=lambda s: (-s.match_score, _meta_tier_order(s.tftacademy_tier)))
    suggestions = suggestions[:top_n]
    if suggestions:
        suggestions[0].is_primary = True
    return suggestions


# ── TFT Academy Lookup ────────────────────────────────────────────────────────

_META_TIER_ORDER = {"S": 0, "A": 1, "B": 2, "C": 3, "X": 4}


def _meta_tier_order(tier: str | None) -> int:
    """Used as a tie-breaker when two comps have similar match scores."""
    return _META_TIER_ORDER.get(tier or "", 99)


def _match_meta_comp(
    comp: dict,
    board_names: set[str],
    syn_by_name: dict[str, ActiveSynergy],
) -> dict | None:
    """
    Find the TFT Academy entry that best matches one of our internal COMPS.

    Strategy:
      1. If the carry of any META_COMPS entry is fielded on the board AND the
         entry's match traits overlap with the comp's target traits, that's a
         confident match — return it.
      2. Otherwise fall back to the carry-only check (some comps don't tag
         match_traits cleanly).
      3. If nothing matches, return None — the suggestion still ships, just
         without external tier info.
    """
    target_trait_names = {t for t, _ in comp.get("target_traits", [])}
    comp_carries = set(comp.get("core_units", []))

    best: dict | None = None
    best_score = -1

    for meta in META_COMPS:
        score = 0
        carry = meta["carry"]
        match_traits = set(meta.get("match_traits", []))

        # Strong signal: TFT Academy's carry is on our board
        if carry in board_names:
            score += 3
        # Medium signal: TFT Academy's carry is one of our comp's core units
        if carry in comp_carries:
            score += 2
        # Trait overlap with our target traits
        score += len(match_traits & target_trait_names)
        # Bonus when matched traits are also active on the player's board
        score += sum(1 for t in match_traits if t in syn_by_name and syn_by_name[t].count > 0)

        if score > best_score and score >= 3:
            best_score = score
            best = meta

    return best


def _format_direction_tip(
    comp_name: str,
    cores_held: list[str],
    cores_bench: list[str],
    missing_cores: list[str],
    next_bp_trait: str | None,
    next_bp_count: int | None,
    next_bp_power: float,
    playstyle: str,
    meta: dict | None = None,
) -> str:
    """Compose a single concise sentence describing comp direction."""
    parts: list[str] = []

    # Lead with TFT Academy framing when we have a tier rating
    if meta:
        trend_str = ""
        if meta.get("trend") == "rising":
            trend_str = " ↑ rising"
        elif meta.get("trend") == "falling":
            trend_str = " ↓ falling"
        elif meta.get("trend") == "new":
            trend_str = " (new this patch)"
        ta_label = f"TFT Academy: {meta['name']} — {meta['tier']}-tier{trend_str}."
        parts.append(ta_label)

    if cores_held:
        parts.append(f"You have {', '.join(cores_held)} — pointing toward {comp_name}.")
    elif cores_bench:
        parts.append(f"{', '.join(cores_bench)} on bench is the start of {comp_name}.")
    else:
        parts.append(f"Could pivot into {comp_name}.")

    if next_bp_trait and next_bp_count:
        bonus = f" (+{next_bp_power:.0f} synergy power)" if next_bp_power > 0 else ""
        parts.append(
            f"Need {next_bp_count} more {next_bp_trait} to hit the next breakpoint{bonus}."
        )

    if missing_cores:
        parts.append(f"Look for: {', '.join(missing_cores[:3])}.")

    if playstyle:
        parts.append(playstyle)

    return " ".join(parts)
