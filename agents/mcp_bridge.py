"""MCP-over-gateway client: how cognition reaches its muscles.

Every tool call goes through agentgateway (JWT identity attached) — cognition
NEVER talks to a robot MCP server directly. The gateway filters tools/list, so
whatever this client sees IS the action envelope for its identity.
"""

import json
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class GatewayMCP:
    def __init__(self, url: str, token: str):
        self.url = url
        self.headers = {"Authorization": f"Bearer {token}"}

    async def list_tools_openai(self) -> list[dict]:
        """Tools as OpenAI function-calling schemas."""
        async with streamablehttp_client(self.url, headers=self.headers) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                tools = await session.list_tools()
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                },
            }
            for t in tools.tools
        ]

    async def call_tool(self, name: str, args: dict[str, Any]) -> str:
        async with streamablehttp_client(self.url, headers=self.headers) as (r, w, _):
            async with ClientSession(r, w) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
        if result.isError:
            texts = [c.text for c in result.content if getattr(c, "text", None)]
            return json.dumps({"ok": False, "error": " ".join(texts) or "tool call denied"})
        texts = [c.text for c in result.content if getattr(c, "text", None)]
        return texts[0] if texts else "{}"
