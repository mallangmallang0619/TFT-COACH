"""
One-shot WS smoke test for the demo server's new command surface.
Connects, collects the first few messages, then sends each new
command and verifies the server responds without crashing.
"""

import asyncio
import json
import sys

import websockets

URL = "ws://localhost:8765"


async def collect_for(ws, seconds: float) -> list[dict]:
    out: list[dict] = []
    end = asyncio.get_event_loop().time() + seconds
    while True:
        timeout = end - asyncio.get_event_loop().time()
        if timeout <= 0:
            break
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            break
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            pass
    return out


async def main() -> int:
    try:
        ws = await asyncio.wait_for(websockets.connect(URL), timeout=4.0)
    except Exception as e:
        print(f"CONNECT FAILED: {e}")
        return 1

    async with ws:
        # 1. First few messages should include game_data + demo_info
        initial = await collect_for(ws, 1.5)
        types = [m.get("type") for m in initial]
        print(f"initial messages: {types[:6]}")
        if "game_data" not in types:
            print("FAIL: no game_data on connect")
            return 2
        if "demo_info" not in types:
            print("FAIL: no demo_info on connect")
            return 2
        demo_info = next(m for m in initial if m.get("type") == "demo_info")
        print(f"  scenarios: {len(demo_info.get('scenarios', []))}")
        print(f"  paused:    {demo_info.get('paused')}")
        print(f"  tick_ms:   {demo_info.get('tick_ms')}")

        # 2. Send each new command, watch for crashes
        commands = [
            {"type": "pause", "paused": True},
            {"type": "set_hp", "hp": 42},
            {"type": "set_gold", "gold": 77},
            {"type": "set_level", "level": 7},
            {"type": "override_stage", "stage": "4-2"},
            {"type": "override_components",
             "components": ["bf_sword", "bf_sword", "tear", "recurve_bow"]},
            {"type": "set_tick_speed", "tick_ms": 250},
            {"type": "force_phase", "phase": "augment_select"},
            {"type": "step"},
            {"type": "restart_game", "scenario": 2},
            {"type": "pause", "paused": False},
        ]
        for cmd in commands:
            await ws.send(json.dumps(cmd))

        # 3. Collect output after the commands and look for game_state
        # that reflects our overrides
        after = await collect_for(ws, 2.0)
        state_msgs = [m for m in after if m.get("type") == "game_state"]
        if not state_msgs:
            print("FAIL: no game_state after commands")
            return 3

        last = state_msgs[-1].get("data", {})
        print(f"\nafter commands — last state:")
        print(f"  phase:     {last.get('phase')}")
        print(f"  stage:     {last.get('stage')}")
        print(f"  hp/gold/lvl: {last.get('player_hp')}/{last.get('gold')}/{last.get('level')}")
        print(f"  components: {last.get('component_ids')}")

        # demo_info should also reflect the new scenario + tick
        info_msgs = [m for m in after if m.get("type") == "demo_info"]
        if info_msgs:
            final_info = info_msgs[-1]
            print(f"  current_scenario: {final_info.get('current_scenario')}")
            print(f"  tick_ms: {final_info.get('tick_ms')}")

    print("\nPASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
