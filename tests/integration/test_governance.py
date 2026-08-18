"""M3 acceptance: MCP governance through the gateway (Safety + Predictability).

The contract under test (gateway/config.yaml IS the action envelope):
  * gated tools are INVISIBLE (filtered from tools/list), not merely refused
  * forced calls to gated tools are denied per identity
  * the orchestrator sees telemetry tools only
  * maintenance sees and can use everything
  * every tool call/denial lands in the audit log with identity + tool + args
  * anonymous traffic is rejected outright (strict JWT)
"""

import json
import os
import subprocess

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

GATEWAY = os.environ.get("GATEWAY_URL", "http://localhost:3000")
TOKENS = json.load(open(os.path.join(os.path.dirname(__file__), "../../gateway/jwt/tokens.json")))

GATED = {"disable_safety_stop", "set_torque_limit", "calibrate"}

pytestmark = pytest.mark.asyncio


async def gw_tools(robot: str, identity: str) -> list[str]:
    headers = {"Authorization": f"Bearer {TOKENS[identity]}"}
    async with streamablehttp_client(f"{GATEWAY}/mcp/{robot}", headers=headers) as (r, w, _):
        async with ClientSession(r, w) as s:
            await s.initialize()
            return [t.name for t in (await s.list_tools()).tools]


async def gw_call(robot: str, identity: str, tool: str, args: dict) -> tuple[bool, str]:
    """Returns (denied, text)."""
    headers = {"Authorization": f"Bearer {TOKENS[identity]}"}
    try:
        async with streamablehttp_client(f"{GATEWAY}/mcp/{robot}", headers=headers) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool(tool, args)
                text = " ".join(c.text for c in res.content if getattr(c, "text", None))
                return bool(res.isError), text
    except Exception as e:
        return True, str(e)


async def test_gated_tools_invisible_to_cognition():
    tools = await gw_tools("amr-1", "amr-1-cognition")
    assert "navigate_to" in tools and "emergency_stop" in tools
    assert not (set(tools) & GATED), f"gated tools leaked into tools/list: {set(tools) & GATED}"


async def test_gated_tools_invisible_on_arm():
    tools = await gw_tools("arm-1", "arm-1-cognition")
    assert "pick" in tools and "place" in tools
    assert not (set(tools) & GATED), f"gated tools leaked: {set(tools) & GATED}"


async def test_orchestrator_sees_telemetry_only():
    tools = await gw_tools("amr-1", "orchestrator")
    assert set(tools) <= {"get_pose", "get_battery", "get_state"}
    assert "navigate_to" not in tools  # the orchestrator delegates; it never actuates


async def test_maintenance_sees_everything():
    tools = await gw_tools("arm-1", "maintenance")
    assert {"set_torque_limit", "calibrate", "pick", "place"} <= set(tools)


async def test_forced_gated_call_denied():
    """The adversarial money shot: call the tool anyway -> denied."""
    denied, text = await gw_call("amr-1", "amr-1-cognition", "disable_safety_stop", {})
    assert denied, f"gated tool call was NOT denied: {text}"


async def test_forced_gated_call_denied_for_orchestrator():
    denied, text = await gw_call("arm-1", "orchestrator", "set_torque_limit", {"limit": 1.0})
    assert denied, f"orchestrator actuated a gated tool: {text}"


async def test_wrong_robot_identity_denied():
    """amr-1's cognition has NO rights on amr-2 (per-robot envelopes)."""
    tools = await gw_tools("amr-2", "amr-1-cognition")
    assert tools == [], f"cross-robot tool leak: {tools}"
    denied, _ = await gw_call("amr-2", "amr-1-cognition", "navigate_to", {"zone": "B"})
    assert denied


async def test_maintenance_can_use_gated_tool():
    denied, text = await gw_call("arm-1", "maintenance", "set_torque_limit", {"limit": 0.5})
    assert not denied, f"maintenance was denied a maintenance tool: {text}"


async def test_allowed_call_passes_through():
    denied, text = await gw_call("amr-1", "amr-1-cognition", "get_pose", {})
    assert not denied
    assert "zone" in text


async def test_anonymous_rejected():
    async with httpx.AsyncClient() as c:
        r = await c.post(
            f"{GATEWAY}/mcp/amr-1",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
        assert r.status_code == 401


def _gateway_logs(tail: int = 400) -> list[dict]:
    out = subprocess.run(
        ["docker", "compose", "logs", "gateway", "--no-log-prefix", "--tail", str(tail)],
        capture_output=True,
        text=True,
        cwd=os.path.join(os.path.dirname(__file__), "../.."),
    ).stdout
    lines = []
    for line in out.splitlines():
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return lines


async def test_audit_log_has_identity_tool_args():
    """The flight recorder: allowed AND denied calls, with who/what/args."""
    await gw_call("amr-1", "amr-1-cognition", "navigate_to", {"zone": "A"})
    await gw_call("amr-1", "amr-1-cognition", "disable_safety_stop", {})
    logs = _gateway_logs()

    allowed = [
        rec
        for rec in logs
        if rec.get("identity") == "amr-1-cognition" and rec.get("tool") == "navigate_to"
    ]
    assert allowed, "allowed tool call missing from audit log"
    assert any("zone" in json.dumps(rec.get("tool_args", "")) for rec in allowed), (
        "audit log lacks tool arguments"
    )

    denials = [
        rec
        for rec in logs
        if rec.get("identity") == "amr-1-cognition" and "disable_safety_stop" in json.dumps(rec)
    ]
    assert denials, "denied gated call left no trace in the audit log"
