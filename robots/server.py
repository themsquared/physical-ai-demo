"""Robot MCP server: one codebase, instantiated per robot via env.

Layers (bottom kills top, never the reverse):
  reflex tier   — in-process interlocks, no network on the decision path
  degraded SM   — cognition heartbeat monitor, SAFE_IDLE on loss
  MCP tools     — the ONLY way cognition can actuate, always via the gateway

Dangerous tools (set_torque_limit, disable_safety_stop, calibrate,
set_speed_limit) are real and functional here: the gateway's deny-by-default
CEL policy is what keeps them out of non-maintenance hands. That is the demo.
"""

import asyncio
import json
import os
import statistics

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from common.otel import init_tracing
from robots.driver import SimDriver
from robots.reflex import ReflexTier
from robots.state_machine import DegradedModeSM, Mode

ROBOT_ID = os.environ.get("ROBOT_ID", "amr-1")
ROBOT_TYPE = os.environ.get("ROBOT_TYPE", "amr")  # amr | arm
PORT = int(os.environ.get("PORT", "8101"))
WORLD_URL = os.environ.get("WORLD_URL", "http://localhost:8080")
HEARTBEAT_TIMEOUT = float(os.environ.get("HEARTBEAT_TIMEOUT", "2.0"))
SENSOR_INTERVAL = float(os.environ.get("SENSOR_INTERVAL", "0.2"))

tracer = init_tracing(f"robot-{ROBOT_ID}")
driver = SimDriver(ROBOT_ID, WORLD_URL)
reflex = ReflexTier(ROBOT_ID)


async def on_mode_change(mode: Mode) -> None:
    await driver.set_field(mode=mode.value)


sm = DegradedModeSM(ROBOT_ID, HEARTBEAT_TIMEOUT, on_mode_change)

mcp = FastMCP(
    name=ROBOT_ID,
    host="0.0.0.0",
    port=PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
)


async def sensor_loop() -> None:
    """The robot's 'onboard sensors': refresh the reflex snapshot continuously
    so reflex decisions never need a network round-trip at decision time."""
    while True:
        try:
            reflex.snapshot = await driver.read_state()
        except Exception:
            pass  # sensors degrade gracefully; last snapshot stays authoritative
        await asyncio.sleep(SENSOR_INTERVAL)


def tool_span(name: str, **attrs):
    span = tracer.start_span(f"tool.{name}")
    span.set_attribute("robot.id", ROBOT_ID)
    for k, v in attrs.items():
        span.set_attribute(k, json.dumps(v) if isinstance(v, (dict, list)) else v)
    return span


# ---- tools common to all robots ----


@mcp.tool()
async def emergency_stop() -> str:
    """Immediately halt all motion. In-process interlock; cannot be refused."""
    with tool_span("emergency_stop"):
        decision = reflex.emergency_stop()  # local flag first — never blocked on I/O
        await driver.set_field(estopped=True)  # then report to the world
        return json.dumps({"ok": True, "engaged_in_us": round(decision.decision_us, 1)})


if ROBOT_TYPE == "amr":

    @mcp.tool()
    async def get_pose() -> str:
        """Current zone, navigation status, and mode of this AMR."""
        s = await driver.read_state()
        return json.dumps(
            {k: s.get(k) for k in ("zone", "target", "status", "mode", "carrying", "docked")}
        )

    @mcp.tool()
    async def get_battery() -> str:
        """Battery percentage."""
        s = await driver.read_state()
        return json.dumps({"battery": s.get("battery")})

    @mcp.tool()
    async def navigate_to(zone: str) -> str:
        """Drive to a zone (A, B, C, D, STAGING). Refused in-process if a human
        is present in the target or current zone."""
        with tool_span("navigate_to", zone=zone):
            decision = reflex.check_motion(target_zone=zone)
            if not decision.allowed:
                return json.dumps({"ok": False, "refused_by": "reflex", "reason": decision.reason})
            return json.dumps(await driver.navigate(zone))

    @mcp.tool()
    async def dock() -> str:
        """Dock at the current zone. Docking at STAGING delivers any carried pallet."""
        with tool_span("dock"):
            decision = reflex.check_motion()
            if not decision.allowed:
                return json.dumps({"ok": False, "refused_by": "reflex", "reason": decision.reason})
            return json.dumps(await driver.dock())

    @mcp.tool()
    async def set_speed_limit(limit: float) -> str:
        """DANGEROUS: set speed limit multiplier (0.1-2.0). Gateway policy
        restricts who may call this."""
        with tool_span("set_speed_limit", limit=limit):
            limit = max(0.1, min(2.0, limit))
            return json.dumps(await driver.set_field(speed_limit=limit))

    @mcp.tool()
    async def disable_safety_stop() -> str:
        """DANGEROUS: disable the human-zone safety interlock. Maintenance
        identity only, enforced by gateway policy."""
        with tool_span("disable_safety_stop"):
            reflex.safety_stop_enabled = False
            return json.dumps(await driver.set_field(safety_stop_enabled=False))

