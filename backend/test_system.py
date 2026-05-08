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

    # Sanity: we actually loaded TFT Academy data
    assert len(META_COMPS) >= 20, f"META_COMPS too small: {len(META_COMPS)}"
    assert any(c["name"] == "Dark Star" and c["tier"] == "S" for c in META_COMPS), \
        "Dark Star S-tier entry from TFT Academy should be present"

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

    assert primary.tftacademy_tier == "S", \
        f"Dark Star should be S-tier, got: {primary.tftacademy_tier}"
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
    #  - patch header in two formats
    #  - tier labels in 3 forms (S-Tier text, data-tier attr, "tier":"S" JSON)
    #  - comp links pointing at /tierlist/comps/<set>/<slug>
    sample = """
    <html><body>
      <h1>Patch 17.2B  -  Last Updated 4 hours ago</h1>
      <section><h2>S-Tier</h2>
        <a href="/tierlist/comps/set17/yi-marawlers">Yi Marawlers</a>
        <a href="/tierlist/comps/set17/dark-star">Dark Star</a>
      </section>
      <section><h2>A-Tier</h2>
        <a href="/tierlist/comps/set17/fountain-lulu">Fountain Lulu</a>
        <a href="/tierlist/comps/set17/tf-reroll">TF Reroll</a>
      </section>
      <section><h2>B-Tier</h2>
        <a href="/tierlist/comps/set17/voyager-crab">Voyager Crab</a>
      </section>
      <!-- duplicate to verify dedupe -->
      <a href="/tierlist/comps/set17/dark-star">Dark Star</a>
    </body></html>
    """

    assert parse_patch(sample) == "17.2b", f"got: {parse_patch(sample)}"

    entries = parse_comps(sample)
    by_name = {e["name"]: e["tier"] for e in entries}
    assert by_name.get("Yi Marawlers") == "S"
    assert by_name.get("Dark Star")    == "S"
    assert by_name.get("Fountain Lulu") == "A"
    assert by_name.get("TF Reroll")    == "A"
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
            # Wait for first game state message
            raw = await asyncio.wait_for(client.recv(), timeout=3.0)
            msg = json.loads(raw)
            assert msg["type"] == "game_state", f"Expected game_state, got {msg['type']}"
            assert "data" in msg
            data = msg["data"]
            assert "stage" in data
            assert "player_hp" in data
            return f"received stage={data['stage']} hp={data['player_hp']}"

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
    try:
        import pytesseract
        version = pytesseract.get_tesseract_version()
        return f"v{version}"
    except ImportError:
        warn("Tesseract", "pytesseract not installed (only needed for live mode)")
        return None
    except Exception:
        warn("Tesseract", "pytesseract installed but tesseract binary not found (brew install tesseract)")
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
