"""Trace assembly and the live event stream. Timestamps are simulated: the event's received_at plus real elapsed
time, so the UI shows a coherent 2027-03-08 timeline while durations stay honest."""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from control_tower.schemas.trace import AgentRun, AgentStep, LLMCall, StepKind

AGENTS = (
    "coordinator",
    "supply_chain_planner",
    "dealer_network",
    "customer_care_quality",
    "supply_chain",
    "dealer_care",
    "quality",
)


class Sink:
    """Appends one JSON line per UI event to runs/<run>/events.ndjson (the API tails this file for SSE)."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, type_: str, event_id: str, payload: dict[str, Any]) -> None:
        if not self.path:
            return
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": type_, "event_id": event_id, "payload": payload}, default=str) + "\n")


class Timeline:
    def __init__(self, event_id: str, received_at: str, sink: Sink) -> None:
        self.event_id = event_id
        self._t0 = time.perf_counter()
        self._base = datetime.fromisoformat(received_at)
        self.sink = sink
        self.runs: dict[str, AgentRun] = {}
        self.llm_calls: list[LLMCall] = []

    def now(self) -> datetime:
        return self._base + timedelta(seconds=round(time.perf_counter() - self._t0, 3))

    def step(
        self, agent: str, kind: StepKind, text: str, data: dict[str, Any] | None = None, **extra: Any
    ) -> AgentStep:
        """Append a step. `extra` carries the v0.2.0 fields (turn, tool, args, result, to_agent, from_agent,
        transport, model, cost_usd)."""
        t = self.now()
        run = self.runs.get(agent)
        if run is None:
            run = self.runs[agent] = AgentRun(agent=agent, started=t)  # type: ignore[arg-type]
        run.ended = t
        step = AgentStep(t=t, kind=kind, text=text, data=data, **extra)
        run.steps.append(step)
        self.sink.emit("agent_step", self.event_id, {"agent": agent, **step.model_dump(mode="json")})
        return step

    def usage(self, agent: str, model: str | None, cost_usd: float) -> None:
        """Account one LLM call against an agent's run (llm_calls, cost_usd, model)."""
        run = self.runs.get(agent)
        if run is None:
            run = self.runs[agent] = AgentRun(agent=agent, started=self.now())  # type: ignore[arg-type]
        run.llm_calls += 1
        run.cost_usd = round(run.cost_usd + cost_usd, 6)
        run.model = model or run.model

    def llm(self, call: LLMCall) -> None:
        self.llm_calls.append(call)

    def agent_runs(self) -> list[AgentRun]:
        return [self.runs[a] for a in AGENTS if a in self.runs]


def write_trace(trace_dir: Path, event_id: str, trace_json: str) -> Path:
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / f"{event_id}.json"
    path.write_text(trace_json + "\n", encoding="utf-8")
    return path
