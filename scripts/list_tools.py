#!/usr/bin/env python3
"""List the tools an identity can SEE through the gateway.
Usage: list_tools.py <mcp-url> <identity>   (token read from gateway/jwt/tokens.json)"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def token_for(identity: str) -> str:
    tokens = json.load(open(Path(__file__).parents[1] / "gateway/jwt/tokens.json"))
    return tokens.get(identity, identity)  # fall back to a literal token


async def main(url: str, token: str) -> None:
    async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (
        r,
        w,
        _,
    ):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = [t.name for t in (await s.list_tools()).tools]
    print("visible tools:", ", ".join(tools) if tools else "(none)")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], token_for(sys.argv[2])))