else:  # arm

    @mcp.tool()
    async def get_state() -> str:
        """Current holding/home/torque state of this arm."""
        s = await driver.read_state()
        return json.dumps(
            {k: s.get(k) for k in ("zone", "holding", "homed", "torque_limit", "status", "mode")}
        )

    @mcp.tool()
    async def pick(pallet_id: str) -> str:
        """Pick a pallet from a rack in this arm's zone."""
        with tool_span("pick", pallet_id=pallet_id):
            decision = reflex.check_motion()
            if not decision.allowed:
                return json.dumps({"ok": False, "refused_by": "reflex", "reason": decision.reason})
            return json.dumps(await driver.pick(pallet_id))

    @mcp.tool()
    async def place(location: str) -> str:
        """Place the held pallet onto an AMR in this zone (e.g. 'amr-1') or a rack."""
        with tool_span("place", location=location):
            decision = reflex.check_motion()
            if not decision.allowed:
                return json.dumps({"ok": False, "refused_by": "reflex", "reason": decision.reason})
            return json.dumps(await driver.place(location))

    @mcp.tool()
    async def home() -> str:
        """Return the arm to its home position."""
        with tool_span("home"):
            return json.dumps(await driver.set_field(homed=True, status="idle"))

    @mcp.tool()
    async def set_torque_limit(limit: float) -> str:
        """DANGEROUS: set servo torque limit (0.0-1.0). Maintenance identity
        only, enforced by gateway policy."""
        with tool_span("set_torque_limit", limit=limit):
            limit = max(0.0, min(1.0, limit))
            return json.dumps(await driver.set_field(torque_limit=limit))

    @mcp.tool()
    async def calibrate() -> str:
        """Run servo calibration. Maintenance identity only, enforced by
        gateway policy."""
        with tool_span("calibrate"):
            return json.dumps(await driver.set_field(status="calibrating"))


# ---- non-MCP control-plane endpoints (heartbeat, health, reflex receipts) ----


@mcp.custom_route("/heartbeat", methods=["POST"])
async def heartbeat(request: Request) -> JSONResponse:
    sm.beat()
    if reflex.estopped:
        body = await request.json() if await request.body() else {}
        if body.get("clear_estop"):
            reflex.clear_estop()
            await driver.set_field(estopped=False, status="idle")
    return JSONResponse({"mode": sm.mode.value})


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    timings = reflex.timings_us
    return JSONResponse(
        {
            "robot": ROBOT_ID,
            "type": ROBOT_TYPE,
            "mode": sm.mode.value,
            "estopped": reflex.estopped,
            "safety_stop_enabled": reflex.safety_stop_enabled,
            "reflex_decisions": len(timings),
            "reflex_p99_us": (
                round(statistics.quantiles(timings, n=100)[98], 1) if len(timings) >= 10 else None
            ),
            "transitions": sm.transitions[-10:],
        }
    )


async def main() -> None:
    asyncio.get_event_loop()
    sm.start()
    asyncio.create_task(sensor_loop())
    await mcp.run_streamable_http_async()


if __name__ == "__main__":
    asyncio.run(main())
