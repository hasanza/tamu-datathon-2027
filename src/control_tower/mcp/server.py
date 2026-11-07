"""MCP stdio server wrapping the enterprise server (`POST /act`, `GET /tools`).

Run: ``uv run python -m control_tower.mcp.server`` (ENTERPRISE_URL defaults to http://127.0.0.1:8000).
Built on mcp 2.x ``MCPServer`` (renamed from FastMCP). Every tool returns the server's JSON verbatim plus
``"http_status"``. A server-side error (HTTP 400/404) is returned as data
(``{"error": ..., "http_status": 400}``), never raised, so callers can record it. See docs/server-notes.md.
Failed calls are logged and counted by the server: do not retry blindly.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.mcpserver import MCPServer

DEFAULT_URL = "http://127.0.0.1:8000"
TIMEOUT_S = 30.0

mcp = MCPServer("wacky-enterprise")
_transport: httpx.BaseTransport | None = None  # tests inject httpx.MockTransport


def set_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=os.environ.get("ENTERPRISE_URL", DEFAULT_URL), timeout=TIMEOUT_S, transport=_transport
    )


def _wrap(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        body = {"error": f"non-JSON response: {resp.text[:200]}"}
    if isinstance(body, dict):
        return {**body, "http_status": resp.status_code}
    return {"result": body, "http_status": resp.status_code}


def act(event_id: str, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    # The server drops the connection (no reply) on a non-string event_id/tool; refuse before sending.
    if not isinstance(event_id, str) or not isinstance(tool, str):
        return {"error": "event_id and tool must be strings (not sent to the server)", "http_status": 0}
    try:
        with _client() as c:
            return _wrap(
                c.post(
                    "/act",
                    json={"event_id": event_id, "tool": tool, "args": args if args is not None else {}},
                )
            )
    except httpx.HTTPError as e:
        return {
            "error": f"enterprise server unreachable or closed the connection: {type(e).__name__}: {e}",
            "http_status": 0,
        }


@mcp.tool()
def enterprise_act(event_id: str, tool: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call any enterprise tool for one event's world (POST /act). WRITE tools change that event's state
    and are logged; failed calls are counted against the score. Returns server JSON + http_status."""
    return act(event_id, tool, args)


@mcp.tool()
def enterprise_get_schedule(event_id: str, plant_id: str, date: str) -> dict[str, Any]:
    """Read-only. Orders built at a plant on a weekday (YYYY-MM-DD, 2027-03-08..2027-04-02) and free slots."""
    return act(event_id, "mes.get_schedule", {"plant_id": plant_id, "date": date})


@mcp.tool()
def enterprise_loaner_availability(event_id: str, dealer_id: str) -> dict[str, Any]:
    """Read-only. Loaner cars still free at a dealer in this event's world."""
    return act(event_id, "crm.loaner_availability", {"dealer_id": dealer_id})


@mcp.tool()
def enterprise_list_tools() -> dict[str, Any]:
    """Read-only. The server's tool catalogue (GET /tools): name, description, args."""
    try:
        with _client() as c:
            r = c.get("/tools")
            return {"tools": r.json(), "http_status": r.status_code} if r.is_success else _wrap(r)
    except httpx.HTTPError as e:
        return {"error": f"enterprise server unreachable: {type(e).__name__}: {e}", "http_status": 0}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
