"""
System Test

Verifies each layer of the stack works independently.
Run this first to catch issues before launching the full app.

Usage:
    cd tft-coach-desktop
    python3 backend/test_system.py
"""

import sys
import asyncio
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# Windows consoles default to a legacy code page (cp1252) that can't encode
# the emoji below — force UTF-8 so the runner doesn't crash mid-report.
for _stream in (sys.stdout, sys.stderr):
    if _stream.encoding and _stream.encoding.lower() not in ("utf-8", "utf8"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

PASS = "✅"
FAIL = "❌"
WARN = "⚠️"
results = []


def test(name, fn):
    """Run a test and record result."""
    try:
        msg = fn()
        results.append((PASS, name, msg or "OK"))
        print(f"  {PASS} {name}: {msg or 'OK'}")
    except Exception as e:
        results.append((FAIL, name, str(e)))
        print(f"  {FAIL} {name}: {e}")


def warn(name, msg):
    results.append((WARN, name, msg))
    print(f"  {WARN} {name}: {msg}")


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_config():
    from config import WEBSOCKET_HOST, WEBSOCKET_PORT, GameROIs, BOARD_HEX_GRID
    rois = GameROIs()
    assert WEBSOCKET_PORT == 8765
    assert len(BOARD_HEX_GRID) == 28, f"Expected 28 hexes, got {len(BOARD_HEX_GRID)}"
    # Verify ROI ratios are valid (0-1 range)
    for name in ["stage", "player_hp", "gold", "item_bench", "board"]:
        roi = getattr(rois, name)
        assert 0 <= roi.x <= 1 and 0 <= roi.y <= 1, f"ROI {name} out of range"
    return f"port={WEBSOCKET_PORT}, {len(BOARD_HEX_GRID)} hexes, ROIs valid"


def test_game_state():
    from game_state import GameState, GamePhase, GameStateHistory
    state = GameState(stage="3-2", player_hp=72, gold=35)
    assert state.stage == "3-2"
    assert state.player_hp == 72

    # Test serialization
    data = state.to_frontend_json()
    assert isinstance(data, dict)
    assert data["stage"] == "3-2"

    # Test history
    history = GameStateHistory(max_size=5)
    for i in range(8):
        s = GameState(player_hp=100 - i * 10, stage=f"3-{i+1}")
        history.push(s)
    assert len(history.states) == 5, "History should cap at max_size"
    assert history.latest.player_hp == 30
    assert history.hp_delta(lookback=3) < 0, "HP should be decreasing"

    return f"serialize OK, history capped at 5, hp_delta={history.hp_delta(3)}"


def test_coach():
    from game_state import GameState, GamePhase
    from coach import Coach

    coach = Coach()

    # Test with components that can make items
    state = GameState(
        phase=GamePhase.PLANNING,
        stage="3-5",
        player_hp=25,
        gold=23,
        component_ids=["bf_sword", "sparring_gloves", "giants_belt", "chain_vest"],
    )
    advice = coach.analyze(state)

    assert advice.slam_urgency_level in ("low", "medium", "high", "critical")
    assert len(advice.slam_recommendations) > 0, "Should find craftable items"

    # Check that Infinity Edge (BF + Gloves, S-tier slam) is recommended
    ie = [r for r in advice.slam_recommendations if r.item_name == "Infinity Edge"]
    assert len(ie) > 0, "Should recommend Infinity Edge"
    assert ie[0].slam_urgency == "slam_now", "IE should be slam_now at stage 3-5"

    # Check that Sunfire (Belt + Vest, S-tier slam) is recommended
    sf = [r for r in advice.slam_recommendations if r.item_name == "Sunfire Cape"]
    assert len(sf) > 0, "Should recommend Sunfire Cape"

    # Low HP tip
    assert any("25 HP" in t or "danger" in t.lower() for t in advice.tips), \
        "Should warn about low HP"

    return (
        f"urgency={advice.slam_urgency_level}, "
        f"{len(advice.slam_recommendations)} items, "
        f"{len(advice.tips)} tips"
    )


def test_active_synergies():
    """compute_active_synergies counts unique champs per trait correctly."""
    from game_state import DetectedChampion
    from synergy import compute_active_synergies

    # Three Meeple champs: Poppy + Veigar (each in Meeple) and Gnar (also Meeple)
    # Veigar is also Replicator, Poppy is also Bastion, Gnar is also Sniper
    board = [
        DetectedChampion(name="Poppy",  board_row=3, board_col=1),
        DetectedChampion(name="Veigar", board_row=3, board_col=2),
        DetectedChampion(name="Gnar",   board_row=2, board_col=3),
    ]
    synergies = compute_active_synergies(board)
    by_name = {s.name: s for s in synergies}

    # Meeple breakpoints are [3, 5, 7, 10] so 3 Meeple is active at the first BP
    assert "Meeple" in by_name, "Meeple trait should be present"
    assert by_name["Meeple"].count == 3
    assert by_name["Meeple"].is_active is True
    # Next breakpoint after 3 is 5
    assert by_name["Meeple"].breakpoint == 5

    # Bastion breakpoints are [2, 4, 6] — only Poppy contributes, count = 1, not active
    assert by_name["Bastion"].count == 1
    assert by_name["Bastion"].is_active is False
    assert by_name["Bastion"].breakpoint == 2

    # Duplicate champions should not double-count: add a 2-star Veigar
    board.append(DetectedChampion(name="Veigar", star_level=2, board_row=2, board_col=4))
    syn2 = {s.name: s for s in compute_active_synergies(board)}
    assert syn2["Meeple"].count == 3, "Duplicate Veigar must not increase Meeple count"

    # Bench-side champions (no board_row/col) should NOT contribute
    board_with_bench = [
        DetectedChampion(name="Poppy",  board_row=3, board_col=1),
        DetectedChampion(name="Veigar"),  # no board pos = bench
    ]
    syn3 = {s.name: s for s in compute_active_synergies(board_with_bench)}
    assert syn3["Meeple"].count == 1, "Bench Veigar must not contribute"

    return f"3 Meeple active (next bp=5), dedupe OK, bench excluded"


def test_comp_detection():
    """detect_comp_direction picks the right comp for a partial board."""
    from game_state import DetectedChampion
    from synergy import compute_active_synergies, detect_comp_direction

    # A clearly Meeple-leaning early board
    board = [
        DetectedChampion(name="Poppy",  board_row=3, board_col=0),
        DetectedChampion(name="Veigar", board_row=3, board_col=1),
        DetectedChampion(name="Gnar",   board_row=2, board_col=2),
    ]
    synergies = compute_active_synergies(board)
    suggestions = detect_comp_direction(synergies, board)

    assert len(suggestions) > 0, "Should produce at least one comp suggestion"
    assert suggestions[0].is_primary, "Top suggestion should be marked primary"

    primary = suggestions[0]
    assert "Meeple" in primary.name, f"Primary should be the Meeple comp, got: {primary.name}"
    assert "Poppy" in primary.held_units or "Veigar" in primary.held_units
    # Next breakpoint should be the 5 Meeple target (we have 3, need 2 more)
    assert primary.next_breakpoint_trait == "Meeple"
    assert primary.next_breakpoint == 2

    # An empty board should produce no suggestions
    empty_suggestions = detect_comp_direction([], [])
    assert empty_suggestions == [], "Empty board → no suggestions"

    return f"primary={primary.name} (score={primary.match_score:.2f}), need {primary.next_breakpoint} more {primary.next_breakpoint_trait}"


def test_coach_comp_direction():
    """The Coach surfaces comp direction in its advice and tips."""
    from game_state import GameState, GamePhase, DetectedChampion
    from coach import Coach

    coach = Coach()
    state = GameState(
        phase=GamePhase.PLANNING,
        stage="3-2",
        player_hp=70,
        gold=30,
        board_champions=[
            DetectedChampion(name="Kai'Sa", star_level=2, board_row=0, board_col=6),
            DetectedChampion(name="Karma",  star_level=1, board_row=0, board_col=0),
            DetectedChampion(name="Jhin",   star_level=1, board_row=0, board_col=5),
            DetectedChampion(name="Lissandra", star_level=2, board_row=3, board_col=3),
        ],
    )

    advice = coach.analyze(state)
    assert len(advice.comp_suggestions) > 0, "Should produce comp suggestions"
    primary = advice.comp_suggestions[0]
    assert "Dark Star" in primary.name, f"Primary should be Dark Star, got: {primary.name}"

    # Verify the synergies got auto-populated by the coach
    assert any(s.name == "Dark Star" for s in state.active_synergies), \
        "Coach should auto-populate active_synergies from the board"

    # The tip should mention comp direction
    assert any("Comp direction" in t or "comp direction" in t.lower() for t in advice.tips), \
        f"Should add a comp direction tip, got: {advice.tips}"

    return f"primary={primary.name} score={primary.match_score:.2f}, synergies populated"


def test_tftacademy_enrichment():
    """CompSuggestion gets tftacademy_tier populated when META_COMPS matches."""
    from game_state import GameState, GamePhase, DetectedChampion
    from coach import Coach
    from game_data import META_COMPS, AUGMENT_RATINGS

    # Sanity: we actually loaded TFT Academy data. The tier itself comes from
    # the live-synced cache and shifts every patch, so look it up rather than
    # hardcoding it.
    assert len(META_COMPS) >= 20, f"META_COMPS too small: {len(META_COMPS)}"
    dark_star = next((c for c in META_COMPS if c["name"] == "Dark Star"), None)
    assert dark_star is not None, "Dark Star entry from TFT Academy should be present"
    assert dark_star["tier"] in ("S", "A", "B", "C", "X"), \
        f"Dark Star has invalid tier: {dark_star['tier']}"

    # New augments from the comp-page references should be in AUGMENT_RATINGS
    for aug in ("Aura Farming", "Portable Forge", "Two Tanky", "Bonk"):
        assert aug in AUGMENT_RATINGS, f"Augment '{aug}' missing from AUGMENT_RATINGS"

    # Build a Dark-Star-leaning board — Jhin is the TFT Academy carry for that comp
    coach = Coach()
    state = GameState(
        phase=GamePhase.PLANNING,
        stage="4-2",
        player_hp=60,
        gold=40,
        board_champions=[
            DetectedChampion(name="Jhin",       star_level=2, board_row=0, board_col=6),
            DetectedChampion(name="Kai'Sa",     star_level=2, board_row=0, board_col=5),
            DetectedChampion(name="Karma",      star_level=1, board_row=0, board_col=0),
            DetectedChampion(name="Lissandra",  star_level=2, board_row=3, board_col=3),
            DetectedChampion(name="Mordekaiser",star_level=2, board_row=3, board_col=2),
        ],
    )
    advice = coach.analyze(state)
    primary = advice.comp_suggestions[0]

    assert primary.tftacademy_tier == dark_star["tier"], \
        f"Dark Star should be {dark_star['tier']}-tier, got: {primary.tftacademy_tier}"
    assert primary.tftacademy_name == "Dark Star", \
        f"Should match TFT Academy 'Dark Star' entry, got: {primary.tftacademy_name}"
    # The composed direction tip should reference TFT Academy
    assert "TFT Academy" in primary.direction_tip, \
        f"Direction tip should mention TFT Academy, got: {primary.direction_tip}"

    return (
        f"primary={primary.name} → TFT Academy '{primary.tftacademy_name}' "
        f"({primary.tftacademy_tier}-tier {primary.tftacademy_trend or '—'})"
    )


def test_coach_edge_cases():
    from game_state import GameState, GamePhase
    from coach import Coach

    coach = Coach()

    # No components
    state = GameState(phase=GamePhase.PLANNING, stage="2-1", component_ids=[])
    advice = coach.analyze(state)
    assert len(advice.slam_recommendations) == 0

    # Single component (can't make anything)
    state = GameState(phase=GamePhase.PLANNING, stage="4-1", component_ids=["bf_sword"])
    advice = coach.analyze(state)
    assert len(advice.slam_recommendations) == 0

    # 6+ components should trigger hoarding warning
    state = GameState(
        phase=GamePhase.PLANNING,
        stage="3-2",
        component_ids=["bf_sword", "tear", "giants_belt", "chain_vest", "recurve_bow", "sparring_gloves"],
    )
    advice = coach.analyze(state)
    assert any("holding" in t.lower() or "components" in t.lower() for t in advice.tips), \
        "Should warn about hoarding 6 components"

    return "empty OK, single OK, hoarding warning OK"


def test_tftacademy_parser():
    """parse_patch + parse_comps handle representative HTML correctly."""
    from tftacademy_live import parse_patch, parse_comps

    # Synthetic HTML snippet covering:
    #  - patch header text
    #  - tier section headers
    #  - comp links pointing at /tierlist/comps/<slug> — the anchors on the
    #    live listing page hold icon grids, not text, so the parser derives
    #    the display name from the slug alone (set-17-dark-star → Dark Star)
    sample = """
    <html><body>
      <h1>Patch 17.2B  -  Last Updated 4 hours ago</h1>
      <section><h2>S-Tier</h2>
        <a href="/tierlist/comps/set-17-yi-marawlers"></a>
        <a href="/tierlist/comps/set-17-dark-star"></a>
      </section>
      <section><h2>A-Tier</h2>
        <a href="/tierlist/comps/set-17-fountain-lulu"></a>
        <a href="/tierlist/comps/set-17-tf-reroll"></a>
      </section>
      <section><h2>B-Tier</h2>
        <a href="/tierlist/comps/set-17-voyager-crab"></a>
      </section>
      <!-- duplicate to verify dedupe -->
      <a href="/tierlist/comps/set-17-dark-star"></a>
    </body></html>
    """

    assert parse_patch(sample) == "17.2b", f"got: {parse_patch(sample)}"

    entries = parse_comps(sample)
    by_name = {e["name"]: e["tier"] for e in entries}
    assert by_name.get("Yi Marawlers") == "S"
    assert by_name.get("Dark Star")    == "S"
    assert by_name.get("Fountain Lulu") == "A"
    assert by_name.get("Tf Reroll")    == "A"
    assert by_name.get("Voyager Crab") == "B"

    # Dedupe — the duplicate Dark Star link must not produce a 2nd entry
    dark_count = sum(1 for e in entries if e["name"] == "Dark Star")
    assert dark_count == 1, f"Dedupe failed: {dark_count} Dark Star entries"

    return f"patch=17.2b, {len(entries)} comps parsed, dedupe OK"


def test_tftacademy_cache_roundtrip():
    """load_cache / save_cache survive a roundtrip and apply_to_game_data mutates in place."""
    import tempfile
    import json
    from pathlib import Path
    import tftacademy_live
    import game_data

    # Roundtrip a synthetic cache through a temp dir
    with tempfile.TemporaryDirectory() as tmp:
        original_path = tftacademy_live.CACHE_PATH
        tftacademy_live.CACHE_PATH = Path(tmp) / "cache.json"
        try:
            payload = {
                "patch": "99.9z",
                "synced_at": "2026-05-08T00:00:00Z",
                "comps": [
                    {"name": "Test Comp", "tier": "S", "trend": "rising",
                     "carry": "Sona", "match_traits": ["Psionic"]},
                ],
            }
            assert tftacademy_live.save_cache(payload), "save_cache failed"
            loaded = tftacademy_live.load_cache()
            assert loaded["patch"] == "99.9z"
            assert loaded["comps"][0]["name"] == "Test Comp"
        finally:
            tftacademy_live.CACHE_PATH = original_path

    # apply_to_game_data should mutate the live META_COMPS list in place,
    # then we put the original data back.
    snapshot = list(game_data.META_COMPS)
    snapshot_lookup = dict(game_data.META_COMPS_BY_CARRY)

    test_comps = [
        {"name": "Cache Test", "tier": "A", "trend": "new",
         "carry": "Kindred", "match_traits": ["N.O.V.A."]},
    ]
    tftacademy_live.apply_to_game_data(test_comps)
    assert len(game_data.META_COMPS) == 1
    assert game_data.META_COMPS[0]["name"] == "Cache Test"
    assert "Kindred" in game_data.META_COMPS_BY_CARRY

    # Restore so other tests are unaffected
    tftacademy_live.apply_to_game_data(snapshot)
    game_data.META_COMPS_BY_CARRY.clear()
    game_data.META_COMPS_BY_CARRY.update(snapshot_lookup)

    return "cache write+read OK, in-place apply OK"


def test_augments_parser():
    """parse_augments_payload flattens the API payload correctly."""
    from tftacademy_live import parse_augments_payload

    payload = {
        "augments_tierlists": [
            {"augmenttier": 1, "stage": "All",
             "tier": {"S": ["TFT_Augment_GoodOne"], "B": ["TFT_Augment_MehOne"]}},
            {"augmenttier": 1, "stage": "2-1",
             "tier": {"A": ["TFT_Augment_GoodOne"]}},
            {"augmenttier": 3, "stage": "4-2",
             "tier": {"S": ["TFT_Augment_BigPrismatic"],
                      "Z": ["TFT_Augment_BadTierLetter"]}},   # invalid tier dropped
        ]
    }
    names = {"TFT_Augment_GoodOne": "Good One"}
    entries = parse_augments_payload(payload, names)
    by_api = {e["api_name"]: e for e in entries}

    # GoodOne + MehOne + BigPrismatic; BadTierLetter dropped (invalid tier)
    assert len(entries) == 3, f"expected 3 entries, got {len(entries)}"
    assert "TFT_Augment_BadTierLetter" not in by_api
    good = by_api["TFT_Augment_GoodOne"]
    assert good["name"] == "Good One"
    assert good["slot"] == "silver"
    assert good["ratings"] == {"All": "S", "2-1": "A"}
    # Name derived from apiName when the mapping doesn't know it
    big = by_api["TFT_Augment_BigPrismatic"]
    assert big["name"] == "Big Prismatic", f"got: {big['name']}"
    assert big["slot"] == "prismatic"
    return f"{len(entries)} entries, stage ratings + slot + name fallback OK"


def test_augments_apply_and_fuzzy():
    """apply_augments_to_game_data merges live + curated; fuzzy lookup works."""
    import tftacademy_live
    import game_data
    from game_data import find_augment_rating

    snapshot = dict(game_data.AUGMENT_RATINGS)
    seed_snapshot = tftacademy_live._curated_augment_seed
    try:
        live = [
            {"api_name": "TFT_Augment_HeroicGrabBag", "name": "Heroic Grab Bag",
             "slot": "gold", "ratings": {"All": "B"}},
            {"api_name": "TFT_Augment_BrandNew", "name": "Brand New Augment",
             "slot": "silver", "ratings": {"All": "S", "2-1": "A"}},
        ]
        tftacademy_live.apply_augments_to_game_data(live)

        # Live rating applied, curated tip preserved
        hgb = game_data.AUGMENT_RATINGS["Heroic Grab Bag"]
        assert hgb["rating"] == "B", f"live rating should win, got {hgb['rating']}"
        assert "components" in hgb["tip"], "curated tip should be preserved"
        # New augment got a generated tip
        new = game_data.AUGMENT_RATINGS["Brand New Augment"]
        assert new["rating"] == "S"
        assert "TFT Academy" in new["tip"]
        # Curated-only entries survive the apply
        assert "Aura Farming" in game_data.AUGMENT_RATINGS

        # Fuzzy lookup: normalized + close-match against OCR noise
        name, data = find_augment_rating("HEROIC GRAB BAG")
        assert name == "Heroic Grab Bag"
        name, data = find_augment_rating("Heroic Grab 8ag")
        assert name == "Heroic Grab Bag", f"fuzzy failed: {name}"
        name, data = find_augment_rating("Totally Unknown Augment")
        assert name is None and data is None
    finally:
        game_data.AUGMENT_RATINGS.clear()
        game_data.AUGMENT_RATINGS.update(snapshot)
        tftacademy_live._curated_augment_seed = seed_snapshot

    return "live+curated merge OK, fuzzy lookup OK"


def _dark_star_board():
    """Board leaning Dark Star — shared by the context-scoring tests."""
    from game_state import DetectedChampion
    return [
        DetectedChampion(name="Jhin",        star_level=2, board_row=0, board_col=6),
        DetectedChampion(name="Kai'Sa",      star_level=2, board_row=0, board_col=5),
        DetectedChampion(name="Karma",       star_level=1, board_row=0, board_col=0),
        DetectedChampion(name="Lissandra",   star_level=2, board_row=3, board_col=3),
        DetectedChampion(name="Mordekaiser", star_level=2, board_row=3, board_col=2),
    ]


def test_context_comp_scoring():
    """Held components and taken augments boost the comps they fit."""
    from synergy import detect_comp_direction, compute_active_synergies
    from game_data import META_COMPS

    board = _dark_star_board()
    synergies = compute_active_synergies(board)

    base = detect_comp_direction(synergies, board)
    assert base, "board should match at least one comp"
    primary = base[0]
    assert primary.board_layout, "META_COMPS-backed suggestion should carry a board layout"
    assert all("board_index" in u and "name" in u for u in primary.board_layout)

    # Augment context: take an augment the primary comp recommends → its
    # score must rise and a context note must appear.
    meta = next((c for c in META_COMPS if c["name"] == (primary.tftacademy_name or primary.name)), None)
    rec_augments = [a["name"] for a in ((meta or {}).get("detail") or {}).get("augments", [])]
    assert rec_augments, "primary comp should have recommended augments in the cache"

    boosted = detect_comp_direction(
        synergies, board, selected_augments=[rec_augments[0]]
    )
    boosted_primary = next((s for s in boosted if s.name == primary.name), None)
    assert boosted_primary is not None
    assert boosted_primary.match_score > primary.match_score, \
        f"augment match should boost score: {boosted_primary.match_score} vs {primary.match_score}"
    assert boosted_primary.context_notes, "context note should explain the boost"

    # Item context: hold components that build the comp's items → score rises.
    item_boosted = detect_comp_direction(
        synergies, board,
        component_ids=["recurve_bow", "sparring_gloves", "bf_sword"],
    )
    item_primary = next((s for s in item_boosted if s.name == primary.name), None)
    assert item_primary is not None and item_primary.match_score >= primary.match_score

    # Slammed-item context: ONE completed carry item on our units must pull
    # the comp harder than fielding one more of the comp's units — items
    # are commitments, units are interchangeable.
    carry_name = (meta.get("detail") or {}).get("main_champion", {}).get("name")
    carry_unit = next(
        u for u in (meta["detail"]["units"]) if u["name"] == carry_name
    )
    carry_item_names = [i["name"] for i in carry_unit["items"]]
    assert carry_item_names, "carry should have build items in the cache"

    slammed_board = [c.model_copy(deep=True) for c in board]
    slam_target = next(c for c in slammed_board if c.name == carry_name)
    slam_target.items = carry_item_names[:1]
    slammed = detect_comp_direction(compute_active_synergies(slammed_board), slammed_board)
    slammed_primary = next((s for s in slammed if s.name == primary.name), None)
    assert slammed_primary is not None
    slam_gain = slammed_primary.match_score - primary.match_score
    assert any("build" in n for n in slammed_primary.context_notes), \
        f"slammed-item note expected, got {slammed_primary.context_notes}"

    # Adding one more comp unit instead (a missing unit from the layout):
    extra_name = next(
        u["name"] for u in meta["detail"]["units"]
        if u["name"] not in {c.name for c in board}
    )
    from game_state import DetectedChampion as DC
    unit_board = board + [DC(name=extra_name, star_level=1, board_row=1, board_col=1)]
    with_unit = detect_comp_direction(compute_active_synergies(unit_board), unit_board)
    unit_primary = next((s for s in with_unit if s.name == primary.name), None)
    unit_gain = (unit_primary.match_score - primary.match_score) if unit_primary else 0.0

    assert slam_gain > unit_gain, (
        f"one slammed carry item should outweigh one extra unit "
        f"(+{slam_gain:.3f} vs +{unit_gain:.3f})"
    )


def test_tactics_units_and_board_power():
    """tactics.tools stats parse and affect explainable board strength."""
    import json
    from coach import Coach
    from game_data import CHAMPIONS
    from game_state import DetectedChampion, GamePhase, GameState
    import tactics_live

    rows = {}
    for index, name in enumerate(list(CHAMPIONS)[:45]):
        api_name = "TFT17_" + "".join(ch for ch in name if ch.isalnum())
        rows[api_name] = {
            "count": 10_000 + index,
            "place": 4.5,
            "top4": 50.0,
            "won": 12.5,
            "starPlace": 3.8,
        }
    payload = {
        "props": {"pageProps": {"statsData": {
            "totalEntries": 500_000,
            "lastUpdated": 123456,
            "units": rows,
        }}}
    }
    html = (
        "<title>TFT Units Stats Patch 17.7</title>"
        f'<script id="__NEXT_DATA__" type="application/json">'
        f"{json.dumps(payload)}</script>"
    )
    parsed = tactics_live.parse_units_html(html)
    assert parsed["patch"] == "17.7"
    assert len(parsed["units"]) >= 40

    old_units = tactics_live._unit_stats
    old_meta = tactics_live._snapshot_meta
    try:
        parsed["units"]["Aatrox"].update(
            avg_place=3.7, top4=64.0, win=20.0
        )
        parsed["units"]["Briar"].update(
            avg_place=5.3, top4=36.0, win=6.0
        )
        tactics_live.apply_snapshot(parsed)
        coach = Coach()

        def score(name, *, items=None, augments=None, board=True):
            champion = DetectedChampion(
                name=name,
                star_level=2,
                items=items or [],
                board_row=0 if board else None,
                board_col=0 if board else None,
            )
            state = GameState(
                phase=GamePhase.PLANNING,
                stage="2-5",
                level=4,
                board_champions=[champion] if board else [],
                bench_champions=[] if board else [champion],
                selected_augments=augments or [],
            )
            return coach.analyze(state)

        strong = score("Aatrox")
        weak = score("Briar")
        geared = score(
            "Aatrox",
            items=["Warmog's Armor", "Gargoyle Stoneplate"],
            augments=["Heroic Grab Bag"],
        )
        estimated = score("Aatrox", board=False)

        assert strong.board_power_breakdown.meta_bonus > 0
        assert weak.board_power_breakdown.meta_bonus < 0
        assert strong.board_power > weak.board_power
        assert geared.board_power > strong.board_power
        assert geared.board_power_breakdown.item_bonus > 0
        assert geared.board_power_breakdown.augment_bonus > 0
        assert estimated.board_power_breakdown.source == "roster_estimate"
        assert estimated.board_power_breakdown.confidence < 0.7
        assert strong.board_power_breakdown.meta_patch == "17.7"
        assert strong.board_power_breakdown.meta_games_analyzed == 500_000
        assert strong.board_power_breakdown.meta_rank == "Diamond+"
    finally:
        tactics_live._unit_stats = old_units
        tactics_live._snapshot_meta = old_meta

    return "live schema, cost-relative meta, items/augments, roster fallback OK"


def test_items_tierlist():
    """Items tier-list parsing + apply: freshest list per kind wins, live
    tiers reach both LIVE_ITEM_TIERS and ITEM_RECIPES, radiants/artifacts
    resolve, and the shred/burn flag audit holds."""
    import game_data
    from tftacademy_live import parse_items_payload, apply_items_to_game_data

    payload = {"items_tierlists": [
        {"type": "craftables", "updated": "2026-01-01",
         "tier": {"S": ["TFT_Item_FrozenHeart"], "A": [], "B": [], "C": []}},
        {"type": "craftables", "updated": "2026-07-01",
         "tier": {"S": ["TFT_Item_Deathblade"], "B": ["TFT_Item_GuinsoosRageblade"]}},
        {"type": "ornns", "updated": "2026-07-01",
         "tier": {"S": ["TFT_Item_Artifact_Dawncore"]}},
        {"type": "radiants", "updated": "2026-07-01",
         "tier": {"A": ["TFT5_Item_ThiefsGlovesRadiant"]}},
        {"type": "emblems", "updated": "2026-07-01", "tier": {"S": []}},
    ]}
    names = {
        "TFT_Item_Deathblade": "Deathblade",
        "TFT_Item_GuinsoosRageblade": "Guinsoo's Rageblade",
        "TFT_Item_Artifact_Dawncore": "Dawncore",
        "TFT5_Item_ThiefsGlovesRadiant": "Rascal's Gloves",
    }
    entries = parse_items_payload(payload, names)
    by_name = {e["name"]: e for e in entries}
    assert "Deathblade" in by_name and "Frozen Heart" not in " ".join(by_name), \
        "freshest craftables list should win over the stale one"
    assert by_name["Dawncore"]["kind"] == "artifact"
    assert by_name["Rascal's Gloves"]["kind"] == "radiant"
    assert by_name["Guinsoo's Rageblade"]["tier"] == "B"

    # Apply (snapshot + restore so later tests see pristine data).
    live_before = dict(game_data.LIVE_ITEM_TIERS)
    tiers_before = {r["name"]: r["tier"] for r in game_data.ITEM_RECIPES}
    try:
        apply_items_to_game_data(entries)
        assert game_data.find_item_tier("Deathblade") == ("S", "craftable")
        assert game_data.find_item_tier("Dawncore") == ("S", "artifact")
        assert game_data.find_item_tier("Rascal's Gloves") == ("A", "radiant")
        assert game_data.find_item_tier("NotAnItem") == (None, None)
        guinsoo = next(r for r in game_data.ITEM_RECIPES
                       if r["name"] == "Guinsoo's Rageblade")
        assert guinsoo["tier"] == "B", "live tier should reach ITEM_RECIPES"
    finally:
        game_data.LIVE_ITEM_TIERS.clear()
        game_data.LIVE_ITEM_TIERS.update(live_before)
        for r in game_data.ITEM_RECIPES:
            r["tier"] = tiers_before[r["name"]]

    # Flag audit: shred = resist reduction, burn = Grievous/DoT — these are
    # mechanical facts, so lock them (Striker's Flail was wrongly burn).
    assert game_data.SHRED_ITEMS == {"Evenshroud", "Ionic Spark",
                                     "Last Whisper", "Void Staff"}, game_data.SHRED_ITEMS
    assert game_data.BURN_ITEMS == {"Morellonomicon", "Red Buff",
                                    "Sunfire Cape"}, game_data.BURN_ITEMS
    return f"{len(entries)} entries: freshest-wins, kinds, apply+restore, flag audit OK"


def test_comp_aware_item_advice():
    """Slam advice puts the comp's own build items first and names the
    unit that holds them — not just generic tier ratings."""
    from game_state import GameState, GamePhase
    from coach import Coach, _norm_item_name
    from synergy import compute_active_synergies, detect_comp_direction, _RECIPE_BY_NAME

    board = _dark_star_board()
    primary = detect_comp_direction(compute_active_synergies(board), board)[0]
    assert primary.board_layout, "primary comp should carry a board layout"

    # A craftable build item from the comp, and the unit that wants it
    # (carries — most build items — checked first, mirroring the coach).
    unit_name = item_name = recipe = None
    for unit in sorted(primary.board_layout, key=lambda u: -len(u.get("items") or [])):
        for iname in unit.get("items") or []:
            if _RECIPE_BY_NAME.get(iname):
                unit_name, item_name, recipe = unit["name"], iname, _RECIPE_BY_NAME[iname]
                break
        if item_name:
            break
    assert item_name, "comp should have at least one craftable build item"

    state = GameState(
        phase=GamePhase.PLANNING, stage="3-2", player_hp=80, gold=30,
        board_champions=board, component_ids=list(recipe),
    )
    advice = Coach().analyze(state)
    assert advice.slam_recommendations, "components should produce a recommendation"

    top = advice.slam_recommendations[0]
    assert top.for_comp, (
        f"comp build item should rank first, got {top.item_name}: {top.reason}"
    )
    assert _norm_item_name(top.item_name) == _norm_item_name(item_name)
    assert top.for_unit == unit_name and unit_name in top.reason, (
        f"reason should name the holder ({unit_name}): {top.reason}"
    )
    return f"top slam = {top.item_name} for {top.for_unit} in {top.for_comp}"

    return (
        f"layout={len(primary.board_layout)} units, "
        f"augment +{boosted_primary.match_score - primary.match_score:.3f}, "
        f"slammed item +{slam_gain:.3f} > extra unit +{unit_gain:.3f}"
    )


def test_augment_pick_context():
    """Offered augments are ranked in context and the best is flagged."""
    from game_state import GameState, GamePhase, DetectedAugment
    from synergy import detect_comp_direction, compute_active_synergies
    from coach import Coach
    from game_data import META_COMPS

    board = _dark_star_board()
    synergies = compute_active_synergies(board)
    primary = detect_comp_direction(synergies, board)[0]
    meta = next((c for c in META_COMPS if c["name"] == (primary.tftacademy_name or primary.name)), None)
    rec_aug = ((meta or {}).get("detail") or {}).get("augments", [])[0]["name"]

    state = GameState(
        phase=GamePhase.AUGMENT_SELECT,
        stage="4-2",
        player_hp=70,
        gold=30,
        board_champions=board,
        augment_options=[
            DetectedAugment(name=rec_aug,          tier="Gold", slot_index=0),
            DetectedAugment(name="Pandora's Items", tier="Gold", slot_index=1),
            DetectedAugment(name="Nonexistent Augment Xyz", tier="Gold", slot_index=2),
        ],
    )
    advice = Coach().analyze(state)
    assert len(advice.augment_ratings) == 3
    picks = [r for r in advice.augment_ratings if r["pick"]]
    assert len(picks) == 1, f"exactly one pick expected, got {len(picks)}"

    rec_entry = next(r for r in advice.augment_ratings if r["slot_index"] == 0)
    assert any("Recommended for" in reason for reason in rec_entry["reasons"]), \
        f"comp-recommended augment should carry a reason, got {rec_entry['reasons']}"
    assert rec_entry["context_score"] > next(
        r for r in advice.augment_ratings if r["slot_index"] == 2
    )["context_score"]
    assert any(t.startswith("Augment pick:") for t in advice.tips)

    return f"pick={picks[0]['name']} (score {picks[0]['context_score']}), reasons OK"


def test_roster_tracker():
    """Shop-diff purchase tracking: buys, rerolls, star-ups, guards, reset."""
    from roster import RosterTracker
    from game_state import GameState, GamePhase

    def state(stage, shop, gold):
        return GameState(phase=GamePhase.PLANNING, stage=stage,
                         shop_units=shop, gold=gold)

    r = RosterTracker()
    # First frame establishes the baseline — no purchases yet.
    r.update(state("2-1", ["Gwen", "Riven", "Poppy", "Lulu", "Gnar"], 30))
    assert r.total_purchases == 0

    # A vanished card is only PENDING — it confirms on the next readable
    # frame where it's still gone (transient occlusions cancel instead).
    r.update(state("2-1", ["Gwen", None, "Poppy", "Lulu", "Gnar"], 27))
    assert r.total_purchases == 0, "vanish should be pending, not counted yet"

    # Next frame: Riven still gone → confirmed. Two more vanish → pending.
    r.update(state("2-1", [None, None, "Poppy", None, "Gnar"], 22))
    assert r.total_purchases == 1

    # Next frame: Gwen + Lulu still gone → confirmed (double buy).
    r.update(state("2-1", [None, None, "Poppy", None, "Gnar"], 22))
    assert r.total_purchases == 3

    # Hover glitch: card unreadable for one frame while gold drops (bought
    # XP), then it reappears → cancelled, no phantom purchase.
    r.update(state("2-1", [None, None, None, None, "Gnar"], 18))
    r.update(state("2-1", [None, None, "Poppy", None, "Gnar"], 18))
    assert r.total_purchases == 3, "reappearing card must cancel the pending buy"

    # Full reroll (all slots replaced) → no purchases inferred.
    r.update(state("2-2", ["Sona", "Shen", "Zed", "Akali", "Fiora"], 16))
    assert r.total_purchases == 3

    # Shop obscured (carousel — all slots unreadable) → frame skipped,
    # baseline survives.
    r.update(state("2-2", [None, None, None, None, None], 16))
    r.update(state("2-2", ["Sona", "Shen", "Zed", "Akali", "Fiora"], 16))
    assert r.total_purchases == 3, "obscured shop must not count as purchases"

    # Card vanished but gold did NOT drop → misread, never even pending.
    r.update(state("2-2", [None, "Shen", "Zed", "Akali", "Fiora"], 16))
    r.update(state("2-2", [None, "Shen", "Zed", "Akali", "Fiora"], 16))
    assert r.total_purchases == 3, "no gold drop → no purchase"

    # Fresh roster: buy Gwen 3 times → one 2-star (with confirm frames).
    r.reset()
    r.update(state("2-3", ["Gwen", "Shen", "Zed", "Akali", "Gwen"], 20))
    r.update(state("2-3", [None, "Shen", "Zed", "Akali", None], 14))   # both pending
    r.update(state("2-3", [None, "Shen", "Zed", "Akali", None], 14))   # confirmed x2
    r.update(state("2-3", ["Gwen", "Shen", "Zed", "Akali", None], 14)) # new Gwen appears
    r.update(state("2-3", [None, "Shen", "Zed", "Akali", None], 11))   # pending
    r.update(state("2-3", [None, "Shen", "Zed", "Akali", None], 11))   # confirmed
    units = r.owned_units()
    gwens = [u for u in units if u.name == "Gwen"]
    assert len(gwens) == 1 and gwens[0].star_level == 2, \
        f"3 Gwen copies should combine to one 2-star, got {[(u.name, u.star_level) for u in gwens]}"

    # A single backwards-stage frame (OCR misread) must NOT reset...
    r.update(state("1-5", ["Poppy", "Gnar", "Lulu", "Sona", "Shen"], 30))
    assert r.total_purchases == 3, "single stage misread must not wipe the roster"
    r.update(state("2-3", [None, "Shen", "Zed", "Akali", None], 11))
    # ...but two consecutive backwards frames = a real new game → reset.
    r.update(state("1-1", ["Poppy", "Gnar", "Lulu", "Sona", "Shen"], 0))
    r.update(state("1-1", ["Poppy", "Gnar", "Lulu", "Sona", "Shen"], 0))
    assert r.total_purchases == 0, "two consecutive regressions should reset"

    # UNREADABLE gold (-1 sentinel) must not block purchases — the guard
    # only applies when both frames' gold genuinely read. The server must
    # feed the roster RAW readings for this to hold: patching failed reads
    # with the previous frame's gold makes it look readable-but-unchanged
    # and silently vetoes every buy (which starved the crop harvester).
    r.reset()
    r.update(state("2-1", ["Gwen", "Riven", "Poppy", "Lulu", "Gnar"], -1))
    r.update(state("2-1", ["Gwen", None, "Poppy", "Lulu", "Gnar"], -1))
    r.update(state("2-1", ["Gwen", None, "Poppy", "Lulu", "Gnar"], -1))
    assert r.total_purchases == 1, "unreadable gold must not veto a real buy"

    return ("pending-confirm buys, hover cancel, occlusion/gold guards, "
            "unreadable-gold buy, star-up, debounced reset OK")


def test_bench_harvester():
    """Purchases pair with newly-occupied bench slots and save labeled crops."""
    import tempfile
    import numpy as np
    from pathlib import Path
    from harvest import BenchHarvester
    from config import GameROIs

    h, w = 720, 1280
    rois = GameROIs()
    bx, by, bw, bh = rois.champion_bench.to_pixels(w, h)
    slot_w = bw // 9

    def frame(occupied_slots):
        f = np.full((h, w, 3), 40, dtype=np.uint8)   # flat = empty bench
        rng = np.random.default_rng(7)
        for s in occupied_slots:
            noise = rng.integers(0, 255, (bh, slot_w, 3), dtype=np.uint8)
            f[by:by + bh, bx + s * slot_w: bx + (s + 1) * slot_w] = noise
        return f

    with tempfile.TemporaryDirectory() as tmp:
        # Tracking disabled here — this section tests purchase pairing.
        hv = BenchHarvester(out_dir=Path(tmp), track_interval=10_000)

        # Baseline frame — nothing saved even with a purchase (no previous
        # occupancy to diff against).
        assert hv.process(frame([]), ["Gwen"]) == 0

        # Purchases confirm one frame after the unit lands: slot 0 fills,
        # then the confirmed purchase arrives → the 2-frame window still
        # pairs it.
        assert hv.process(frame([0]), []) == 0
        assert hv.process(frame([0]), ["Gwen"]) == 1
        saved = list(Path(tmp).rglob("*.png"))
        assert len(saved) == 1 and "Gwen" in str(saved[0].parent)

        # No purchase → occupancy change alone saves nothing (unit moved).
        assert hv.process(frame([0, 1]), []) == 0
        assert hv.process(frame([0, 1]), []) == 0   # age slot 1 out of the window

        # Double buy confirming immediately → two new slots, two crops.
        assert hv.process(frame([0, 1, 2, 3]), ["Riven", "Poppy"]) == 2
        names = {p.parent.name for p in Path(tmp).rglob("*.png")}
        assert names == {"Gwen", "Riven", "Poppy"}, names

        # Ambiguous frame: more new slots than purchases → skip entirely
        # (a wrong label is worse than a missing sample).
        assert hv.process(frame([0, 1, 2, 3, 4, 5]), ["Zed"]) == 0

        # imwrite failing (returns False, never raises) must not count as
        # a save — it used to leave empty champion folders behind.
        import harvest as harvest_mod
        orig_imwrite = harvest_mod.cv2.imwrite
        harvest_mod.cv2.imwrite = lambda *a, **k: False
        try:
            before = hv.saved_count
            noisy = np.random.default_rng(3).integers(0, 255, (20, 20, 3), dtype=np.uint8)
            assert hv._save(noisy, "Ghost", 0) is False
            assert hv.saved_count == before, "failed imwrite counted as saved"
        finally:
            harvest_mod.cv2.imwrite = orig_imwrite

    # A vacated slot is a large visual change too, but must never be
    # labeled as the purchased champion (the corrupt empty Aatrox batch).
    with tempfile.TemporaryDirectory() as tmp:
        hv = BenchHarvester(out_dir=Path(tmp))
        assert hv.process(frame([0]), []) == 0
        assert hv.process(frame([]), ["Aatrox"]) == 0
        assert not list(Path(tmp).rglob("*.png"))

    # A unit can be moved or sold in the same capture window as a purchase.
    # Filter the vacated slot before deciding whether pairing is ambiguous.
    with tempfile.TemporaryDirectory() as tmp:
        hv = BenchHarvester(out_dir=Path(tmp), track_interval=10_000)
        assert hv.process(frame([0]), []) == 0
        assert hv.process(frame([1]), ["Gwen"]) == 1
        saved = list(Path(tmp).rglob("*.png"))
        assert len(saved) == 1 and saved[0].parent.name == "Gwen"

    # Preserve the exact landing frame while the roster waits one readable
    # frame to confirm the shop-card vanish. Confirmation can arrive after
    # the unit has already been moved without losing the labeled crop.
    with tempfile.TemporaryDirectory() as tmp:
        hv = BenchHarvester(out_dir=Path(tmp), track_interval=10_000)
        assert hv.process(frame([]), []) == 0
        assert hv.process(frame([0]), [], ["Gwen"]) == 0
        assert hv.process(frame([]), ["Gwen"], []) == 1
        saved = list(Path(tmp).rglob("*.png"))
        assert len(saved) == 1 and saved[0].parent.name == "Gwen"

    # Continuous tracking: a confirmed slot keeps yielding crops while it
    # stays visually stable, up to the cap; any abrupt change stops it.
    with tempfile.TemporaryDirectory() as tmp:
        hv = BenchHarvester(out_dir=Path(tmp), track_interval=2, track_max_saves=4)
        assert hv.process(frame([]), []) == 0           # baseline
        assert hv.process(frame([0]), []) == 0          # unit lands
        assert hv.process(frame([0]), ["Gwen"]) == 1    # confirm → crop 1, tracked
        got = [hv.process(frame([0]), []) for _ in range(6)]
        assert got == [0, 1, 0, 1, 0, 1], got           # every 2nd frame until cap
        assert hv.process(frame([0]), []) == 0          # cap (4) reached → untracked
        assert len(list(Path(tmp).rglob("*.png"))) == 4

    with tempfile.TemporaryDirectory() as tmp:
        hv = BenchHarvester(out_dir=Path(tmp), track_interval=2, track_max_saves=99)
        hv.process(frame([]), [])
        hv.process(frame([0]), [])
        assert hv.process(frame([0]), ["Zed"]) == 1
        assert hv.process(frame([]), []) == 0           # unit moved away → untrack
        got = [hv.process(frame([0]), []) for _ in range(4)]
        assert got == [0, 0, 0, 0], f"untracked slot kept saving: {got}"
        assert len(list(Path(tmp).rglob("*.png"))) == 1

    # A transient write/quality failure must not consume the tracking cap;
    # retry the next stable frame instead of silently losing the sample.
    with tempfile.TemporaryDirectory() as tmp:
        hv = BenchHarvester(out_dir=Path(tmp), track_interval=1, track_max_saves=2)
        hv.process(frame([]), [])
        hv.process(frame([0]), [])
        assert hv.process(frame([0]), ["Gwen"]) == 1
        original_save = hv._save
        attempts = 0

        def fail_once(crop, name, slot):
            nonlocal attempts
            attempts += 1
            return attempts > 1 and original_save(crop, name, slot)

        hv._save = fail_once
        assert hv.process(frame([0]), []) == 0
        assert hv.process(frame([0]), []) == 1
        assert len(list(Path(tmp).rglob("*.png"))) == 2

    return ("pairing guards + pending landing cache OK, vacated-slot filtering OK, "
            "imwrite-fail OK, tracking: interval+cap+retry OK, stop-on-change OK")


def test_window_picker():
    """Capture must only target the game or the League client — exact
    titles. Substring matching latched onto editors/terminals with this
    'TFT-COACH' project open and browser tabs mentioning League."""
    from capture import WindowFinder

    class W:
        def __init__(self, title, minimized=False, w=2560, h=1440):
            self.title, self.isMinimized = title, minimized
            self.width, self.height = w, h

    ide = W("TFT-COACH - Visual Studio Code")
    term = W("Windows PowerShell - python backend/main.py TFT-COACH")
    browser = W("best TFT comps - League of Legends guide - Chrome")
    launcher = W("League of Legends")
    game = W("League of Legends (TM) Client")

    pick = WindowFinder._pick_game_window
    assert pick([ide, term, browser, launcher, game]) is game
    assert pick([ide, browser, launcher]) is None, "launcher is not a game frame"
    assert pick([ide, browser, launcher], include_launcher=True) is launcher
    assert pick([ide, term, browser]) is None, "no game/client → capture nothing"
    assert pick([W("League of Legends (TM) Client", minimized=True), launcher]) is None
    assert pick(
        [W("League of Legends (TM) Client", minimized=True), launcher],
        include_launcher=True,
    ) is launcher
    assert pick([W("  League of Legends (TM) Client ")]) is not None
    assert pick([]) is None
    return "game only by default, optional launcher lookup, unrelated windows ignored"


def test_classifier_data_pipeline():
    """Training-data discovery and stratified split (no torch required)."""
    import tempfile
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    from train_classifier import discover_dataset, split_dataset

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Gwen and the _empty background class have enough crops; Zed
        # doesn't; stray files are ignored.
        for name, n in [("Gwen", 25), ("_empty", 30), ("Zed", 3)]:
            d = root / name
            d.mkdir()
            for i in range(n):
                (d / f"crop_{i}.png").write_bytes(b"png")
        (root / "notes.txt").write_text("ignore me")

        usable, skipped = discover_dataset(root, min_crops=20)
        assert set(usable) == {"Gwen", "_empty"}, usable.keys()
        assert skipped == {"Zed": 3}, skipped

        train, val, labels = split_dataset(usable, val_fraction=0.15)
        assert labels == ["Gwen", "_empty"]  # sorted, background kept
        assert len(train) + len(val) == 55
        # Every class keeps at least one val sample; splits are disjoint.
        val_classes = {lbl for _, lbl in val}
        assert val_classes == {0, 1}, "each class needs a val sample"
        assert not set(p for p, _ in train) & set(p for p, _ in val)

        # Missing directory → empty, not an error.
        usable, skipped = discover_dataset(root / "nope", min_crops=20)
        assert usable == {} and skipped == {}

    return "discovery, min-crop gate, stratified split OK"


def test_unit_classifier_fallback():
    """Without a trained model the classifier is a safe no-op; the
    preprocessing contract produces correct batches."""
    import numpy as np
    from pathlib import Path
    from unit_classifier import UnitClassifier, preprocess

    clf = UnitClassifier(
        model_path=Path("_nonexistent.onnx"), meta_path=Path("_nonexistent.json")
    )
    assert clf.available is False
    crops = [np.zeros((30, 20, 3), dtype=np.uint8)] * 3
    assert clf.classify_batch(crops) == [(None, 0.0)] * 3
    assert clf.classify_batch([]) == []

    # preprocess: BGR crops of any size → normalized NCHW float32 batch.
    mean = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
    std = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)
    batch = preprocess(
        [np.full((260, 160, 3), 128, dtype=np.uint8),
         np.full((40, 90, 3), 128, dtype=np.uint8)],
        input_size=128, mean=mean, std=std,
    )
    assert batch.shape == (2, 3, 128, 128) and batch.dtype == np.float32
    # 128/255 normalized: channel means must match the formula exactly.
    expected = (128 / 255.0 - mean.ravel()) / std.ravel()
    got = batch.mean(axis=(0, 2, 3))
    assert np.allclose(got, expected, atol=1e-5), (got, expected)

    return "no-model no-op OK, preprocess contract OK"


