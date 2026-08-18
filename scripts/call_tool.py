#!/usr/bin/env python3
"""Force a tool call through the gateway (shows denials).
Usage: call_tool.py <mcp-url> <identity> <tool> [json-args]"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def token_for(identity: str) -> str:
    tokens = json.load(open(Path(__file__).parents[1] / "gateway/jwt/tokens.json"))
    return tokens.get(identity, identity)


def clean_error(e: BaseException) -> str:
    """Unwrap ExceptionGroups to the underlying HTTP/denial message."""
    while isinstance(e, BaseExceptionGroup) and e.exceptions:
        e = e.exceptions[0]
    msg = str(e)
    if "400" in msg or "Unknown tool" in msg:
        return "tool not available to this identity (filtered by policy)"
    return msg or type(e).__name__


async def main(url: str, token: str, tool: str, args: dict) -> None:
    try:
        async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (
            r,
            w,
            _,
        ):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool(tool, args)
                text = " ".join(c.text for c in res.content if getattr(c, "text", None))
                print(f"{'DENIED' if res.isError else 'ok'}: {text}")
    except BaseException as e:
        print(f"DENIED: {clean_error(e)}")


if __name__ == "__main__":
    args = json.loads(sys.argv[4]) if len(sys.argv) > 4 else {}
    asyncio.run(main(sys.argv[1], token_for(sys.argv[2]), sys.argv[3], args))
