"""Where actions actually happen.

- `McpExecutor` (default for server runs): an MCP client. It spawns ``python -m control_tower.mcp.server`` over stdio and
  every enterprise call (reads and writes) goes through ``session.call_tool("enterprise_act", ...)``.
- `HttpExecutor`: calls the MCP server module's `act` function in-process (same HTTP code, no MCP protocol). Kept for
  tests and comparison.
- `TwinExecutor`: the organizers' Enterprise class in-process, for dry runs, tests and the sandbox.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Protocol

from control_tower.schemas.action import ToolResult, Transport
from control_tower.world.twin import Twin

REQUIRED_MCP_TOOLS = frozenset(
    {"enterprise_act", "enterprise_get_schedule", "enterprise_loaner_availability", "enterprise_list_tools"}
)


class Executor(Protocol):
    name: str
    transport: Transport

    def call(self, event_id: str, tool: str, args: dict[str, Any]) -> ToolResult: ...


def _to_result(r: dict[str, Any]) -> ToolResult:
    """Server JSON (+ http_status) -> ToolResult, the same shape for every transport."""
    r = dict(r)
    status = r.pop("http_status", 0)
    if status == 200 and "error" not in r:
        return ToolResult(ok=True, response=r)
    return ToolResult(ok=False, error=str(r.get("error", f"http {status}")), response=None)


class HttpExecutor:
    """In-process call of the MCP server's `act` (HTTP to the enterprise server, no MCP protocol)."""

    name = "http"
    transport: Transport = "in-process"

    def __init__(self, base_url: str) -> None:
        os.environ["ENTERPRISE_URL"] = base_url
        from control_tower.mcp import server  # imported late so ENTERPRISE_URL is already set

        self._act = server.act

    def call(self, event_id: str, tool: str, args: dict[str, Any]) -> ToolResult:
        return _to_result(self._act(event_id, tool, args))


class McpExecutor:
    """MCP client over stdio. The asyncio loop lives in a dedicated thread; calls are serialised by a lock."""

    name = "mcp"
    transport: Transport = "mcp/stdio"

    def __init__(self, base_url: str, *, startup_timeout: float = 30.0, call_timeout: float = 60.0) -> None:
        self._base_url = base_url
        self._call_timeout = call_timeout
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._loop = asyncio.new_event_loop()
        self._stop: asyncio.Event | None = None
        self._session: Any = None
        self.tools: list[str] = []
        self._thread = threading.Thread(target=self._run, name="mcp-client", daemon=True)
        self._thread.start()
        if not self._ready.wait(startup_timeout):
            self.close()
            raise RuntimeError(f"MCP server did not start within {startup_timeout}s")
        if self._startup_error is not None:
            self.close()
            raise RuntimeError(f"MCP client failed to start: {self._startup_error!r}") from self._startup_error

    # -- event-loop thread -------------------------------------------------------------------------------------
    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._main())

    async def _main(self) -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._stop = asyncio.Event()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "control_tower.mcp.server"],
            env={**os.environ, "ENTERPRISE_URL": self._base_url},
        )
        try:
            async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                self.tools = sorted(t.name for t in listed.tools)
                missing = REQUIRED_MCP_TOOLS - set(self.tools)
                if missing:
                    raise RuntimeError(f"MCP server is missing tools {sorted(missing)}; has {self.tools}")
                self._session = session
                self._ready.set()
                await self._stop.wait()
        except BaseException as e:  # noqa: BLE001 - reported to the constructor / to callers
            if not self._ready.is_set():
                self._startup_error = e
                self._ready.set()
            else:
                self._session = None

    # -- public API --------------------------------------------------------------------------------------------
    def call(self, event_id: str, tool: str, args: dict[str, Any]) -> ToolResult:
        if self._session is None:
            return ToolResult(ok=False, error="MCP session is closed")
        with self._lock:
            fut = asyncio.run_coroutine_threadsafe(
                self._session.call_tool("enterprise_act", {"event_id": event_id, "tool": tool, "args": args}),
                self._loop,
            )
            try:
                res = fut.result(self._call_timeout)
            except Exception as e:  # noqa: BLE001
                fut.cancel()
                return ToolResult(ok=False, error=f"MCP call failed: {type(e).__name__}: {e}")
        return _to_result(self._parse(res))

    @staticmethod
    def _parse(res: Any) -> dict[str, Any]:
        structured = getattr(res, "structuredContent", None)
        if isinstance(structured, dict):
            # FastMCP-style servers may wrap a dict return as {"result": {...}}
            if set(structured) == {"result"} and isinstance(structured["result"], dict):
                return structured["result"]
            return structured
        text = "".join(getattr(c, "text", "") for c in (res.content or []))
        try:
            body = json.loads(text)
        except ValueError:
            return {"error": f"MCP returned non-JSON content: {text[:200]}", "http_status": 0}
        if getattr(res, "isError", False) and isinstance(body, dict):
            body.setdefault("error", text[:200])
        return body if isinstance(body, dict) else {"result": body, "http_status": 0}

    def close(self) -> None:
        if self._stop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._stop.set)
        self._thread.join(timeout=10)

    def __enter__(self) -> McpExecutor:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class TwinExecutor:
    """Dry run: same semantics as the server, plus the same action_log.jsonl format."""

    name = "twin"
    transport: Transport = "twin"

    def __init__(self, log_path: Path | None = None) -> None:
        self._twin = Twin()
        self._log = log_path
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("")

    def call(self, event_id: str, tool: str, args: dict[str, Any]) -> ToolResult:
        res = self._twin.execute(event_id, tool, args)
        if self._log:
            with open(self._log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"event_id": event_id, "tool": tool, "args": args, "ok": res.ok}) + "\n")
        return res