def test_shop_buy_calls():
    """The coach flags shop cards worth buying: 2-star completions first,
    then comp units we're missing."""
    from game_state import GameState, GamePhase, DetectedChampion
    from coach import Coach

    board = _dark_star_board()
    pre = Coach().analyze(GameState(
        phase=GamePhase.PLANNING, stage="3-5", player_hp=80, gold=30,
        board_champions=board,
    ))
    assert pre.comp_suggestions, "board should produce a comp direction"
    missing = pre.comp_suggestions[0].missing_units
    assert missing, "primary comp should have missing units"

    bench = [DetectedChampion(name="Poppy"), DetectedChampion(name="Poppy")]
    advice = Coach().analyze(GameState(
        phase=GamePhase.PLANNING, stage="3-5", player_hp=80, gold=30,
        board_champions=board, bench_champions=bench,
        shop_units=[missing[0], "Poppy", None, None, None],
    ))
    names = [a["name"] for a in advice.shop_actions]
    assert "Poppy" in names and missing[0] in names, f"buy calls missing: {names}"
    top = advice.shop_actions[0]
    assert top["name"] == "Poppy" and "2-star" in top["reason"], \
        f"pair completion should rank first: {top}"
    assert any(t.startswith("Shop: buy") for t in advice.tips)
    return f"calls: {[(a['name'], a['priority']) for a in advice.shop_actions]}"


