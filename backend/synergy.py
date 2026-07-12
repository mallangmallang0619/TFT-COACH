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

from collections import Counter

from game_state import (
    ActiveSynergy,
    CompSuggestion,
    DetectedChampion,
)
from game_data import (
    CHAMPIONS,
    TRAITS,
    COMPS,
    ITEM_RECIPES,
    META_COMPS,
    META_COMPS_BY_CARRY,
    _normalize_augment_name,
)
from tftacademy_live import canonical_name

# Item-name → recipe lookup for translating a comp's build items into the
# components the player would need to hold.
_RECIPE_BY_NAME: dict[str, tuple] = {r["name"]: r["recipe"] for r in ITEM_RECIPES}


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

    return synergies_from_counts(counts)


def synergies_from_counts(counts: dict[str, int]) -> list[ActiveSynergy]:
    """
    Build ActiveSynergy entries from raw {trait: unit_count} tallies.

    Split out of compute_active_synergies so other count sources — e.g. the
    detector reading the HUD trait panel on live frames — produce identical
    synergy objects.
    """
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


def _layout_from_detail(detail: dict) -> list[dict]:
    """Recommended final board from a scraped comp detail (0-27 hex indices)."""
    return [
        {
            "name": canonical_name(u["name"]),
            "board_index": u["boardIndex"],
            "stars": u.get("stars", 1),
            "items": [canonical_name(i["name"]) for i in (u.get("items") or [])],
            "cost": CHAMPIONS.get(canonical_name(u["name"]), {}).get("cost", 1),
        }
        for u in (detail or {}).get("units") or []
        if u.get("name") and u.get("boardIndex") is not None
    ]


def _item_names_from_detail(detail: dict) -> list[str]:
    """All build items across a scraped comp's units (canonical names)."""
    return [
        canonical_name(i["name"])
        for u in (detail or {}).get("units") or []
        for i in (u.get("items") or [])
    ]


def _augment_names_from_detail(detail: dict) -> list[str]:
    """Recommended augment display names from a scraped comp detail."""
    return [a["name"] for a in (detail or {}).get("augments") or [] if a.get("name")]


def _carry_items_from_detail(detail: dict) -> set[str]:
    """The main carry's build items — the strongest itemization signal."""
    carry = canonical_name(
        ((detail or {}).get("main_champion") or {}).get("name") or ""
    )
    if not carry:
        return set()
    for u in (detail or {}).get("units") or []:
        if canonical_name(u.get("name") or "") == carry:
            return {canonical_name(i["name"]) for i in (u.get("items") or [])}
    return set()


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

        # Recommended final-board layout (units with a boardIndex), the
        # comp's item builds, and its recommended augments — used for
        # positioning display and item/augment-aware scoring.
        layout = _layout_from_detail(detail)
        item_names = _item_names_from_detail(detail)
        augment_names = _augment_names_from_detail(detail)

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
            "_meta_layout":        layout,
            "_meta_item_names":    item_names,
            "_meta_augments":      augment_names,
            "_meta_carry_items":   _carry_items_from_detail(detail),
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


def _item_fit(
    comp_item_names: list[str],
    component_ids: list[str],
) -> tuple[float, str | None]:
    """
    How well the player's held components feed this comp's item builds.

    Returns (fraction of held components the comp can use, note). Each build
    item is decomposed into its two components via ITEM_RECIPES; components
    the comp needs multiple times count multiple times.
    """
    if not comp_item_names or not component_ids:
        return 0.0, None

    needed: dict[str, int] = {}
    for item_name in comp_item_names:
        for comp_id in _RECIPE_BY_NAME.get(item_name, ()):
            needed[comp_id] = needed.get(comp_id, 0) + 1

    have: dict[str, int] = {}
    for comp_id in component_ids:
        have[comp_id] = have.get(comp_id, 0) + 1

    matched = sum(min(n, have.get(c, 0)) for c, n in needed.items())
    fit = matched / len(component_ids)
    if matched == 0:
        return 0.0, None

    # Name one item the player can already work toward, for the tip.
    example = next(
        (i for i in comp_item_names
         if any(c in have and have[c] > 0 for c in _RECIPE_BY_NAME.get(i, ()))),
        None,
    )
    note = f"Your components build into {example}." if example else None
    return fit, note


def _augment_fit(
    comp_augment_names: list[str],
    selected_augments: list[str],
) -> tuple[int, list[str]]:
    """How many of the player's taken augments this comp recommends."""
    if not comp_augment_names or not selected_augments:
        return 0, []
    comp_norm = {_normalize_augment_name(a): a for a in comp_augment_names}
    matches = [
        comp_norm[_normalize_augment_name(sel)]
        for sel in selected_augments
        if _normalize_augment_name(sel) in comp_norm
    ]
    return len(matches), matches


