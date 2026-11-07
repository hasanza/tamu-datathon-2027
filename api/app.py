"""FastAPI skeleton (task 1.6): serves docs/contracts.md endpoints from files on disk.

Run: ``uv run uvicorn api.app:app --port 8001``. Everything is read from disk on each request, so a pipeline
run in another process shows up without a restart.

Environment (all optional):
  TRACES_DIR   directory of ``<event_id>.json`` traces        (default ``traces/examples``)
  RUN_DIR      directory with ``action_log.jsonl`` and ``events.ndjson``  (default ``runs/dev``)
  EVENTS_PATH  the event feed                                  (default ``hack_the_highway/data/events.json``)
  CORS_ORIGINS comma-separated allowed origins                 (default the Vite dev server)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sse_starlette.sse import EventSourceResponse

from control_tower.schemas import GraphPath, Trace

ROOT = Path(__file__).resolve().parents[1]
EVENT_ID = re.compile(r"^E-\d{2}$")
# Tools that are not writes (hack_the_highway/enterprise.py TOOLS[...]["writes"] is False). Hard-coded because
# GET /tools omits the flag (docs/server-notes.md).
NON_WRITE_TOOLS = {"mes.get_schedule", "crm.loaner_availability", "escalate"}
SSE_TYPES = {"event_received", "agent_step", "action", "event_done"}


@dataclass
class Settings:
    traces_dir: Path = field(default_factory=lambda: _path("TRACES_DIR", "traces/examples"))
    run_dir: Path = field(default_factory=lambda: _path("RUN_DIR", "runs/dev"))
    events_path: Path = field(default_factory=lambda: _path("EVENTS_PATH", "hack_the_highway/data/events.json"))
    cors_origins: list[str] = field(
        default_factory=lambda: os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    )
    poll_s: float = 0.25

    @property
    def action_log(self) -> Path:
        return self.run_dir / "action_log.jsonl"

    @property
    def stream_file(self) -> Path:
        return self.run_dir / "events.ndjson"


def _path(var: str, default: str) -> Path:
    p = Path(os.environ.get(var, default))
    return p if p.is_absolute() else ROOT / p


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # a half-written last line while the server appends
    return rows


async def tail_ndjson(
    path: Path,
    *,
    from_start: bool,
    poll_s: float,
    disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE messages for each complete JSON line appended to ``path``.

    Starts at the end of the file unless ``from_start``. Survives the file not existing yet and
    being truncated (a new run). Lines that are not JSON objects with a known ``type`` are skipped.
    """
    pos = 0 if from_start else (path.stat().st_size if path.exists() else 0)
    buf = b""
    while not await disconnected():
        if path.exists():
            size = path.stat().st_size
            if size < pos:
                pos, buf = 0, b""
            if size > pos:
                with path.open("rb") as f:
                    f.seek(pos)
                    chunk = f.read()
                pos += len(chunk)
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for raw in lines:
                    try:
                        msg = json.loads(raw)
                    except ValueError:
                        continue
                    if isinstance(msg, dict) and msg.get("type") in SSE_TYPES:
                        payload = msg.get("payload")
                        data = dict(payload) if isinstance(payload, dict) else {}
                        if (
                            "event_id" in msg
                        ):  # CORE writes event_id beside the payload (docs/contracts.md: payload + event_id)
                            data["event_id"] = msg["event_id"]
                        yield {"event": msg["type"], "data": json.dumps(data)}
        await asyncio.sleep(poll_s)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    app = FastAPI(title="Wacky Wheels Control Tower API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["GET", "POST"], allow_headers=["*"]
    )

    def event_id_or_404(event_id: str) -> str:
        if not EVENT_ID.match(event_id):
            raise HTTPException(404, f"unknown event_id {event_id!r}")
        return event_id

    def load_trace(event_id: str) -> Trace | None:
        p = cfg.traces_dir / f"{event_id}.json"
        if not p.exists():
            return None
        try:
            return Trace.model_validate_json(p.read_text(encoding="utf-8"))
        except ValidationError as e:
            raise HTTPException(500, f"{p.name} does not match the Trace contract: {e.error_count()} errors") from e

    def all_traces() -> dict[str, Trace]:
        out = {}
        for p in sorted(cfg.traces_dir.glob("E-*.json")):
            if EVENT_ID.match(p.stem) and (t := load_trace(p.stem)):
                out[p.stem] = t
        return out

    def feed() -> list[dict[str, Any]]:
        if not cfg.events_path.exists():
            raise HTTPException(500, f"event feed not found: {cfg.events_path}")
        return json.loads(cfg.events_path.read_text(encoding="utf-8"))

    @app.get("/api/events")
    def events() -> list[dict[str, Any]]:
        traces = all_traces()
        out = []
        for ev in feed():
            t = traces.get(ev["event_id"])
            out.append(
                {
                    **ev,
                    "status": t.status if t else "queued",
                    "category": t.classification.category if t else None,
                    "confidence": t.classification.confidence if t else None,
                }
            )
        return out

    @app.get("/api/traces/{event_id}", response_model=Trace)
    def trace(event_id: str) -> Trace:
        t = load_trace(event_id_or_404(event_id))
        if t is None:
            raise HTTPException(404, f"no trace for {event_id} yet")
        return t

    @app.get("/api/actions")
    def actions(event_id: str | None = Query(default=None, pattern=EVENT_ID.pattern)) -> list[dict[str, Any]]:
        out = []
        for i, row in enumerate(_read_jsonl(cfg.action_log), start=1):
            if event_id and row.get("event_id") != event_id:
                continue
            out.append({"line": i, **row, "write": row.get("tool") not in NON_WRITE_TOOLS})
        return out

    @app.get("/api/graph/{event_id}", response_model=GraphPath)
    def graph(event_id: str) -> dict[str, Any]:
        t = load_trace(event_id_or_404(event_id))
        if t is None:
            raise HTTPException(404, f"no trace for {event_id} yet")
        nodes: dict[str, Any] = {}
        edges: dict[tuple[str, str, str], Any] = {}
        for paths in t.paths.values():
            for p in paths:
                for n in p.nodes:
                    nodes.setdefault(n.id, n.model_dump(mode="json"))
                for e in p.edges:
                    edges.setdefault((e.from_, e.to, e.type), e.model_dump(mode="json", by_alias=True))
        return {"nodes": list(nodes.values()), "edges": list(edges.values())}

    @app.get("/api/kpis")
    def kpis() -> dict[str, Any]:
        traces = all_traces()
        log = _read_jsonl(cfg.action_log)
        by_status: dict[str, int] = {}
        for t in traces.values():
            by_status[t.status] = by_status.get(t.status, 0) + 1
        calls = [c for t in traces.values() for c in t.llm.calls]
        return {
            "events_total": len(feed()),
            "events_with_trace": len(traces),
            "by_status": by_status,
            "actions": len(log),
            "writes": sum(r.get("tool") not in NON_WRITE_TOOLS for r in log),
            "failed": sum(r.get("ok") is False for r in log),
            "escalations": sum(r.get("tool") == "escalate" for r in log),
            "cost_usd": round(sum(t.llm.total_cost_usd for t in traces.values()), 6),
            "llm_calls": len(calls),
            "models": sorted({f"{c.provider}/{c.model}" for c in calls}),
        }

    runner: dict[str, Any] = {"proc": None, "mode": None, "started": None}

    def runner_state() -> dict[str, Any]:
        proc = runner["proc"]
        running = proc is not None and proc.poll() is None
        return {
            "running": running,
            "mode": runner["mode"],
            "exit_code": None if proc is None or running else proc.returncode,
            "started": runner["started"],
        }

    @app.get("/api/run/status")
    def run_status() -> dict[str, Any]:
        return runner_state()

    @app.post("/api/run", status_code=202)
    def run(
        event_id: str | None = Query(default=None, pattern=EVENT_ID.pattern),
        all: bool = False,
        mode: str = Query(default="dry", pattern="^(dry|server)$"),
        pace: float = Query(default=1.0, ge=0, le=10),
    ) -> dict[str, Any]:
        """Start the pipeline in a subprocess (control_tower.live). mode=server uses a fresh organizers' server."""
        if not event_id and not all:
            raise HTTPException(422, "give event_id=E-nn or all=true")
        if runner_state()["running"]:
            raise HTTPException(409, "a run is already in progress")
        cmd = [sys.executable, "-m", "control_tower.live", "--mode", mode, "--pace", str(pace)]
        if event_id:
            cmd += ["--event", event_id]
        cfg.traces_dir, cfg.run_dir = ROOT / "traces" / "live", ROOT / "runs" / "live"
        for stale in cfg.traces_dir.glob("E-*.json") if cfg.traces_dir.exists() else []:
            stale.unlink()  # the live run rewrites traces; do not show the previous run's results as current
        cfg.run_dir.mkdir(parents=True, exist_ok=True)
        cfg.action_log.write_text("")  # KPIs and the actions table must not show the previous run while this one starts
        cfg.stream_file.write_text(
            ""
        )  # connected SSE tailers see the truncation now, before the pipeline starts writing
        env = {**os.environ, "LLM_CACHE_DIR": os.environ.get("LLM_CACHE_DIR", str(ROOT / "cache" / "snapshot"))}
        runner["proc"] = subprocess.Popen(cmd, cwd=ROOT, env=env)  # noqa: S603
        runner["mode"], runner["started"] = mode, time.time()
        return runner_state()

    @app.get("/api/stream")
    async def stream(request: Request, replay: bool = False) -> EventSourceResponse:
        return EventSourceResponse(
            tail_ndjson(cfg.stream_file, from_start=replay, poll_s=cfg.poll_s, disconnected=request.is_disconnected)
        )

    return app


app = create_app()
