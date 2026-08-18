#!/usr/bin/env python3
"""Invoke a kagent agent over its A2A endpoint (legacy 0.3 dialect kagent speaks).
Usage: kagent_invoke.py <a2a-base-url> <task-text>

kagent serves the card at <base>/.well-known/agent.json and accepts message/send
JSON-RPC at <base>. Prints the agent's text reply.
"""

import sys
import uuid

import httpx


def main(base: str, text: str) -> None:
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
    r = httpx.post(base, json=payload, timeout=300)
    r.raise_for_status()
    data = r.json()
    if "error" in data:
        print(f"agent error: {data['error']}")
        sys.exit(1)
    result = data.get("result", {})
    # message/send may return a message or a task with artifacts
    parts = result.get("parts") or []
    for art in result.get("artifacts", []) or []:
        parts += art.get("parts", [])
    texts = [p.get("text", "") for p in parts if p.get("kind") == "text" or "text" in p]
    print("\n--- fleet-sre ---")
    print("\n".join(t for t in texts if t) or str(result)[:800])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