def test_tempo_tips():
    """Level-tempo and rolldown tips fire in the right spots."""
    from game_state import GameState, GamePhase
    from coach import Coach

    # Level 5 at stage 4 with gold = behind the curve.
    advice = Coach().analyze(GameState(
        phase=GamePhase.PLANNING, stage="4-1", player_hp=80, gold=30, level=5,
    ))
    assert any("behind tempo" in t for t in advice.tips), advice.tips

    # Bleeding, rich, no committed comp = roll down.
    advice = Coach().analyze(GameState(
        phase=GamePhase.PLANNING, stage="4-1", player_hp=35, gold=30, level=7,
    ))
    assert any("roll this round" in t.lower() for t in advice.tips), advice.tips

    # Healthy and on-curve: neither tip.
    advice = Coach().analyze(GameState(
        phase=GamePhase.PLANNING, stage="4-1", player_hp=80, gold=30, level=8,
    ))
    assert not any("behind tempo" in t or "roll this round" in t for t in advice.tips)
    return "behind-tempo, rolldown, quiet-when-fine OK"


def test_stage_aware_augment_pick():
    """Augment offers are scored with the CURRENT stage's rating bucket,
    not the overall one — an econ augment is S at 2-1 and C at 4-2."""
    import game_data
    from game_state import GameState, GamePhase, DetectedAugment
    from coach import Coach

    seed = dict(game_data.AUGMENT_RATINGS)
    try:
        game_data.AUGMENT_RATINGS.clear()
        game_data.AUGMENT_RATINGS.update({
            "Early Bloomer": {"rating": "C", "tip": "t", "slot": "gold",
                              "stage_ratings": {"All": "C", "2-1": "S", "4-2": "C"}},
            "Late Bloomer": {"rating": "S", "tip": "t", "slot": "gold",
                             "stage_ratings": {"All": "S", "2-1": "C", "4-2": "S"}},
        })

        def pick_at(stage):
            advice = Coach().analyze(GameState(
                phase=GamePhase.AUGMENT_SELECT, stage=stage, player_hp=90, gold=10,
                augment_options=[
                    DetectedAugment(name="Early Bloomer", tier="?", slot_index=0),
                    DetectedAugment(name="Late Bloomer", tier="?", slot_index=1),
                ],
            ))
            best = next(r for r in advice.augment_ratings if r["pick"])
            return best["name"], {r["name"]: r["rating"] for r in advice.augment_ratings}

        name21, ratings21 = pick_at("2-1")
        assert name21 == "Early Bloomer", (name21, ratings21)
        assert ratings21["Early Bloomer"] == "S", "displayed rating should be the stage bucket"
        name42, _ = pick_at("4-2")
        assert name42 == "Late Bloomer", name42
    finally:
        game_data.AUGMENT_RATINGS.clear()
        game_data.AUGMENT_RATINGS.update(seed)
    return "2-1 picks the early augment, 4-2 the late one"


