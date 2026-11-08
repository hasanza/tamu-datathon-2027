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
    """Server JSON (+ http_status) -> ToolResult, the same shape for every transport.
    status 200 -> ok; a server rejection (400/404...) -> outcome "failed"; status 0 (the enterprise server was
    unreachable or dropped the connection) -> outcome "unknown", because a write may already have committed."""
    r = dict(r)
    status = int(r.pop("http_status", 0) or 0)
    if status == 200 and "error" not in r:
        return ToolResult(ok=True, response=r, http_status=status)
    return ToolResult(
        ok=False,
        error=str(r.get("error", f"http {status}")),
        outcome="unknown" if status == 0 else "failed",
        http_status=status,
    )


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
        self._startup_timeout = startup_timeout
        self._call_timeout = call_timeout
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._closed = False
        self._up = False
        self._loop = asyncio.new_event_loop()
        self._stop: asyncio.Event | None = None
        self._task: asyncio.Task | None = None
        self._session: Any = None
        self.tools: list[str] = []
        self._thread = threading.Thread(target=self._run, name="mcp-client", daemon=True)
        self._thread.start()
        if not self._ready.wait(startup_timeout + 5):
            self.close()
            raise RuntimeError(f"MCP server did not start within {startup_timeout}s")
        if self._startup_error is not None:
            err = self._startup_error
            self.close()
            raise RuntimeError(f"MCP client failed to start: {err!r}") from err

    # -- event-loop thread -------------------------------------------------------------------------------------
    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._task = self._loop.create_task(self._main())
        try:
            self._loop.run_until_complete(self._task)
        except BaseException:  # noqa: BLE001 - cancellation / startup failure already recorded by _main
            pass

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
                await asyncio.wait_for(session.initialize(), self._startup_timeout)
                listed = await asyncio.wait_for(session.list_tools(), self._startup_timeout)
                self.tools = sorted(t.name for t in listed.tools)
                missing = REQUIRED_MCP_TOOLS - set(self.tools)
                if missing:
                    raise RuntimeError(f"MCP server is missing tools {sorted(missing)}; has {self.tools}")
                self._session = session
                self._up = True
                self._ready.set()
                await self._stop.wait()
        except BaseException as e:  # noqa: BLE001 - reported to the constructor / to callers
            if not self._ready.is_set():
                self._startup_error = e
        finally:
            self._session = None
            self._ready.set()

    # -- public API --------------------------------------------------------------------------------------------
    def call(self, event_id: str, tool: str, args: dict[str, Any]) -> ToolResult:
        with self._lock:
            session = self._session
            if self._closed or session is None:
                return ToolResult(ok=False, error="MCP executor is closed", outcome="unknown")
            fut = asyncio.run_coroutine_threadsafe(
                session.call_tool("enterprise_act", {"event_id": event_id, "tool": tool, "args": args}),
                self._loop,
            )
            try:
                res = fut.result(self._call_timeout)
            except BaseException as e:  # noqa: BLE001 - timeout or transport error: the write may have committed
                fut.cancel()
                return ToolResult(ok=False, error=f"MCP transport error: {type(e).__name__}: {e}", outcome="unknown")
        return _to_result(self._parse(res))

    @staticmethod
    def _parse(res: Any) -> dict[str, Any]:
        """CallToolResult -> the server's JSON dict (snake_case attrs of the installed SDK; camelCase as fallback)."""
        structured = getattr(res, "structured_content", None)
        if structured is None:
            structured = getattr(res, "structuredContent", None)
        is_error = bool(getattr(res, "is_error", getattr(res, "isError", False)))
        text = "".join(getattr(c, "text", "") for c in (getattr(res, "content", None) or []))
        body: Any
        if isinstance(structured, dict):
            # FastMCP-style servers may wrap a dict return as {"result": {...}}
            body = (
                structured["result"]
                if set(structured) == {"result"} and isinstance(structured["result"], dict)
                else structured
            )
        else:
            try:
                body = json.loads(text)
            except ValueError:
                return {"error": f"MCP returned non-JSON content: {text[:200]}", "http_status": 0}
            if not isinstance(body, dict):
                body = {"result": body, "http_status": 0}
        body = dict(body)
        if is_error:  # a tool-level MCP error, whichever representation carried the payload
            body.setdefault("error", text[:200] or "MCP tool error")
            body.setdefault("http_status", 0)
            if body["http_status"] == 200:
                body["http_status"] = 500
        return body

    def close(self) -> None:
        """Idempotent. Waits for an in-flight call, then stops the client task, the thread and the loop."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._session = None
        if self._loop.is_running():

            def _shutdown() -> None:
                if self._up and self._stop is not None:
                    self._stop.set()  # clean exit of the stdio/session context managers
                elif self._task is not None:
                    self._task.cancel()  # still starting up (or hung): cancel the owning task

            self._loop.call_soon_threadsafe(_shutdown)
        self._thread.join(timeout=10)
        if self._thread.is_alive() and self._task is not None:
            self._loop.call_soon_threadsafe(self._task.cancel)
            self._thread.join(timeout=10)
        if not self._thread.is_alive():
            self._loop.close()

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
        self._log_lock = threading.Lock()
        if log_path:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("")

    def call(self, event_id: str, tool: str, args: dict[str, Any]) -> ToolResult:
        res = self._twin.execute(event_id, tool, args)
        if self._log:
            line = json.dumps({"event_id": event_id, "tool": tool, "args": args, "ok": res.ok}) + "\n"
            with self._log_lock, open(self._log, "a", encoding="utf-8") as f:
                f.write(line)
        return res
