"""M4 acceptance: fleet coordination under failure (Failover + Predictability).

Scenarios:
  * happy path — mission completes, pallet physically delivered
  * dead cognition agent — its robot SAFE_IDLEs, orchestrator reassigns the
    task to the other AMR, mission still completes
  * human event mid-route — motion pauses (physics + reflex), resumes when
    the zone clears, mission still completes
"""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parents[2]))
from agents.a2a import a2a_send  # noqa: E402

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:3000")
WORLD = os.environ.get("WORLD_URL", "http://localhost:8085")
ROOT = os.path.join(os.path.dirname(__file__), "../..")
TOKENS = json.load(open(os.path.join(ROOT, "gateway/jwt/tokens.json")))
MISSION = (
    "Move pallet P-42 from rack A3 to staging. Keep robots out of any zone with a human in it."
)

pytestmark = pytest.mark.asyncio


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=ROOT, check=True, capture_output=True)


async def world_state() -> dict:
    async with httpx.AsyncClient() as c:
        return (await c.get(f"{WORLD}/state")).json()


async def run_mission() -> dict:
    reply = await a2a_send(
        f"{GATEWAY}/a2a/orchestrator", MISSION, token=TOKENS["orchestrator"], timeout=600.0
    )
    start, end = reply.find("{"), reply.rfind("}")
    return json.loads(reply[start : end + 1])


@pytest.fixture(autouse=True)
async def fresh_world():
    async with httpx.AsyncClient() as c:
        await c.post(f"{WORLD}/reset")
    await asyncio.sleep(0.5)
    yield


async def test_mission_happy_path():
    result = await run_mission()
    assert result["status"] == "done", result
    state = await world_state()
    assert "P-42" in state["delivered"]


async def test_dead_cognition_safe_idles_and_reassigns():
    """Kill amr-1's brain: amr-1 must SAFE_IDLE; amr-2 must finish the job."""
    compose("stop", "amr-1-cognition")
    try:
        # SAFE_IDLE within heartbeat timeout (2s) + SM transition SLO
        await asyncio.sleep(3.0)
        async with httpx.AsyncClient() as c:
            mode = (await c.get("http://localhost:8101/healthz")).json()["mode"]
        assert mode == "SAFE_IDLE", f"amr-1 should be SAFE_IDLE without cognition, is {mode}"

        result = await run_mission()
        assert result["status"] == "done", result
        replans = [e for e in result["log"] if "replan" in e]
        assert replans, "mission succeeded without reassignment?!"
        state = await world_state()
        assert "P-42" in state["delivered"]
        assert state["robots"]["amr-2"]["zone"] == "STAGING"  # amr-2 carried it home
    finally:
        compose("start", "amr-1-cognition")
        await asyncio.sleep(2.0)


async def test_human_event_pauses_then_mission_completes():
    """Human enters zone C (on the route to STAGING): motion halts on physics
    AND reflex; when the human leaves, the fleet finishes the mission."""
    async with httpx.AsyncClient() as c:
        await c.post(f"{WORLD}/events/human", json={"zone": "C", "present": True})

    mission_task = asyncio.ensure_future(run_mission())
    try:
        await asyncio.sleep(6.0)
        state = await world_state()
        assert "P-42" not in state["delivered"], "delivered THROUGH an occupied zone!"
        assert all(r["zone"] != "C" for r in state["robots"].values() if r["type"] == "amr"), (
            "an AMR entered the occupied zone"
        )

        async with httpx.AsyncClient() as c:
            await c.post(f"{WORLD}/events/human", json={"zone": "C", "present": False})
        result = await asyncio.wait_for(mission_task, timeout=120)
        assert result["status"] == "done", result
        state = await world_state()
        assert "P-42" in state["delivered"]
    finally:
        if not mission_task.done():
            mission_task.cancel()
        async with httpx.AsyncClient() as c:
            await c.post(f"{WORLD}/events/human", json={"zone": "C", "present": False})
