#!/usr/bin/env python3
"""Operator CLI: send a mission to the orchestrator over A2A (via the gateway).

Usage: run_mission.py [--verify] [mission text]
  --verify: assert the mission completes AND the world shows P-42 delivered
            to STAGING (M4 acceptance).
"""

import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parents[1]))
from agents.a2a import a2a_send  # noqa: E402

GATEWAY = "http://localhost:3000"
WORLD = "http://localhost:8085"
DEFAULT_MISSION = (
    "Move pallet P-42 from rack A3 to staging. Keep robots out of any zone with a human in it."
)


async def main() -> int:
    args = [a for a in sys.argv[1:] if a != "--verify"]
    verify = "--verify" in sys.argv
    mission = " ".join(args) or DEFAULT_MISSION

    tokens = json.load(open(Path(__file__).parents[1] / "gateway/jwt/tokens.json"))

    async with httpx.AsyncClient() as c:
        await c.post(f"{WORLD}/reset")

    print(f"mission: {mission}")
    t0 = time.monotonic()
    reply = await a2a_send(
        f"{GATEWAY}/a2a/orchestrator", mission, token=tokens["orchestrator"], timeout=600.0
    )
    elapsed = time.monotonic() - t0
    print(f"orchestrator reply ({elapsed:.1f}s): {reply}")

    result = {}
    try:
        start, end = reply.find("{"), reply.rfind("}")
        result = json.loads(reply[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        pass

    if not verify:
        return 0

    if result.get("status") != "done":
        print("VERIFY FAIL: mission did not complete")
        return 1
    async with httpx.AsyncClient() as c:
        state = (await c.get(f"{WORLD}/state")).json()
    if "P-42" not in state.get("delivered", []):
        print(f"VERIFY FAIL: P-42 not delivered (world says: {state.get('delivered')})")
        return 1
    print("VERIFY PASS: mission done and P-42 physically delivered to STAGING")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
