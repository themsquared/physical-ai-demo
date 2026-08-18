"""mock-llm: deterministic OpenAI-compatible backend.

The bottom rung of the failover chain and the CI brain (Repeatability pillar):
same conversation in, same tool calls out, every time. State is derived ONLY
from the request messages — the server itself is stateless.

Toggle an outage with POST /outage {"fail": true} (or ?fail=true per request)
to demo the failover chain's last rung disappearing too.
"""

import json
import re
import time

from fastapi import FastAPI, Request, Response

app = FastAPI(title="mock-llm")
OUTAGE = {"fail": False}


def canned_plan(mission: str) -> dict:
    """Orchestrator asks for a mission plan -> fixed, schema-valid JSON."""
    plan = {
        "mission": mission,
        "steps": [
            {"robot": "amr-1", "task": "navigate to zone A"},
            {"robot": "arm-1", "task": "pick pallet P-42 and place onto amr-1"},
            {"robot": "amr-1", "task": "navigate to zone STAGING and dock"},
        ],
    }
    return {"role": "assistant", "content": json.dumps(plan)}


def next_tool_call(task: str, done_tools: list[str]) -> dict | None:
    """Derive the next tool call for a cognition task from what's already done."""
    task_l = task.lower()
    steps: list[tuple[str, dict]] = []
    nav = re.search(r"navigate to zone (\w+)", task_l)
    if nav:
        steps.append(("navigate_to", {"zone": nav.group(1).upper()}))
        if "dock" in task_l:
            steps.append(("dock", {}))
    pick = re.search(r"pick pallet ([\w-]+)", task_l, re.IGNORECASE)
    if pick:
        steps.append(("pick", {"pallet_id": pick.group(1).upper()}))
        place = re.search(r"place onto ([\w-]+)", task_l, re.IGNORECASE)
        if place:
            steps.append(("place", {"location": place.group(1).lower()}))
    if not steps:  # unknown task -> ask for pose, then declare done (safe default)
        steps.append(("get_pose", {}))
    idx = len(done_tools)
    return None if idx >= len(steps) else {"name": steps[idx][0], "args": steps[idx][1]}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> Response:
    if OUTAGE["fail"] or request.query_params.get("fail") == "true":
        return Response(status_code=500, content='{"error": "mock outage"}')

    body = await request.json()
    messages = body.get("messages", [])
    system = next((m["content"] for m in messages if m["role"] == "system"), "")
    user = next((m["content"] for m in messages if m["role"] == "user"), "")
    tool_results = [m for m in messages if m["role"] == "tool"]
    done_tools = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            done_tools += [tc["function"]["name"] for tc in m["tool_calls"]]

    if "orchestrator" in system.lower() or "mission planner" in system.lower():
        message = canned_plan(user)
    else:
        call = next_tool_call(user, done_tools)
        if call is None:
            last = json.loads(tool_results[-1]["content"]) if tool_results else {}
            ok = last.get("ok", True) if isinstance(last, dict) else True
            message = {
                "role": "assistant",
                "content": json.dumps({"status": "done" if ok else "failed", "detail": last}),
            }
        else:
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call_{len(done_tools)}",
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["args"]),
                        },
                    }
                ],
            }

    prompt_tokens = sum(len(str(m.get("content") or "")) for m in messages) // 4
    completion_tokens = len(json.dumps(message)) // 4
    return Response(
        media_type="application/json",
        content=json.dumps(
            {
                "id": "mock-completion",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": body.get("model", "mock-llm"),
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                },
            }
        ),
    )


@app.post("/outage")
async def outage(body: dict) -> dict:
    OUTAGE["fail"] = bool(body.get("fail"))
    return OUTAGE


@app.get("/v1/models")
async def models() -> dict:
    return {"object": "list", "data": [{"id": "mock-llm", "object": "model"}]}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": not OUTAGE["fail"]}
