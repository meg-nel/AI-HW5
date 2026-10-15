"""Long-lived MCP client connection to the Campus Customs MCP server (spawned over stdio)."""

import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent


class MCPBridge:
    def __init__(self):
        self._stack = AsyncExitStack()
        self.session: ClientSession | None = None
        self.tools: list = []

    async def start(self) -> None:
        # Pass our env through so overrides like CAMPUS_CUSTOMS_DB reach the server process
        params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"], cwd=str(ROOT), env=dict(os.environ))
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        self.tools = (await self.session.list_tools()).tools

    async def stop(self) -> None:
        await self._stack.aclose()

    def agent_tool_defs(self, allowed: list[str] | None) -> list[dict]:
        """Claude tool definitions for an agent. Admin tools are never exposed to agents."""
        return [
            {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
            for t in self.tools
            if not t.name.startswith("admin_") and (allowed is None or t.name in allowed)
        ]

    async def call(self, name: str, args: dict):
        """Call an MCP tool and return its decoded result. Raises RuntimeError on tool errors."""
        result = await self.session.call_tool(name, args)
        text = "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        if result.isError:
            raise RuntimeError(text or f"{name} failed")
        if result.structuredContent is not None:
            # FastMCP wraps non-object returns as {"result": ...}
            sc = result.structuredContent
            return sc["result"] if set(sc) == {"result"} else sc
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text


bridge = MCPBridge()
