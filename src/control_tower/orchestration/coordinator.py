"""The Coordinator (docs/PLAN_V2.md §2): one event in, one Trace out.

A hub LLM agent (`coordinator_agent.COORDINATOR`) understands the message, resolves it, gates it, delegates to the three
specialist agents, validates their plans with code, and executes through the executor. This class builds the per-event
context, runs that agent, settles whatever the agent left open (loop error -> escalate, zero writes) and assembles the
trace. Nothing here plans: planning lives in the specialists' tools and the validators.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx

from control_tower.data.loader import World
from control_tower.orchestration.context import EventContext
from control_tower.orchestration.coordinator_agent import COORDINATOR
from control_tower.orchestration.coordinator_tools import (
    ACTIONABLE,
    _queue_escalation,
    cs,
    draft,
    flush_escalations,
    open_incidents,
    status_of,
)
from control_tower.orchestration.report import classify, counterfactual, minimal_path, world_diff
from control_tower.orchestration.runtime import run_agent
from control_tower.planning.policy import DEFAULT_POLICY, Policy
from control_tower.schemas.trace import Escalation, GraphPath, LLMUsage, Orchestration, Trace
from control_tower.trace import Sink, Timeline, write_trace
from control_tower.understanding.resolve import EntityIndex
from control_tower.world.executor import Executor
from control_tower.world.twin import Twin

TASK = (
    "Handle this incoming message end to end: register_incidents -> gate -> delegate -> validate_plan -> execute -> "
    "finish. The message is in INPUT.text."
)


class Coordinator:
    def __init__(
        self,
        world: World,
        graph: nx.MultiDiGraph,
        index: EntityIndex,
        twin: Twin,
        executor: Executor,
        *,
        traces_dir: Path,
        sink: Sink | None = None,
        policy: Policy = DEFAULT_POLICY,
        use_tiebreak: bool = True,
        use_audit: bool = True,
        use_explain: bool = True,
        mode: str = "sequential",
    ) -> None:
        self.world, self.g, self.index, self.twin, self.executor = world, graph, index, twin, executor
        self.traces_dir, self.sink, self.policy = traces_dir, sink or Sink(None), policy
        self.opts = {"use_tiebreak": use_tiebreak, "use_audit": use_audit, "use_explain": use_explain}
        self.mode = mode

    # ------------------------------------------------------------------ public
    def handle(self, event: dict[str, Any]) -> Trace:
        eid = event["event_id"]
        tl = Timeline(eid, event["received_at"], self.sink)
        self.sink.emit("event_received", eid, {k: event[k] for k in ("received_at", "source", "text")})
        ev = {**event, "id": eid}
        ctx = EventContext(
            world=self.world,
            graph=self.g,
            executor=self.executor,
            event_id=eid,
            index=self.index,
            twin=self.twin,
            policy=self.policy,
            event=ev,
            timeline=tl,
            run_mode=self.mode,
        )
        ctx.state["sink"], ctx.state["opts"] = self.sink, dict(self.opts)
        payload = {k: event[k] for k in ("event_id", "source", "received_at", "text")}
        res = run_agent(COORDINATOR, TASK, payload, ctx, tl)
        st = cs(ctx)
        error: str | None = res.error
        if error is None and not st.finished:
            error = "the coordinator ended without calling finish"
        if error:
            self._settle_unfinished(ctx, error)
        flush_escalations(ctx)
        return self._assemble(ctx, tl, error)

    # ------------------------------------------------------------------ helpers
    def _settle_unfinished(self, ctx: EventContext, error: str) -> None:
        """The agent loop died: every confirmed-but-unfinished incident is escalated, with zero writes."""
        st = cs(ctx)
        if not st.executed and any(a.writes for a in st.log):  # writes were sent but never accounted for
            st.failed = True
            st.failure_text = f"The coordinator stopped ({error}) after some writes were sent; check the action log."
            _queue_escalation(ctx, None, list(ctx.incidents), st.failure_text, "Coordinator stopped mid-execution")
            return
        ids = open_incidents(ctx)
        for i in ids:
            raw = st.raws.get(i)
            _queue_escalation(
                ctx, i, [i],
                f'{i} ({ctx.incidents[i].category}): "{raw.evidence if raw else ""}". Not completed: {error} '
                "No operational action taken.",
                "Coordinator loop failed",
            )  # fmt: skip
        if not ctx.incidents:
            _queue_escalation(
                ctx, None, [], f"Nothing could be understood or acted on: {error} No operational action taken.",
                "Coordinator loop failed",
            )  # fmt: skip
            st.escalations[-1]["incident_id"] = ctx.event_id
        ctx.timeline.step("coordinator", "decision", f"Coordinator stopped: {error}. Unfinished incidents escalated.")

    def _paths(self, ctx: EventContext) -> dict[str, list[GraphPath]]:
        st = cs(ctx)
        text, eid = ctx.event["text"], ctx.event_id
        mini = minimal_path(self.world, self.g, self.index, eid, text, f"Event {eid}")
        out: dict[str, list[GraphPath]] = {}
        for i, s in ctx.incidents.items():
            imp = ctx.impacts.get(i)
            paths = list(getattr(imp, "summary_paths", []) or []) if i in st.closed and s.category in ACTIONABLE else []
            out[i] = paths or [mini]
        return out or {eid: [mini]}

    def _assemble(self, ctx: EventContext, tl: Timeline, error: str | None) -> Trace:
        st, ev = cs(ctx), ctx.event
        for n, a in enumerate(st.log, 1):  # defensive: seq is 1..n in log order
            a.seq = n
        specs = list(ctx.incidents.values())
        status = status_of(ctx)
        if st.finished and st.summary:
            summary, reason = st.summary, st.reason or ""
        else:
            summary, reason = draft(ctx, error)
        diff = world_diff(self.world, st.log)
        cf = counterfactual(self.world, diff) if st.closed else None
        cls_reason = " ".join(s.reason for s in specs) or (error or "no incident registered")
        trace = Trace(
            event_id=ev["event_id"], received_at=ev["received_at"], source=ev["source"], text=ev["text"],
            status=status, classification=classify(specs, cls_reason), incidents=specs, paths=self._paths(ctx),
            agents=tl.agent_runs(),
            orchestration=Orchestration(
                mode=self.mode,  # type: ignore[arg-type]
                correction_rounds=st.correction_rounds,
                escalations=[Escalation(**e) for e in st.escalations],
                mcp_transport=getattr(self.executor, "transport", None),
            ),
            actions=st.log, world_diff=diff, counterfactual=cf,
            llm=LLMUsage(calls=tl.llm_calls, total_cost_usd=round(sum(c.cost_usd for c in tl.llm_calls), 6)),
            summary=summary, decision_reason=reason,
        )  # fmt: skip
        write_trace(self.traces_dir, ev["event_id"], trace.model_dump_json(indent=2, by_alias=True))
        self.sink.emit(
            "event_done",
            ev["event_id"],
            {"status": status, "category": trace.classification.category, "actions": len(trace.actions)},
        )
        return trace
