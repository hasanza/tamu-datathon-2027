"""Where actions actually happen. ServerExecutor goes through the MCP server module's `act` (the same code Claude Code
reaches over stdio); TwinExecutor runs the organizers' Enterprise class in-process for dry runs and tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

from control_tower.schemas.action import ToolResult
from control_tower.world.twin import Twin


class Executor(Protocol):
    name: str

    def call(self, event_id: str, tool: str, args: dict[str, Any]) -> ToolResult: ...


class ServerExecutor:
    name = "server"

    def __init__(self, base_url: str) -> None:
        os.environ["ENTERPRISE_URL"] = base_url
        from control_tower.mcp import server  # imported late so ENTERPRISE_URL is already set

        self._act = server.act

    def call(self, event_id: str, tool: str, args: dict[str, Any]) -> ToolResult:
        r = self._act(event_id, tool, args)
        status = r.pop("http_status", 0)
        if status == 200 and "error" not in r:
            return ToolResult(ok=True, response=r)
        return ToolResult(ok=False, error=r.get("error", f"http {status}"), response=None)


class TwinExecutor:
    """Dry run: same semantics as the server, plus the same action_log.jsonl format."""

    name = "twin"

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