def test_econ_and_damage_tips():
    """Interest-breakpoint nudge (which upgrades always beat) and
    loss-damage forecast."""
    from game_state import GameState, GamePhase, DetectedChampion
    from coach import Coach

    tips = Coach().analyze(GameState(
        phase=GamePhase.PLANNING, stage="3-2", player_hp=80, gold=48, level=6,
    )).tips
    assert any("hold" in t and "interest breakpoint" in t for t in tips), tips

    tips = Coach().analyze(GameState(
        phase=GamePhase.PLANNING, stage="3-2", player_hp=80, gold=44, level=6,
    )).tips
    assert not any("interest breakpoint" in t for t in tips), "6 gold away — quiet"

    # A pair copy in the shop beats the breakpoint: the tip must say BUY,
    # never advise holding past an upgrade.
    board = _dark_star_board()
    bench = [DetectedChampion(name="Poppy"), DetectedChampion(name="Poppy")]
    tips = Coach().analyze(GameState(
        phase=GamePhase.PLANNING, stage="3-2", player_hp=80, gold=48, level=6,
        board_champions=board, bench_champions=bench,
        shop_units=["Poppy", None, None, None, None],
    )).tips
    buy_tip = next((t for t in tips if "interest breakpoint" in t), "")
    assert buy_tip.startswith("Buy Poppy"), f"upgrade should beat interest: {tips}"

    tips = Coach().analyze(GameState(
        phase=GamePhase.PLANNING, stage="4-3", player_hp=20, gold=10, level=8,
    )).tips
    assert any("must-win" in t for t in tips), tips
    return "hold nudge, quiet-when-far, pair-beats-interest, loss forecast OK"


