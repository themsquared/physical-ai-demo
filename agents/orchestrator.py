"""Fleet orchestrator: mission in -> plan -> delegate over A2A -> replan on failure.

Plans are schema-constrained (pydantic-validated JSON, bounded retries).
Replanning covers the two demo failure modes:
  - reflex refusal (human in zone): wait-and-retry, then reassign to the other AMR
  - dead cognition agent: A2A call fails -> reassign to the other AMR
"""

import asyncio
import json
import os

import uvicorn
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from agents.a2a import a2a_send, make_app
from common.identity import load_token
from common.otel import init_tracing

PORT = int(os.environ.get("PORT", "9000"))
GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:3000")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:4b")
JWT_TOKEN = load_token("orchestrator")
STEP_RETRIES = int(os.environ.get("STEP_RETRIES", "4"))
RETRY_WAIT = float(os.environ.get("RETRY_WAIT", "3.0"))

tracer = init_tracing("orchestrator")

llm = AsyncOpenAI(
    base_url=f"{GATEWAY_URL}/llm/v1",
    api_key="not-needed-identity-is-jwt",
    default_headers={"Authorization": f"Bearer {JWT_TOKEN}"},
)

AMR_ALTERNATE = {"amr-1": "amr-2", "amr-2": "amr-1"}


class Step(BaseModel):
    robot: str
    task: str


class Plan(BaseModel):
    mission: str
    steps: list[Step]


PLANNER_SYSTEM = """You are the fleet orchestrator (mission planner) for a warehouse.
Robots: amr-1 and amr-2 (mobile robots that navigate zones A,B,C,D,STAGING and dock),
arm-1 (fixed picker arm in zone A that can pick pallets from racks and place them onto an AMR in zone A).
Decompose the mission into sequential steps. Reply with ONLY JSON, no prose:
{"mission": "<mission>", "steps": [{"robot": "<robot-id>", "task": "<imperative task>"}]}
Task phrasing must use these forms: "navigate to zone <Z>", "pick pallet <ID> and place onto <amr-id>",
"navigate to zone <Z> and dock". Safety policy is enforced by the platform; plan only allowed work."""


async def make_plan(mission: str) -> Plan:
    messages = [
        {"role": "system", "content": PLANNER_SYSTEM},
        {"role": "user", "content": mission},
    ]
    last_err: Exception | None = None
    for attempt in range(3):
        with tracer.start_as_current_span("llm.mission_plan") as span:
            span.set_attribute("attempt", attempt)
            resp = await llm.chat.completions.create(
                model=LLM_MODEL, messages=messages, temperature=0.1
            )
            raw = (resp.choices[0].message.content or "").strip()
            span.set_attribute("plan.raw", raw[:1000])
        try:
            start, end = raw.find("{"), raw.rfind("}")
            plan = Plan.model_validate_json(raw[start : end + 1])
            if plan.steps:
                return plan
        except (ValidationError, json.JSONDecodeError, ValueError) as e:
            last_err = e
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": f"Invalid plan JSON ({e}). Reply with ONLY the JSON object.",
                }
            )
    raise RuntimeError(f"planner failed schema validation after 3 attempts: {last_err}")


def agent_url(robot: str) -> str:
    return f"{GATEWAY_URL}/a2a/{robot}-cognition"


async def dispatch(step: Step) -> dict:
    """Send one step to a cognition agent; normalize its reply to a status dict."""
    try:
        reply = await a2a_send(agent_url(step.robot), step.task, token=JWT_TOKEN)
    except Exception as e:
        return {"status": "failed", "detail": f"agent unreachable: {e}", "robot": step.robot}
    try:
        start, end = reply.find("{"), reply.rfind("}")
        parsed = json.loads(reply[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        parsed = {"status": "done", "detail": reply[:200]}
    parsed["robot"] = step.robot
    return parsed


async def run_mission(mission: str) -> str:
    with tracer.start_as_current_span("mission") as span:
        span.set_attribute("mission.text", mission)
        try:
            plan = await make_plan(mission)
        except Exception as e:
            return json.dumps({"status": "failed", "detail": str(e)})
        span.set_attribute("plan.steps", json.dumps([s.model_dump() for s in plan.steps]))

        log: list[dict] = []
        for i, step in enumerate(plan.steps):
            current = step
            result: dict = {}
            for attempt in range(STEP_RETRIES):
                with tracer.start_as_current_span("mission.step") as sspan:
                    sspan.set_attribute("step.index", i)
                    sspan.set_attribute("step.robot", current.robot)
                    sspan.set_attribute("step.task", current.task)
                    sspan.set_attribute("step.attempt", attempt)
                    result = await dispatch(current)
                    sspan.set_attribute("step.status", result.get("status", "?"))
                if result.get("status") == "done":
                    break
                # Replan: prefer handing AMR work to the other AMR; a blocked
                # human zone may also clear, so wait before each retry.
                alt = AMR_ALTERNATE.get(current.robot)
                if alt:
                    # Later steps referencing the failed AMR must follow the pallet.
                    for later in plan.steps[i + 1 :]:
                        later.task = later.task.replace(current.robot, alt)
                        if later.robot == current.robot:
                            later.robot = alt
                    current = Step(robot=alt, task=current.task.replace(current.robot, alt))
                    log.append({"replan": f"reassigned to {alt}", "reason": result.get("detail")})
                else:
                    await asyncio.sleep(RETRY_WAIT)
            log.append(result)
            if result.get("status") != "done":
                return json.dumps({"status": "failed", "mission": mission, "log": log})
        return json.dumps({"status": "done", "mission": mission, "log": log})


app = make_app(
    "orchestrator",
    "Warehouse fleet orchestrator: decomposes missions and delegates to cognition agents",
    [
        {
            "id": "run-mission",
            "name": "Run mission",
            "description": "Plans and executes a warehouse mission across the fleet",
            "tags": ["robotics"],
        }
    ],
    run_mission,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
