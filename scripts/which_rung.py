#!/usr/bin/env python3
"""Print which LLM rung actually served a request (failover receipt).
Usage: which_rung.py <llm-base-url> <identity>"""

import json
import sys
from pathlib import Path

import httpx


def token_for(identity: str) -> str:
    tokens = json.load(open(Path(__file__).parents[1] / "gateway/jwt/tokens.json"))
    return tokens.get(identity, identity)


def main(base: str, token: str) -> None:
    for _attempt in range(6):
        try:
            r = httpx.post(
                f"{base}/v1/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "model": "robot-brain",
                    "messages": [{"role": "user", "content": "navigate to zone A"}],
                },
                timeout=60,
            )
            if r.status_code == 200:
                print(f"  served by rung → {r.json().get('model')}")
                return
        except Exception:
            pass
    print("  (no rung served after retries)")


if __name__ == "__main__":
    main(sys.argv[1], token_for(sys.argv[2]))