def test_component_detection_real_frames():
    """Basic components detect on real frames (local diagnose captures;
    requires the fetched component templates — both skipped when absent).
    Set 17's stylized component art (Chain Vest is a blue spiked pauldron)
    was mistaken for non-components once; the scores say otherwise."""
    import cv2
    from pathlib import Path
    from detector import Detector, TemplateStore

    t = TemplateStore(); t.load()
    if not t.component_templates:
        return "no component templates on disk — skipped"
    debug_dir = Path(__file__).parent / "_debug"
    cases = [
        ("diagnose_20260717_183943.png", {"chain_vest", "recurve_bow"}),
        ("diagnose_20260717_184036.png", {"chain_vest", "bf_sword", "recurve_bow"}),
    ]
    checked = 0
    for name, expected in cases:
        path = debug_dir / name
        if not path.exists():
            continue
        d = Detector(t)
        got = {c.component_id for c in d._detect_components(cv2.imread(str(path)))}
        assert expected <= got, f"{name}: {got} missing {expected - got}"
        checked += 1
    if not checked:
        return "no diagnose frames present — skipped"
    return f"{checked} frames detect their components"


def test_held_item_detection():
    """Completed items on the item bench are template-matched (change-gated
    scan); unknown icons are rejected rather than guessed."""
    import cv2
    import numpy as np
    from detector import Detector, TemplateStore
    from config import GameROIs

    t = TemplateStore(); t.load()
    if not t.item_templates:
        return "no item templates on disk — skipped"
    d = Detector(t)

    frame = np.full((1440, 2560, 3), 25, dtype=np.uint8)
    x, y, rw, rh = GameROIs().item_bench.to_pixels(2560, 1440)
    size = int(2560 * 0.0165)
    names = [n for n in ("Deathblade", "Sunfire Cape") if n in t.item_templates]
    assert names, "expected craftable templates on disk"
    for i, nm in enumerate(names):
        icon = cv2.resize(t.item_templates[nm], (size, size), interpolation=cv2.INTER_AREA)
        sy = y + 20 + i * int(rh / 10)
        frame[sy:sy + size, x + 8:x + 8 + size] = icon

    got = d._detect_held_items(frame)
    assert got == names, f"held items {got} != {names}"
    assert d._detect_held_items(frame) == names, "cached path should agree"

    empty = Detector(t)
    assert empty._detect_held_items(np.full((1440, 2560, 3), 25, dtype=np.uint8)) == []
    return f"detected {got}, cache + empty OK"


