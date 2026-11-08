"""FastAPI skeleton (task 1.6): serves docs/contracts.md endpoints from files on disk.

Run: ``uv run uvicorn api.app:app --port 8001``. Everything is read from disk on each request, so a pipeline
run in another process shows up without a restart.

Environment (all optional):
  TRACES_DIR   directory of ``<event_id>.json`` traces        (default ``traces/examples``)
  RUN_DIR      directory with ``action_log.jsonl`` and ``events.ndjson``  (default ``runs/dev``)
  EVENTS_PATH  the event feed                                  (default ``hack_the_highway/data/events.json``)
  CORS_ORIGINS comma-separated allowed origins                 (default the Vite dev server)
  UI_DIST      built UI served at / with SPA fallback          (default ``ui/dist``; skipped when absent)
  CT_ACCESS_PASSWORD  when set, every path but /healthz needs cookie ``ct_access`` or HTTP Basic auth with it
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sse_starlette.sse import EventSourceResponse

from control_tower.schemas import GraphPath, Trace

ROOT = Path(__file__).resolve().parents[1]
EVENT_ID = re.compile(r"^[EC]-\d{2}$")
EVENT_FILE = re.compile(r"^C-\d{2}\.json$")  # a finished judge trace (C-nn.input.json is one in flight)
# Tools that are not writes (hack_the_highway/enterprise.py TOOLS[...]["writes"] is False). Hard-coded because
# GET /tools omits the flag (docs/server-notes.md).
NON_WRITE_TOOLS = {"mes.get_schedule", "crm.loaner_availability", "escalate"}
# A real LLM run of a big event is about two minutes plus the sandbox server start.
CUSTOM_TIMEOUT_S = 300
SSE_TYPES = {"event_incoming", "event_received", "agent_step", "action", "event_done"}


@dataclass
class Settings:
    traces_dir: Path = field(default_factory=lambda: _path("TRACES_DIR", "traces/examples"))
    run_dir: Path = field(default_factory=lambda: _path("RUN_DIR", "runs/dev"))
    events_path: Path = field(default_factory=lambda: _path("EVENTS_PATH", "hack_the_highway/data/events.json"))
    cors_origins: list[str] = field(
        default_factory=lambda: os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    )
    poll_s: float = 0.25
    custom_dir: Path = field(default_factory=lambda: _path("CUSTOM_DIR", "traces/custom"))
    custom_run_dir: Path = field(default_factory=lambda: _path("CUSTOM_RUN_DIR", "runs/custom"))

    @property
    def action_log(self) -> Path:
        return self.run_dir / "action_log.jsonl"

    @property
    def stream_file(self) -> Path:
        return self.run_dir / "events.ndjson"

    @property
    def custom_stream_file(self) -> Path:
        return self.custom_run_dir / "events.ndjson"


class CustomEvent(BaseModel):
    """Either a fresh message (`text`), or a follow-up to an existing event: `parent_id` + `details` the operator adds
    (the original text is read from the parent's trace and the details are appended)."""

    text: str | None = Field(default=None, min_length=8, max_length=2000)
    source: str = Field(default="judge input", max_length=60)
    parent_id: str | None = Field(default=None, pattern=r"^[EC]-\d{2}$")
    details: str | None = Field(default=None, min_length=4, max_length=1000)


class AccessGate:
    """Pure ASGI gate: cookie ``ct_access`` (SHA-256 of the password) or HTTP Basic (any user). /healthz is exempt."""

    def __init__(self, app: Any, password: str) -> None:
        self.app = app
        self.password = password
        self.token = hashlib.sha256(password.encode()).hexdigest()

    def _allowed(self, headers: dict[bytes, bytes]) -> tuple[bool, bool]:
        """Returns (allowed, via_basic)."""
        for part in headers.get(b"cookie", b"").decode("latin-1").split(";"):
            name, _, value = part.strip().partition("=")
            if name == "ct_access" and hmac.compare_digest(value.encode(), self.token.encode()):
                return True, False
        auth = headers.get(b"authorization", b"").decode("latin-1")
        if auth[:6].lower() == "basic ":
            try:
                _, _, pw = base64.b64decode(auth[6:]).decode("utf-8").partition(":")
            except ValueError:
                return False, False
            if hmac.compare_digest(pw.encode(), self.password.encode()):
                return True, True
        return False, False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket") or scope["path"] == "/healthz":
            await self.app(scope, receive, send)
            return
        ok, via_basic = self._allowed(dict(scope["headers"]))
        if not ok:
            if scope["type"] == "http":
                body = b"Authentication required"
                await send(
                    {
                        "type": "http.response.start",
                        "status": 401,
                        "headers": [
                            (b"www-authenticate", b'Basic realm="Control Tower"'),
                            (b"content-type", b"text/plain; charset=utf-8"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
            else:
                await send({"type": "websocket.close", "code": 1008})
            return
        if not via_basic or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_cookie(message: Any) -> None:
            if message["type"] == "http.response.start":
                cookie = f"ct_access={self.token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000"
                message = {**message, "headers": [*message.get("headers", []), (b"set-cookie", cookie.encode())]}
            await send(message)

        await self.app(scope, receive, send_with_cookie)


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
    path: Path | Callable[[], Path | list[Path]],
    *,
    from_start: bool,
    poll_s: float,
    disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[dict[str, str]]:
    """Yield SSE messages for each complete JSON line appended to one or more ndjson files.

    ``path`` is a Path, or a callable returning a Path or a list of Paths (called every poll, so it follows a run
    switching directories and also tails the sandbox stream for custom events). Starts at the end of each file unless
    ``from_start``. Survives files not existing yet and being truncated (a new run). Lines that are not JSON objects with
    a known ``type`` are skipped.
    """

    def resolve() -> list[Path]:
        got = path() if callable(path) else path
        return list(got) if isinstance(got, list | tuple) else [got]

    state: dict[Path, list[Any]] = {}  # path -> [position, partial-line buffer]
    first = True
    while not await disconnected():
        paths = resolve()
        for gone in set(state) - set(paths):
            del state[gone]
        for p in paths:
            if p not in state:
                # files present at connect time start at their end (unless replaying); a path that shows up later
                # (a run switched directories) is a new stream and is read from its first line
                at_end = first and not from_start
                state[p] = [p.stat().st_size if at_end and p.exists() else 0, b""]
        for p in paths:
            pos, buf = state[p]
            if not p.exists():
                continue
            size = p.stat().st_size
            if size < pos:
                pos, buf = 0, b""
            if size > pos:
                with p.open("rb") as f:
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
                        if "event_id" in msg:  # CORE writes event_id beside the payload (docs/contracts.md)
                            data["event_id"] = msg["event_id"]
                        yield {"event": msg["type"], "data": json.dumps(data)}
            state[p] = [pos, buf]
        first = False
        await asyncio.sleep(poll_s)


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings()
    app = FastAPI(title="Wacky Wheels Control Tower API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware, allow_origins=cfg.cors_origins, allow_methods=["GET", "POST"], allow_headers=["*"]
    )

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    def event_id_or_404(event_id: str) -> str:
        if not EVENT_ID.match(event_id):
            raise HTTPException(404, f"unknown event_id {event_id!r}")
        return event_id

    def load_trace(event_id: str) -> Trace | None:
        p = (cfg.custom_dir if event_id.startswith("C-") else cfg.traces_dir) / f"{event_id}.json"
        if not p.exists():
            return None
        try:
            return Trace.model_validate_json(p.read_text(encoding="utf-8"))
        except ValidationError as e:
            raise HTTPException(500, f"{p.name} does not match the Trace contract: {e.error_count()} errors") from e

    def custom_files() -> list[Path]:
        """Finished custom traces only (C-nn.json). A run in flight keeps its input as C-nn.input.json in the same directory,
        which a plain C-*.json glob also matches: it crashed /api/events (not a Trace) and the next-id arithmetic."""
        if not cfg.custom_dir.exists():
            return []
        return sorted(p for p in cfg.custom_dir.glob("C-*.json") if EVENT_ID.match(p.stem))

    def custom_numbers() -> list[int]:
        """Numbers already taken by custom events: finished traces (C-nn.json) AND runs in flight (C-nn.input.json).
        A second submission while a run is going must not reuse that run's number (two pipelines would overwrite each other)."""
        if not cfg.custom_dir.exists():
            return []
        found = (re.fullmatch(r"C-(\d{2})(?:\.input)?\.json", p.name) for p in cfg.custom_dir.glob("C-*.json"))
        return [int(m.group(1)) for m in found if m]

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
        for p in custom_files():
            t = load_trace(p.stem)
            if t:
                out.append(
                    {
                        "event_id": t.event_id,
                        "received_at": t.received_at,
                        "source": t.source,
                        "text": t.text,
                        "status": t.status,
                        "category": t.classification.category,
                        "confidence": t.classification.confidence,
                        "custom": True,
                        "parent_id": (m.group(1) if (m := re.match(r"follow-up to ([EC]-\d{2})$", t.source)) else None),
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

    @app.post("/api/custom")
    def custom(body: CustomEvent) -> dict[str, Any]:
        """Run the full pipeline on a judge's own event text against a PRIVATE sandbox copy of the enterprise server (same four
        agents and MCP client as the feed; the scored action log is never touched). Blocks until the trace exists (a real
        LLM run is about two minutes), then returns it as C-nn with the `target` the trace records."""
        source = body.source
        if body.parent_id:  # follow-up: the operator adds details to an escalated (or any) event; re-run in the sandbox
            if not body.details:
                raise HTTPException(422, "details are required with parent_id")
            parent = load_trace(body.parent_id)
            if parent is None:
                raise HTTPException(404, f"no trace for {body.parent_id}")
            text = f"{parent.text.strip()[:1500]}\n\nFollow-up from the operator: {body.details.strip()}"
            source = f"follow-up to {body.parent_id}"
        elif body.text:
            text = body.text.strip()
        else:
            raise HTTPException(422, "give text, or parent_id with details")
        cfg.custom_dir.mkdir(parents=True, exist_ok=True)
        n = 1 + max(custom_numbers() or [0])
        if n > 99:
            raise HTTPException(409, "custom event limit reached (C-99)")
        eid = f"C-{n:02d}"
        ev = {"event_id": eid, "received_at": "2027-03-08T09:00:00", "source": source, "text": text}
        cfg.custom_run_dir.mkdir(parents=True, exist_ok=True)
        cfg.custom_stream_file.write_text("")  # connected Activity streams reset now; the run then appends live
        tmp = cfg.custom_dir / f"{eid}.input.json"
        tmp.write_text(json.dumps([ev]), encoding="utf-8")
        # the pipeline writes where the API reads: pass the dirs instead of relying on matching defaults
        cmd = [
            sys.executable,
            "-m",
            "control_tower.live",
            "--custom",
            str(tmp),
            "--run-dir",
            str(cfg.custom_run_dir),
            "--traces-dir",
            str(cfg.custom_dir),
        ]
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=CUSTOM_TIMEOUT_S)  # noqa: S603
        except subprocess.TimeoutExpired as e:
            raise HTTPException(504, "the pipeline took too long on this event") from e
        finally:
            tmp.unlink(missing_ok=True)
        t = load_trace(eid)
        if t is None:
            raise HTTPException(500, f"pipeline produced no trace: {r.stderr[-300:]}")
        return {
            "event_id": eid,
            "status": t.status,
            "category": t.classification.category,
            "parent_id": body.parent_id,
            # contract 0.2.2 puts it on the trace; until then a custom event is a sandbox run by definition
            "target": getattr(t.orchestration, "target", None) or "sandbox",
        }

    runner: dict[str, Any] = {"proc": None, "mode": None, "started": None, "stderr": None, "cancelled": False}
    initial_dirs = (cfg.traces_dir, cfg.run_dir)  # what the server was started with: the committed snapshot

    def stderr_line(code: int) -> str | None:
        """The line that says why a run ended badly: the `ABORTED:` line if there is one, else the last stderr line."""
        path = runner["stderr"]
        if not path or not Path(path).exists():
            return None
        lines = [
            ln.strip() for ln in Path(path).read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()
        ]
        aborted = [ln for ln in lines if ln.startswith("ABORTED:")]
        return (aborted[-1] if aborted else (lines[-1] if lines else None)) if code != 0 else None

    def runner_state() -> dict[str, Any]:
        proc = runner["proc"]
        running = proc is not None and proc.poll() is None
        code = None if proc is None or running else proc.returncode
        # exit 2 is the pipeline giving up on purpose (provider unavailable, or the sandbox server did not start)
        state = None if code is None else "done" if code == 0 else "aborted" if code == 2 else "failed"
        if runner["cancelled"] and not running and proc is not None:
            state = "cancelled"  # the reader stopped it: not a failure
        return {
            "running": running,
            "mode": runner["mode"],
            "exit_code": code,
            "started": runner["started"],
            "state": state,
            "message": None if state == "cancelled" else (stderr_line(code) if code is not None else None),
        }

    @app.get("/api/run/status")
    def run_status() -> dict[str, Any]:
        return runner_state()

    @app.post("/api/run", status_code=202)
    def run(
        event_id: str | None = Query(default=None, pattern=EVENT_ID.pattern),
        all: bool = False,
        mode: str = Query(default="server", pattern="^(dry|server)$"),
        pace: float = Query(default=1.0, ge=0, le=10),
        parallel: int = Query(default=1, ge=1, le=8),
    ) -> dict[str, Any]:
        """Start the pipeline in a subprocess (control_tower.live). Feed events always go to the scored organizers' server
        (mode=server, the default); mode=dry (in-process twin, no server) stays for developers."""
        if not event_id and not all:
            raise HTTPException(422, "give event_id=E-nn or all=true")
        if runner_state()["running"]:
            raise HTTPException(409, "a run is already in progress")
        cmd = [
            sys.executable,
            "-m",
            "control_tower.live",
            "--mode",
            mode,
            "--pace",
            str(pace),
            "--parallel",
            str(parallel),
        ]
        if event_id:
            cmd += ["--event", event_id]
        cfg.traces_dir, cfg.run_dir = ROOT / "traces" / "live", ROOT / "runs" / "live"
        cfg.run_dir.mkdir(parents=True, exist_ok=True)
        if event_id:
            # a single-event run replaces only that event (live.py merges its trace and log rows into the full run)
            (cfg.traces_dir / f"{event_id}.json").unlink(missing_ok=True)
        else:
            for stale in cfg.traces_dir.glob("E-*.json") if cfg.traces_dir.exists() else []:
                stale.unlink()  # a full run rewrites every trace; do not show the previous run's results as current
            cfg.action_log.write_text("")  # KPIs and the actions table must not show the previous run while it starts
        cfg.stream_file.write_text(
            ""
        )  # connected SSE tailers see the truncation now, before the pipeline starts writing
        runner["stderr"] = str(cfg.run_dir / "run.stderr")
        with open(runner["stderr"], "wb") as err:  # the child keeps its own copy of the descriptor
            # own process group, so Cancel can stop live.py together with the enterprise server it started
            runner["proc"] = subprocess.Popen(cmd, cwd=ROOT, stderr=err, start_new_session=True)  # noqa: S603
        runner["mode"], runner["started"], runner["cancelled"] = mode, time.time(), False
        return runner_state()

    def reset_dirs() -> dict[str, Path]:
        """What "Reset everything" removes: the judge events and the live run (traces, action log, streams)."""
        return {
            "judge": cfg.custom_dir,
            "judge_run": cfg.custom_run_dir,
            "live": ROOT / "traces" / "live",
            "live_run": ROOT / "runs" / "live",
        }

    def contents(d: Path) -> list[Path]:
        return [p for p in d.iterdir() if not p.name.startswith(".")] if d.exists() else []

    @app.get("/api/reset/preview")
    def reset_preview() -> dict[str, Any]:
        """Counts for the "Reset everything" dialog."""
        d = reset_dirs()
        log = d["live_run"] / "action_log.jsonl"
        return {
            "judge_events": len([p for p in contents(d["judge"]) if EVENT_FILE.fullmatch(p.name)]),
            "live_traces": len([p for p in contents(d["live"]) if p.suffix == ".json"]),
            "live_log_rows": len(_read_jsonl(log)),
            "running": runner_state()["running"],
        }

    @app.post("/api/reset")
    def reset(scope: str = Query(default="run", pattern="^(run|all)$")) -> dict[str, Any]:
        """scope=run (default): back to the snapshot: point the API at the directories it started with and forget the
        last live run. scope=all: also delete the judge events and the live run's files from disk."""
        if runner_state()["running"]:
            raise HTTPException(409, "a run is in progress; wait for it to finish")
        if scope == "all":
            for d in reset_dirs().values():
                for p in contents(d):
                    shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
        # scope=all: the feed stays quiet (the emptied live dirs) until the next Run feed; scope=run: back to the startup dirs
        cfg.traces_dir, cfg.run_dir = (
            (ROOT / "traces" / "live", ROOT / "runs" / "live") if scope == "all" else initial_dirs
        )
        runner.update(proc=None, mode=None, started=None, stderr=None, cancelled=False)
        return runner_state()

    @app.post("/api/run/cancel")
    def cancel_run() -> dict[str, Any]:
        """Stop the live run: SIGTERM to its process group (live.py and the enterprise server), SIGKILL after 5 s."""
        proc = runner["proc"]
        if proc is None or proc.poll() is not None:
            raise HTTPException(409, "no run is in progress")
        runner["cancelled"] = True
        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
                proc.wait(timeout=5)
        except ProcessLookupError:
            pass
        return runner_state()

    @app.get("/api/stream")
    async def stream(request: Request, replay: bool = False) -> EventSourceResponse:
        return EventSourceResponse(
            tail_ndjson(
                lambda: [cfg.stream_file, cfg.custom_stream_file],
                from_start=replay,
                poll_s=cfg.poll_s,
                disconnected=request.is_disconnected,
            )
        )

    dist = _path("UI_DIST", "ui/dist")
    if (dist / "index.html").is_file():
        dist_root = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            if path == "api" or path.startswith("api/"):
                raise HTTPException(404, "not found")
            f = (dist_root / path).resolve()
            if path and f.is_file() and f.is_relative_to(dist_root):
                return FileResponse(f)
            return FileResponse(dist_root / "index.html")

    password = os.environ.get("CT_ACCESS_PASSWORD")
    if password:
        app.add_middleware(AccessGate, password=password)  # added last = outermost, so CORS preflights are gated too
    return app


app = create_app()
