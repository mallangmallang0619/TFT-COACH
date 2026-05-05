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