def test_lobby_hp_real_frames():
    """All players' HP read in standings order from real frames (local
    diagnose captures; skipped when absent)."""
    import cv2
    from pathlib import Path
    from detector import Detector, TemplateStore, _merge_lobby_reads
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception:
        return "tesseract unavailable — skipped"

    assert _merge_lobby_reads(
        [96, 95, 93, 93, 81, 78], [100, 96, 95, 81, 78], 95
    ) == [100, 96, 95, 93, 93, 81, 78]
    assert _merge_lobby_reads(
        [98, 18, 17, 0, 0, 0], [69, 41, 28], 28
    ) == [69, 41, 28, 18, 17, 0, 0, 0]

    debug_dir = Path(__file__).parent / "_debug"
    # Unreadable rows remain explicit -1 slots so the frontend always
    # renders all eight players without calling them eliminated.
    cases = [
        ("diagnose_20260713_151422.png", [44, 30, 17, 16, 12, 0, 0, 0]),
        ("diagnose_20260711_023339.png", [62, 60, 39, 20, 5, 4, 0, 0]),
        ("diagnose_20260713_145641.png", [94, 88, 87, 86, 71, 69, 62, -1]),
        # One tied 97 is unreadable and remains an explicit unknown slot.
        ("diagnose_20260718_015501.png", [100, 100, 100, 100, 97, 95, 95, -1]),
    ]
    t = TemplateStore(); t.load()
    checked = 0
    for name, truth in cases:
        path = debug_dir / name
        if not path.exists():
            continue
        d = Detector(t)
        got = d._read_lobby_hp(cv2.imread(str(path)))
        assert got == truth, f"{name}: lobby {got} != {truth}"
        checked += 1
    anchored_cases = [
        ("diagnose_20260718_205941.png", 28, [69, 41, 28, -1, -1, -1, -1, -1]),
        ("diagnose_20260718_210036.png", 28, [69, 43, 28, -1, -1, -1, -1, -1]),
        ("diagnose_20260718_210237.png", 10, [69, 34, 10, 0, 0, 0, 0, 0]),
    ]
    for name, own_hp, truth in anchored_cases:
        path = debug_dir / name
        if not path.exists():
            continue
        d = Detector(t)
        d._last_hp = own_hp
        got = d._read_lobby_hp(cv2.imread(str(path)))
        assert got == truth, f"{name}: anchored lobby {got} != {truth}"
    if not checked:
        return "no diagnose frames present — skipped"
    return f"{checked} frames read in standings order"


