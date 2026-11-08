"""Call an OpsPilot MCP tool from the command line (uses the official MCP client).

    python mcp/scripts/call_tool.py --list
    python mcp/scripts/call_tool.py get_service_health service=checkout
    python mcp/scripts/call_tool.py get_recent_logs service=checkout minutes=10 severity=warning

Arguments are key=value; integers are converted automatically. Set MCP_URL and
MCP_AUTH_TOKEN if the server is not at http://127.0.0.1:8001 or requires a token.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def parse_arguments(pairs: list[str]) -> dict[str, object]:
    arguments: dict[str, object] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"expected key=value, got {pair!r}")
        arguments[key] = int(value) if value.lstrip("-").isdigit() else value
    return arguments


async def run(tool: str | None, arguments: dict[str, object]) -> int:
    url = os.environ.get("MCP_URL", "http://127.0.0.1:8001").rstrip("/") + "/mcp"
    token = os.environ.get("MCP_AUTH_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(headers=headers, timeout=60) as http:
        async with streamable_http_client(url, http_client=http) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                if tool is None:
                    for t in (await session.list_tools()).tools:
                        print(f"{t.name}: {(t.description or '').splitlines()[0]}")  # noqa: T201
                    return 0
                result = await session.call_tool(tool, arguments)
                if result.isError:
                    message = result.content[0].text if result.content else "tool error"
                    print(message, file=sys.stderr)  # noqa: T201
                    return 1
                print(json.dumps(result.structuredContent, indent=2, default=str))  # noqa: T201
                return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("tool", nargs="?")
    parser.add_argument("arguments", nargs="*", help="key=value")
    parser.add_argument("--list", action="store_true", help="list available tools")
    args = parser.parse_args()
    if not args.list and not args.tool:
        parser.error("give a tool name or --list")
    tool = None if args.list else args.tool
    raise SystemExit(asyncio.run(run(tool, parse_arguments(args.arguments))))


if __name__ == "__main__":
    main()
