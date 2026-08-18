"""M1 acceptance: world + robots + reflex tier + degraded-mode state machine.

Runs against live services (compose or local): world :8080, amr-1 :8101,
arm-1 :8103. Direct-to-robot MCP here on purpose — gateway governance is M3;
this milestone proves the machine layer beneath it.
"""

import asyncio
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

WORLD = os.environ.get("WORLD_URL", "http://localhost:8085")
AMR1 = os.environ.get("AMR1_URL", "http://localhost:8101")
ARM1 = os.environ.get("ARM1_URL", "http://localhost:8103")
ROOT = Path(__file__).parents[2]


def compose(*args: str) -> None:
    """Best-effort compose control; no-op if compose/container absent (bare-process runs)."""
    subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True)

pytestmark = pytest.mark.asyncio


async def mcp_tools(url: str) -> list[str]:
    async with streamablehttp_client(f"{url}/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return [t.name for t in (await s.list_tools()).tools]


async def mcp_call(url: str, name: str, args: dict) -> str:
    async with streamablehttp_client(f"{url}/mcp") as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(name, args)
            return res.content[0].text


async def beat(*robots: str) -> None:
    """Play the cognition role: without heartbeats robots SAFE_IDLE by design."""
    async with httpx.AsyncClient() as c:
        for url in robots:
            await c.post(f"{url}/heartbeat", json={})


@pytest.fixture(autouse=True)
async def reset_world():
    async with httpx.AsyncClient() as c:
        await c.post(f"{WORLD}/reset")
    await beat(AMR1, ARM1)
    await asyncio.sleep(0.5)  # sensor refresh + SM check interval
    yield


async def test_amr_tool_surface_is_complete():
    """Un-gated view: ALL tools exist on the robot, dangerous ones included.
    (The gateway subtracting from this list is the M3 demo.)"""
    tools = await mcp_tools(AMR1)
    assert set(tools) >= {
        "get_pose",
        "get_battery",
        "navigate_to",
        "dock",
        "emergency_stop",
        "set_speed_limit",
        "disable_safety_stop",
    }
    arm_tools = await mcp_tools(ARM1)
    assert set(arm_tools) >= {
        "get_state",
        "pick",
        "place",
        "home",
        "emergency_stop",
        "set_torque_limit",
        "calibrate",
    }


async def keep_alive(*robots: str):
    """Background heartbeats while a blocking motion command runs."""
    while True:
        await beat(*robots)
        await asyncio.sleep(0.5)


async def test_navigate_mutates_world():
    """navigate_to blocks until arrival (cognition reasons about completed
    actions); world autoticks in compose, so we just keep cognition alive."""
    hb = asyncio.ensure_future(keep_alive(AMR1))
    ticker = None

    async def tick_loop():
        async with httpx.AsyncClient() as c:
            while True:
                await c.post(f"{WORLD}/tick")
                await asyncio.sleep(0.2)

    try:
        async with httpx.AsyncClient() as c:
            autotick = (await c.get(f"{WORLD}/state")).json()["tick"]
            await asyncio.sleep(1.2)
            autotick = (await c.get(f"{WORLD}/state")).json()["tick"] - autotick
        if autotick == 0:  # CI/local runs may disable the autoticker
            ticker = asyncio.ensure_future(tick_loop())
        result = await mcp_call(AMR1, "navigate_to", {"zone": "C"})
        assert '"ok": true' in result.lower(), result
        async with httpx.AsyncClient() as c:
            state = (await c.get(f"{WORLD}/state")).json()
        assert state["robots"]["amr-1"]["zone"] == "C"
    finally:
        hb.cancel()
        if ticker:
            ticker.cancel()


async def test_reflex_refuses_human_zone_in_process():
    """Human enters zone C -> navigate_to(C) refused by the ROBOT, not the world."""
    async with httpx.AsyncClient() as c:
        await c.post(f"{WORLD}/events/human", json={"zone": "C", "present": True})
    await asyncio.sleep(0.7)  # sensor refresh interval is 0.2s
    result = await mcp_call(AMR1, "navigate_to", {"zone": "C"})
    assert "reflex" in result and "human" in result
    async with httpx.AsyncClient() as c:
        state = (await c.get(f"{WORLD}/state")).json()
        assert state["robots"]["amr-1"]["target"] is None  # command never reached the world
        await c.post(f"{WORLD}/events/human", json={"zone": "C", "present": False})


async def test_estop_is_fast_and_in_process():
    result = await mcp_call(AMR1, "emergency_stop", {})
    assert '"ok": true' in result.lower()
    import json

    engaged_us = json.loads(result)["engaged_in_us"]
    assert engaged_us < 10_000, f"e-stop took {engaged_us}us, SLO is 10ms"
    # recover for later tests
    async with httpx.AsyncClient() as c:
        await c.post(f"{AMR1}/heartbeat", json={"clear_estop": True})


async def test_heartbeat_loss_reaches_safe_idle_within_slo():
    """No heartbeats -> SAFE_IDLE. Detection bounded by heartbeat timeout (2s)
    + transition ≤500ms; we assert the transition tail, not the timeout.

    In the full stack amr-1's cognition agent heartbeats it continuously, so we
    stop that agent for the duration to observe genuine heartbeat loss."""
    compose("stop", "amr-1-cognition")
    try:
        await _assert_heartbeat_loss_safe_idle()
    finally:
        compose("start", "amr-1-cognition")


async def _assert_heartbeat_loss_safe_idle():
    async with httpx.AsyncClient() as c:
        # establish cognition, then go silent
        await c.post(f"{AMR1}/heartbeat", json={})
        deadline = time.monotonic() + 2.0 + 1.0  # timeout + SLO margin
        mode = "ACTIVE"
        while time.monotonic() < deadline:
            mode = (await c.get(f"{AMR1}/healthz")).json()["mode"]
            if mode == "SAFE_IDLE":
                break
            await asyncio.sleep(0.05)
        assert mode == "SAFE_IDLE", f"robot stuck in {mode} after heartbeat loss"

        # transition latency receipt: FINISH_CURRENT_MOTION -> SAFE_IDLE ≤500ms
        health = (await c.get(f"{AMR1}/healthz")).json()
        ts = {t["to"]: t["t"] for t in health["transitions"][-5:]}
        if "FINISH_CURRENT_MOTION" in ts and "SAFE_IDLE" in ts:
            assert (ts["SAFE_IDLE"] - ts["FINISH_CURRENT_MOTION"]) <= 0.5

        # heartbeat restored -> auto-resume
        await c.post(f"{AMR1}/heartbeat", json={})
        await asyncio.sleep(0.3)
        assert (await c.get(f"{AMR1}/healthz")).json()["mode"] == "ACTIVE"


async def test_pick_and_place_flow():
    tools = await mcp_tools(ARM1)
    assert "pick" in tools
    result = await mcp_call(ARM1, "pick", {"pallet_id": "P-42"})
    assert '"ok": true' in result.lower() or "holding" in result
    result = await mcp_call(ARM1, "place", {"location": "amr-1"})
    assert '"ok": true' in result.lower()
    async with httpx.AsyncClient() as c:
        state = (await c.get(f"{WORLD}/state")).json()
    assert state["robots"]["amr-1"]["carrying"] == "P-42"
