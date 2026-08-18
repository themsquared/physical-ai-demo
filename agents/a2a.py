"""Minimal A2A surface: agent card + message/send. No framework.

Implements just enough of the A2A protocol for agent-to-agent messaging
through agentgateway's a2a policy: a discovery card and synchronous
message/send over JSON-RPC 2.0.
"""

import uuid
from collections.abc import Awaitable, Callable

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

Handler = Callable[[str], Awaitable[str]]


def make_app(name: str, description: str, skills: list[dict], handler: Handler) -> FastAPI:
    app = FastAPI(title=name)
    card = {
        "protocolVersion": "0.3.0",
        "name": name,
        "description": description,
        "url": "/",
        "preferredTransport": "JSONRPC",
        "capabilities": {"streaming": False},
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": skills,
    }

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "agent": name}

    # The gateway forwards requests with their ORIGINAL path (/a2a/<agent>/...),
    # so both the card and the JSON-RPC endpoint answer on any path.
    @app.get("/{full_path:path}")
    async def agent_card(full_path: str) -> dict:
        if full_path.endswith(("agent-card.json", "agent.json")) or full_path in ("", "card"):
            return card
        return card  # A2A GET discovery is the only GET surface we serve

    @app.post("/{full_path:path}")
    async def rpc(request: Request) -> JSONResponse:
        body = await request.json()
        rpc_id = body.get("id")
        if body.get("method") != "message/send":
            return JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": rpc_id,
                    "error": {
                        "code": -32601,
                        "message": f"unsupported method {body.get('method')}",
                    },
                }
            )
        parts = body.get("params", {}).get("message", {}).get("parts", [])
        text = " ".join(p.get("text", "") for p in parts if p.get("kind") == "text")
        result_text = await handler(text)
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "kind": "message",
                    "role": "agent",
                    "messageId": str(uuid.uuid4()),
                    "parts": [{"kind": "text", "text": result_text}],
                },
            }
        )

    return app


async def a2a_send(url: str, text: str, token: str | None = None, timeout: float = 300.0) -> str:
    """Send one A2A message and return the agent's text reply."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": str(uuid.uuid4()),
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(f"A2A error from {url}: {data['error']}")
        parts = data["result"].get("parts", [])
        return " ".join(p.get("text", "") for p in parts if p.get("kind") == "text")