def test_standings_tips():
    """Lobby-aware coaching: lowest-alive alarm, bleed-out patience,
    top-4 push — and silence without lobby data."""
    from game_state import GameState, GamePhase
    from coach import Coach

    def tips_for(hp, lobby):
        return Coach().analyze(GameState(
            phase=GamePhase.PLANNING, stage="4-5", player_hp=hp, gold=50,
            level=8, lobby_hp=lobby,
        )).tips

    tips = tips_for(12, [80, 55, 40, 33, 12, 0, 0, 0])
    assert any("LOWEST HP" in t for t in tips), tips

    tips = tips_for(80, [80, 55, 40, 12, 9, 0, 0, 0])
    assert any("bleed out" in t for t in tips), tips

    tips = tips_for(55, [80, 55, 40, 33, 20, 0, 0, 0])
    assert any("top 4" in t for t in tips), tips

    tips = tips_for(55, [])
    assert not any("LOWEST HP" in t or "bleed out" in t or "top 4" in t for t in tips)
    return "lowest-alive, bleed-out, top-4 push, no-data silence OK"


def test_augment_ocr_real_frame():
    """Augment titles read exactly from a real selection screen (local-only
    diagnose frame; skipped when absent)."""
    import cv2
    from pathlib import Path
    frame_path = Path(__file__).parent / "_debug" / "diagnose_20260714_185217.png"
    if not frame_path.exists():
        return "diagnose frame not present — skipped"
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception:
        return "tesseract unavailable — skipped"

    import tftacademy_live
    tftacademy_live.init_from_cache()   # OCR reads resolve via the augment DB
    from detector import Detector, TemplateStore
    t = TemplateStore(); t.load()
    d = Detector(t)
    got = [a.name for a in d._detect_augments(cv2.imread(str(frame_path)))]
    expected = ["Birthday Present", "Heart of the Swarm", "Band of Thieves II"]
    assert got == expected, f"augment OCR mismatch: {got} != {expected}"
    return f"3 titles exact: {got}"


def test_hp_real_frames():
    """Our HP reads correctly from real frames — the enlarged-row finder
    plus the strip fallbacks. Diagnose frames are local-only; test them
    when present."""
    import cv2
    from pathlib import Path
    from detector import Detector, TemplateStore
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception:
        return "tesseract unavailable — skipped"

    cases = [(Path(__file__).parent / "fixtures" / "tft_screenshot.png", 46)]
    debug_dir = Path(__file__).parent / "_debug"
    for name, truth in [
        ("diagnose_20260713_145641.png", 71),   # merged-glyph + icon-junk frame
        ("diagnose_20260713_151422.png", 17),   # hollow glyphs + spell glow
        ("diagnose_20260711_023339.png", 5),    # big single digit, near-death
        ("diagnose_20260718_015501.png", 97),   # leading digit over gold frame art
        ("diagnose_20260718_205941.png", 28),
        ("diagnose_20260718_210036.png", 28),
        ("diagnose_20260718_210237.png", 10),
    ]:
        if (debug_dir / name).exists():
            cases.append((debug_dir / name, truth))

    t = TemplateStore(); t.load()
    checked = []
    for path, truth in cases:
        if not path.exists():
            continue
        d = Detector(t)   # fresh anchor per frame
        got = d._ocr_player_hp(cv2.imread(str(path)))
        assert got == truth, f"{path.name}: HP {got} != {truth}"
        checked.append(truth)
    return f"{len(checked)} frames correct: {checked}"


def test_shop_ocr_real_frame():
    """Shop card names read correctly from the real fixture screenshot."""
    from game_data import find_champion_name
    assert find_champion_name("Nunu & Willump") == "Nunu"
    import cv2
    from pathlib import Path
    fixture = Path(__file__).parent / "fixtures" / "tft_screenshot.png"
    if not fixture.exists():
        return "fixture missing — skipped"
    # detector's import sets the Windows tesseract path fallback — import
    # it before probing for the binary.
    from detector import Detector, TemplateStore
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception:
        return "tesseract unavailable — skipped"
    t = TemplateStore()
    t.load()
    d = Detector(t)
    frame = cv2.imread(str(fixture))
    got = d._detect_shop(frame)
    expected = ["Gwen", None, "Rek'Sai", "Miss Fortune", "Ornn"]
    assert got == expected, f"shop OCR mismatch: {got} != {expected}"
    return f"5 slots read: {got}"


def test_pinned_comp():
    """Pinning a comp surfaces it first and supercharges its augments."""
    from synergy import detect_comp_direction, compute_active_synergies
    from game_state import GameState, GamePhase, DetectedAugment
    from coach import Coach

    board = _dark_star_board()
    synergies = compute_active_synergies(board)
    base = detect_comp_direction(synergies, board)
    assert len(base) >= 2, "need multiple suggestions to test pinning"

    # Pin the SECOND suggestion — it must jump to the front, flagged.
    target = base[1]
    pin_name = target.tftacademy_name or target.name
    pinned = detect_comp_direction(synergies, board, pinned_comp=pin_name)
    assert pinned[0].is_pinned and pinned[0].is_primary, \
        f"pinned comp should lead: {[(s.name, s.is_pinned) for s in pinned]}"
    assert (pinned[0].tftacademy_name or pinned[0].name) == pin_name

    # Augment offers recommended by the pinned comp carry the locked-comp
    # reason and outrank the same augment without a pin.
    rec_augments = pinned[0].recommended_augments
    if not rec_augments:
        return f"pin ordering OK ({pin_name}); no augments in cache to test boost"

    def analyze(pin):
        state = GameState(
            phase=GamePhase.AUGMENT_SELECT, stage="3-2", player_hp=80, gold=30,
            board_champions=board, pinned_comp=pin,
            augment_options=[
                DetectedAugment(name=rec_augments[0], tier="Gold", slot_index=0),
            ],
        )
        return Coach().analyze(state).augment_ratings[0]

    with_pin = analyze(pin_name)
    without_pin = analyze(None)
    assert with_pin["context_score"] > without_pin["context_score"], \
        "pinned comp's augment should score higher than unpinned"
    assert any("locked" in r for r in with_pin["reasons"]), with_pin["reasons"]

    return (
        f"pin ordering OK ({pin_name}), augment boost "
        f"{without_pin['context_score']} → {with_pin['context_score']}"
    )