# Context bonuses — additive on top of the unit/trait base score, so they
# reorder close calls without letting an empty board "match" a comp.
#
# Items outweigh units on purpose: a unit can be sold and replaced in one
# shop, but a slammed item is permanent — itemization decides the comp.
# One slammed build-item is worth roughly 2-3 core units of score; carry
# items count double again.
_ITEM_FIT_BONUS_MAX   = 0.25   # held components that build into the comp's items
_SLAMMED_ITEM_BONUS   = 0.12   # each completed item on our units the comp builds
_SLAMMED_ITEM_CAP     = 0.36
_CARRY_ITEM_WEIGHT    = 2.0    # slammed items for the comp's CARRY count double
_AUGMENT_MATCH_BONUS  = 0.15   # per taken augment the comp recommends
_AUGMENT_BONUS_CAP    = 0.30


def _slammed_item_fit(
    comp_item_names: list[str],
    carry_items: set[str],
    board_champions: list[DetectedChampion],
    bench_champions: list[DetectedChampion] | None,
) -> tuple[float, list[str]]:
    """
    Score the completed items already sitting on the player's units against
    this comp's build. Returns (bonus, matched item names).
    """
    have: Counter[str] = Counter()
    for champ in list(board_champions) + list(bench_champions or []):
        for item in champ.items or []:
            have[item] += 1
    if not have or not comp_item_names:
        return 0.0, []

    need = Counter(comp_item_names)
    bonus = 0.0
    matched: list[str] = []
    for name, needed in need.items():
        count = min(needed, have.get(name, 0))
        if count:
            weight = _CARRY_ITEM_WEIGHT if name in carry_items else 1.0
            bonus += count * _SLAMMED_ITEM_BONUS * weight
            matched.append(name)
    return min(_SLAMMED_ITEM_CAP, bonus), matched


def detect_comp_direction(
    synergies: list[ActiveSynergy],
    board_champions: list[DetectedChampion],
    bench_champions: list[DetectedChampion] | None = None,
    top_n: int = 3,
    component_ids: list[str] | None = None,
    selected_augments: list[str] | None = None,
) -> list[CompSuggestion]:
    """
    Rank comps by how well the current board matches each entry in COMPS.

    Beyond unit/trait overlap, the score reacts to context: held components
    that feed a comp's item builds and already-taken augments the comp
    recommends both push that comp up the ranking.

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

        # Combine into a 0-1 base score
        match_score = min(1.0, (trait_score * _TRAIT_WEIGHT + unit_score) / (1 + _TRAIT_WEIGHT))

        if match_score < _MIN_VIABLE_SCORE:
            continue

        # Resolve the TFT Academy entry early — its scraped detail feeds
        # both the context bonuses and the layout payload. Dynamic comps
        # already carry the detail fields; curated comps borrow them from
        # whichever META_COMPS entry they match.
        if "_meta_tier" in comp:
            meta = {
                "name":  comp["name"],
                "tier":  comp["_meta_tier"],
                "trend": comp.get("_meta_trend", ""),
            }
            layout = comp.get("_meta_layout") or []
            comp_item_names = comp.get("_meta_item_names") or []
            comp_augments = comp.get("_meta_augments") or []
            carry_items = comp.get("_meta_carry_items") or set()
        else:
            meta = _match_meta_comp(comp, board_names, syn_by_name)
            detail = (meta or {}).get("detail") or {}
            layout = _layout_from_detail(detail)
            comp_item_names = _item_names_from_detail(detail)
            comp_augments = _augment_names_from_detail(detail)
            carry_items = _carry_items_from_detail(detail)

        # Context boosts. Itemization comes first and weighs heaviest:
        # completed items already slammed on our units are commitments the
        # comp must honor, held components are strong hints, and augments
        # confirm the direction.
        context_notes: list[str] = []
        slam_bonus, slammed = _slammed_item_fit(
            comp_item_names, carry_items, board_champions, bench_champions
        )
        if slam_bonus > 0:
            match_score = min(1.0, match_score + slam_bonus)
            context_notes.append(
                f"Your {', '.join(slammed[:3])} "
                f"{'are' if len(slammed) > 1 else 'is'} in this comp's build."
            )
        fit, item_note = _item_fit(comp_item_names, component_ids or [])
        if fit > 0:
            match_score = min(1.0, match_score + fit * _ITEM_FIT_BONUS_MAX)
            if item_note:
                context_notes.append(item_note)
        aug_matches, matched_augs = _augment_fit(comp_augments, selected_augments or [])
        if aug_matches:
            match_score = min(
                1.0,
                match_score + min(_AUGMENT_BONUS_CAP, aug_matches * _AUGMENT_MATCH_BONUS),
            )
            context_notes.append(
                f"Your {', '.join(matched_augs[:2])} augment"
                f"{'s are' if aug_matches > 1 else ' is'} recommended for this comp."
            )

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

        if context_notes:
            tip = tip + " " + " ".join(context_notes)

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
            board_layout=layout,
            recommended_augments=comp_augments,
            context_notes=context_notes,
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