def test_set_autodetect():
    """Current-set detection from CDragon payload and comp slugs."""
    from tftacademy_live import current_set_number, CURRENT_SET_NUMBER

    # From comp slugs — newest set wins, malformed slugs ignored
    cache = {"comps": [
        {"slug": "set-17-dark-star"},
        {"slug": "set-18-new-hotness"},
        {"slug": "not-a-set-slug"},
        {"slug": None},
    ]}
    assert current_set_number(cache) == 18
    # No usable slugs → fallback constant
    assert current_set_number({"comps": []}) == CURRENT_SET_NUMBER

    # From CDragon sets (fetch_templates needs cv2-free import? it imports
    # config + game_data only, safe here)
    from fetch_templates import detect_current_set, select_cdragon_item, CURRENT_SET
    cdragon = {"sets": {
        "16": {"traits": [{"name": "Old"}]},
        "17": {"traits": [{"name": "New"}]},
        "18": {"traits": []},           # future set with no traits yet
        "bogus": {"traits": [{"name": "X"}]},
    }}
    assert detect_current_set(cdragon) == "17"
    assert detect_current_set({"sets": {}}) == CURRENT_SET

    old_emblem = {"apiName": "TFT3_Item_DarkStarEmblem", "icon": "/Set3/DarkStar.tex"}
    live_emblem = {"apiName": "TFT17_Item_DarkStarEmblem", "icon": "/Set17/DarkStar.tex"}
    assert select_cdragon_item(
        [live_emblem, old_emblem], current_set="17", is_craftable=False
    ) is live_emblem
    encounter = {"apiName": "TFT11_Encounter_GiveItem", "composition": []}
    standard = {"apiName": "TFT_Item_GiantSlayer", "composition": ["a", "b"]}
    assert select_cdragon_item(
        [encounter, standard], current_set="17", is_craftable=True
    ) is standard

    return "slug-derived set OK, CDragon-derived set OK, fallbacks OK"


def test_tftacademy_debounce():
    """refresh_async returns early when called inside the debounce window."""
    import asyncio
    import tftacademy_live

    async def _run():
        # Reset the debounce state and pretend a refresh just happened.
        tftacademy_live._last_refresh_attempt_at = 0.0
        # First call with debounce of 9999s and force=False, but state is
        # 'never refreshed' — so it WILL try to fetch. Mock it out by
        # short-circuiting via force=False and a huge debounce after we
        # set the attempt time manually.
        import time
        tftacademy_live._last_refresh_attempt_at = time.monotonic()

        result = await tftacademy_live.refresh_async(
            force=False, debounce_seconds=9999,
        )
        assert result["checked"] is False, \
            f"Should be debounced (not checked), got: {result}"
        assert result["error"] is None
        return result

    result = asyncio.run(_run())
    return f"debounced OK (checked={result['checked']})"


def test_tactics_periodic_refresh():
    """Only one recurring tactics.tools updater can run per process."""
    import asyncio
    import tactics_live

    async def _run():
        first = tactics_live.schedule_periodic_refresh(
            initial_delay_seconds=3600,
            interval_seconds=3600,
        )
        second = tactics_live.schedule_periodic_refresh(
            initial_delay_seconds=3600,
            interval_seconds=3600,
        )
        assert first is second
        first.cancel()
        try:
            await first
        except asyncio.CancelledError:
            pass
        await asyncio.sleep(0)
        assert tactics_live._periodic_task is None

    asyncio.run(_run())
    return "singleton schedule and cancellation OK"


def test_websockets_import():
    import websockets
    return f"v{websockets.__version__}"


def test_pydantic_import():
    import pydantic
    return f"v{pydantic.__version__}"


def test_demo_server_init():
    from demo_server import DemoServer
    server = DemoServer()
    assert server.is_running is False
    assert server._game is None
    return "DemoServer initializes OK"


async def _test_demo_server_connection():
    """Start the demo server briefly and verify a client can connect."""
    from demo_server import DemoServer
    import websockets as ws

    server = DemoServer()
    server_task = None

    try:
        # Start server in background
        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(0.5)  # Let it spin up

        # Connect a client
        async with ws.connect("ws://localhost:8765") as client:
            # On connect the server pushes static game_data + demo_info
            # payloads first, then starts broadcasting game_state. Read
            # until the first game_state arrives.
            seen_types = []
            for _ in range(10):
                raw = await asyncio.wait_for(client.recv(), timeout=5.0)
                msg = json.loads(raw)
                seen_types.append(msg["type"])
                if msg["type"] == "game_state":
                    break
            else:
                raise AssertionError(f"No game_state within 10 messages: {seen_types}")

            assert "game_data" in seen_types, \
                f"Server should push game_data on connect, saw: {seen_types}"
            assert "data" in msg
            data = msg["data"]
            assert "stage" in data
            assert "player_hp" in data
            return f"received {seen_types} → stage={data['stage']} hp={data['player_hp']}"

    finally:
        server.is_running = False
        if server_task:
            server_task.cancel()
            try:
                await server_task
            except (asyncio.CancelledError, Exception):
                pass


def test_demo_websocket():
    return asyncio.run(_test_demo_server_connection())


def test_cv_deps():
    """Check if CV dependencies are available (optional for demo mode)."""
    missing = []
    for mod in ["cv2", "numpy", "mss"]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)

    if missing:
        warn("CV dependencies", f"Not installed: {', '.join(missing)} (only needed for live mode)")
        return None
    import cv2
    import numpy
    return f"opencv={cv2.__version__}, numpy={numpy.__version__}"


def test_tesseract():
    """Check if Tesseract OCR is available."""
    hint = {
        "win32": "winget install UB-Mannheim.TesseractOCR",
        "darwin": "brew install tesseract",
    }.get(sys.platform, "sudo apt install tesseract-ocr")
    try:
        # detector.py points pytesseract at the standard Windows install
        # location when the binary isn't on PATH — reuse that setup.
        import detector  # noqa: F401
        import pytesseract
        version = pytesseract.get_tesseract_version()
        return f"v{version}"
    except ImportError:
        warn("Tesseract", "pytesseract not installed (only needed for live mode)")
        return None
    except Exception:
        warn("Tesseract", f"pytesseract installed but tesseract binary not found ({hint})")
        return None


# ── Run ───────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  TFT COACH — System Tests")
    print("=" * 60)

    print("\n[Core modules]")
    test("Config", test_config)
    test("Game State model", test_game_state)
    test("Coaching engine", test_coach)
    test("Coach edge cases", test_coach_edge_cases)
    test("Active synergies", test_active_synergies)
    test("Comp detection", test_comp_detection)
    test("Coach comp direction", test_coach_comp_direction)
    test("TFT Academy enrichment", test_tftacademy_enrichment)
    test("TFT Academy parser", test_tftacademy_parser)
    test("TFT Academy cache roundtrip", test_tftacademy_cache_roundtrip)
    test("Augments parser", test_augments_parser)
    test("Augments apply + fuzzy lookup", test_augments_apply_and_fuzzy)
    test("Set auto-detection", test_set_autodetect)
    test("Context comp scoring", test_context_comp_scoring)
    test("Board strength + tactics.tools", test_tactics_units_and_board_power)
    test("Periodic tactics.tools refresh", test_tactics_periodic_refresh)
    test("Items tier list", test_items_tierlist)
    test("Comp-aware item advice", test_comp_aware_item_advice)
    test("Shop buy calls", test_shop_buy_calls)
    test("Tempo tips", test_tempo_tips)
    test("Augment pick context", test_augment_pick_context)
    test("Pinned comp", test_pinned_comp)
    test("Roster tracker", test_roster_tracker)
    test("Bench harvester", test_bench_harvester)
    test("Window picker", test_window_picker)
    test("Classifier data pipeline", test_classifier_data_pipeline)
    test("Unit classifier fallback", test_unit_classifier_fallback)
    test("Augment OCR (real frame)", test_augment_ocr_real_frame)
    test("HP OCR (real frames)", test_hp_real_frames)
    test("Component detection (real frames)", test_component_detection_real_frames)
    test("Held item detection", test_held_item_detection)
    test("Lobby HP (real frames)", test_lobby_hp_real_frames)
    test("Standings tips", test_standings_tips)
    test("Stage-aware augment pick", test_stage_aware_augment_pick)
    test("Econ + damage tips", test_econ_and_damage_tips)
    test("Shop OCR (real frame)", test_shop_ocr_real_frame)
    test("TFT Academy debounce", test_tftacademy_debounce)

    print("\n[Dependencies]")
    test("websockets", test_websockets_import)
    test("pydantic", test_pydantic_import)

    print("\n[Demo mode]")
    test("Demo server init", test_demo_server_init)
    test("Demo WebSocket round-trip", test_demo_websocket)

    print("\n[Live mode (optional)]")
    result = test_cv_deps()
    if result:
        test("CV dependencies", lambda: result)
    test_tesseract()

    # Summary
    print("\n" + "=" * 60)
    passes = sum(1 for r in results if r[0] == PASS)
    fails = sum(1 for r in results if r[0] == FAIL)
    warns = sum(1 for r in results if r[0] == WARN)
    print(f"  Results: {passes} passed, {fails} failed, {warns} warnings")

    if fails == 0:
        print("  🎉 All critical tests passed! You're good to go.")
        print()
        print("  Start the app:")
        print("    Terminal 1: python3 backend/main.py --demo")
        print("    Terminal 2: cd frontend && npm install && npm run dev")
        print("    Browser:    http://localhost:5173")
    else:
        print("  Fix the failures above before running the app.")

    print("=" * 60)
    return 1 if fails > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
