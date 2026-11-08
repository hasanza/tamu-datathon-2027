"""The Coordinator's tools (docs/PLAN_V2.md §2.2, §3.1, §4.1, §5). The coordinator agent reasons about WHAT to do; these
tools enforce the guardrails in code: the noise guard, the delegation cadence, the correction-round cap, the completion
check, "no write before the twin rehearsal, the audit and the live-freshness check passed", and failed-call handling.

State lives in `ctx.state["coord"]` (a `CoordState`); options (explain / audit / tie-break switches) in
`ctx.state["opts"]`.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from control_tower.orchestration.auditor import audit, plan_digest
from control_tower.orchestration.config import agent_config
from control_tower.orchestration.context import EventContext
from control_tower.orchestration.explain import explain
from control_tower.orchestration.report import MOVES, incident_sentence, ok, tool_counts
from control_tower.orchestration.runtime import run_agent
from control_tower.orchestration.specialist_tools import CCQ, _lot_impact, _quality_reason, _replay_moves, _stamp, stash
from control_tower.orchestration.specialists import SPECIALISTS
from control_tower.orchestration.tools import tool
from control_tower.planning.dealer_care import plan_care
from control_tower.planning.quality import plan_quality
from control_tower.planning.supply_chain import SlotBoard
from control_tower.planning.validators import Finding, blocking, validate
from control_tower.schemas.action import Action, Rehearsal, ToolResult
from control_tower.understanding.resolve import EntityIndex, build_incident, parse_date_phrase
from control_tower.understanding.schemas import RawIncident
from control_tower.understanding.tiebreak import make_tiebreak

CO = "coordinator"
ACTIONABLE = {"supplier_delay", "plant_outage", "quality_hold"}
MAX_ROUNDS = 2  # correction rounds per (agent, task, incident)
# task -> (agent, per-incident?, incident categories it applies to)
TASKS: dict[str, tuple[str, bool, set[str]]] = {
    "reschedule": ("supply_chain_planner", True, {"supplier_delay", "plant_outage"}),
    "quality_hold": ("customer_care_quality", True, {"quality_hold"}),
    "dealer_comms": ("dealer_network", False, set()),
    "loaners": ("customer_care_quality", False, set()),
}
# validator rules that concern each task (a correction round only sees the findings it can act on)
TASK_RULES = {
    "reschedule": {"V1", "V2", "V6", "V8"},
    "quality_hold": {"V5", "V6", "V8"},
    "dealer_comms": {"V3", "V5", "V6"},
    "loaners": {"V4", "V6"},
}


@dataclass
class CoordState:
    raws: dict[str, RawIncident] = field(default_factory=dict)
    needs_human: dict[str, bool] = field(default_factory=dict)
    dropped: dict[str, str] = field(default_factory=dict)
    escalated: dict[str, str] = field(default_factory=dict)  # incident_id -> full reason text
    partial: dict[str, str] = field(default_factory=dict)  # executed incidents with a failed/skipped/unknown action
    noise_refused: set[str] = field(default_factory=set)  # noise items whose drop_noise was refused (name a record)
    esc_queue: list[Action] = field(default_factory=list)  # escalate Actions not yet sent
    escalations: list[dict[str, str]] = field(default_factory=list)  # for Trace.orchestration
    done: dict[tuple[str, str, str | None], int] = field(default_factory=dict)  # successful runs
    errors: dict[tuple[str, str, str | None], int] = field(default_factory=dict)  # runs that ended without a plan
    rounds: dict[tuple[str, str, str | None], int] = field(default_factory=dict)
    correction_rounds: int = 0
    last_findings: list[Finding] = field(default_factory=list)
    closed: set[str] = field(default_factory=set)  # incidents settled by execute()
    executed: bool = False
    failed: bool = False
    failure_text: str = ""
    audit_note: str = ""
    log: list[Action] = field(default_factory=list)  # every Action of the trace, in order
    logged_reads: set[int] = field(default_factory=set)
    summary: str | None = None
    reason: str | None = None
    finished: bool = False


def cs(ctx: Any) -> CoordState:
    if not isinstance(ctx, EventContext):
        raise TypeError("coordinator tools need an EventContext")
    st = ctx.state.get("coord")
    if st is None:
        st = ctx.state["coord"] = CoordState()
    return st


def opts(ctx: EventContext) -> dict[str, Any]:
    return ctx.state.setdefault("opts", {})


def tl(ctx: EventContext):
    return ctx.timeline


def open_incidents(ctx: EventContext) -> list[str]:
    st = cs(ctx)
    return [
        i
        for i, s in ctx.incidents.items()
        if s.category in ACTIONABLE and i not in st.dropped and i not in st.escalated and i not in st.closed
    ]


def _hint(ctx: EventContext, i: str) -> str:
    """What settles incident `i` next (used by `unsettled` and `finish`)."""
    st, cat = cs(ctx), ctx.incidents[i].category
    if cat == "noise":
        return "drop_noise or escalate (it names a record)"
    if cat not in ACTIONABLE:
        return "escalate"
    todo = [f"delegate {t}" for t, j in _per_incident_missing(ctx) if j == i]
    if st.needs_human.get(i):
        return "escalate (needs_human)"
    return "; ".join(todo) if todo else "validate_plan, then execute (or escalate it)"


def unsettled(ctx: EventContext) -> list[tuple[str, str]]:
    """Every registered incident must be in exactly one of dropped / escalated / closed. Returns (id, what settles it)."""
    st = cs(ctx)
    return [
        (i, _hint(ctx, i))
        for i in ctx.incidents
        if i not in st.dropped and i not in st.escalated and i not in st.closed
    ]


def _brief(spec) -> dict[str, Any]:
    keys = (
        "category", "plant_id", "part_id", "supplier_id", "shipment_id", "lot_id", "orig_eta", "new_eta",
        "outage_start", "outage_end", "build_window_start", "build_window_end", "confidence",
    )  # fmt: skip
    d = spec.model_dump(mode="json")
    out = {k: d[k] for k in keys if d.get(k) is not None}
    out["incident_id"] = spec.incident_id
    return out


def _clip(v: Any, n: int = 500) -> Any:
    s = str(v)
    return v if len(s) <= n else s[:n] + "...(clipped)"


def _log(ctx: EventContext, a: Action) -> None:
    st = cs(ctx)
    a.seq = len(st.log) + 1
    st.log.append(a)
    ctx.state["sink"].emit("action", ctx.event_id, a.model_dump(mode="json"))


def _log_planning_reads(ctx: EventContext) -> None:
    st = cs(ctx)
    for r in ctx.plan.reads:
        if id(r) not in st.logged_reads:
            st.logged_reads.add(id(r))
            _log(ctx, r)


# ---------------------------------------------------------------------------------------------------------------
# understanding: register_incidents / resolve_entity / resolve_date
# ---------------------------------------------------------------------------------------------------------------


class RawIncidentIn(RawIncident):
    """RawIncident that also accepts a bare string for a date field (models often drop the {text, iso} wrapper)."""

    @model_validator(mode="before")
    @classmethod
    def _bare_dates(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = {k: ({"text": v} if isinstance(v, str) and k in DATE_FIELDS else v) for k, v in data.items()}
        return data


DATE_FIELDS = {
    "original_eta", "new_eta", "outage_start", "outage_end", "build_window_start", "build_window_end",
}  # fmt: skip


class RegisterArgs(BaseModel):
    incidents: list[RawIncidentIn] = Field(
        description="Your understanding of the message: one entry per distinct incident, in the order of the text"
    )


@tool(
    "register_incidents",
    {CO},
    "control",
    "UNDERSTANDING output. Register the incidents you read in the message (category, verbatim evidence, entity "
    "mentions and date phrases exactly as written, confidence, reason). Code resolves names to ids and phrases to "
    "dates (aliases, tables, calendar, closed-set tie-break) and returns, per incident, the resolved ids/dates, "
    "confidence, ambiguities and needs_human. Call this first. You may call it again only before any delegation.",
)
def register_incidents(ctx: EventContext, args: RegisterArgs) -> dict[str, Any]:
    st = cs(ctx)
    if not args.incidents:
        raise ValueError("register at least one incident (a message with nothing operational is one `noise` item)")
    if st.done or st.escalated or st.executed:
        raise ValueError("incidents are already registered and work has started; continue with the current ones")
    cfg = agent_config(CO)
    o = opts(ctx)
    calls_before = len(tl(ctx).llm_calls)
    tiebreak = (
        make_tiebreak(ctx.world, tl(ctx).llm_calls, provider=cfg.provider, model=cfg.model)
        if o.get("use_tiebreak", True)
        else None
    )
    ctx.incidents.clear()
    st.raws.clear()
    st.needs_human.clear()
    st.dropped.clear()
    st.noise_refused.clear()
    out = []
    for n, raw in enumerate(args.incidents, 1):
        res = build_incident(
            ctx.world, ctx.index, raw, event_id=ctx.event_id, n=n, event_text=ctx.event["text"], tiebreak=tiebreak
        )
        spec = res.spec
        ctx.incidents[spec.incident_id] = spec
        st.raws[spec.incident_id] = raw
        st.needs_human[spec.incident_id] = res.needs_human
        for step in spec.resolution_steps:
            if step.method in {"data_snap", "fuzzy", "llm"}:
                tl(ctx).step(
                    CO,
                    "gate",
                    f"{step.entity_type} {step.mention!r} -> {step.chosen} via {step.method}: {step.note or ''}".strip(),
                )
        item = _brief(spec)
        item["needs_human"] = res.needs_human
        item["actionable"] = spec.category in ACTIONABLE and not res.needs_human
        item["ambiguities"] = [
            {
                "field": a.field,
                "issue": a.issue,
                "blocking": a.blocking,
                **({"options": a.options} if a.options else {}),
            }
            for a in spec.ambiguities
        ]
        out.append(item)
    for call in tl(ctx).llm_calls[calls_before:]:  # tie-break calls belong to the coordinator
        if call.purpose == "resolve":
            tl(ctx).usage(CO, call.model, call.cost_usd, call.attempts)
    return {
        "count": len(out),
        "incidents": out,
        "next": "Gate each incident: drop_noise (noise only), escalate (unconfirmed / needs_human / unresolved), or "
        "delegate the actionable ones.",
    }


class ResolveEntityArgs(BaseModel):
    type: Literal["plant", "part", "supplier", "shipment", "lot"]
    mention: str = Field(description="The name or id as written in the message")


@tool(
    "resolve_entity",
    {CO},
    "code",
    "Retry resolving ONE mention against the tables (ids, names, aliases, nicknames, closed-set model pick for "
    "plant/part/supplier). Returns the candidates and the pick (null when unresolved). Does not change registered "
    "incidents; if the pick fixes a problem, call register_incidents again with the corrected mention.",
)
def resolve_entity(ctx: EventContext, args: ResolveEntityArgs) -> dict[str, Any]:
    index: EntityIndex = ctx.index
    step = index.resolve(args.mention, args.type)
    note = step.note
    if step.chosen is None and args.type in {"plant", "part", "supplier"} and opts(ctx).get("use_tiebreak", True):
        cfg = agent_config(CO)
        before = len(tl(ctx).llm_calls)
        pick, conf, why = make_tiebreak(ctx.world, tl(ctx).llm_calls, provider=cfg.provider, model=cfg.model)(
            args.type, args.mention, ctx.event["text"]
        )
        for call in tl(ctx).llm_calls[before:]:
            tl(ctx).usage(CO, call.model, call.cost_usd, call.attempts)
        if pick is not None and conf >= 0.9:
            return {"type": args.type, "mention": args.mention, "candidates": [pick], "pick": pick,
                    "method": "llm", "note": f"closed-set model pick at {conf:.2f}: {why}"}  # fmt: skip
        note = f"not resolved; model pick rejected ({why})"
    return {"type": args.type, "mention": args.mention, "candidates": step.candidates, "pick": step.chosen,
            "method": step.method, "note": note}  # fmt: skip


class ResolveDateArgs(BaseModel):
    phrase: str = Field(description="The date phrase as written, e.g. 'next Friday' or 'Monday Mar 22'")


@tool(
    "resolve_date",
    {CO},
    "code",
    "Retry resolving ONE date phrase from today (Monday 2027-03-08): returns the ISO date, whether it is a working day "
    "in the planning calendar, and how it was derived.",
)
def resolve_date(ctx: EventContext, args: ResolveDateArgs) -> dict[str, Any]:
    p = parse_date_phrase(args.phrase)
    out: dict[str, Any] = {"phrase": args.phrase, "date": p.value.isoformat() if p.value else None, "note": p.note,
                           "weekday_mismatch": p.weekday_mismatch}  # fmt: skip
    if p.value:
        out["weekday"] = p.value.strftime("%A")
        out["working_day"] = ctx.world.calendar.is_working_day(p.value)
        if not out["working_day"]:
            nxt = ctx.world.calendar.on_or_after(p.value)
            out["next_working_day"] = nxt.isoformat() if nxt else None
    return out


# ---------------------------------------------------------------------------------------------------------------
# gate: drop_noise / escalate
# ---------------------------------------------------------------------------------------------------------------


def _incident(ctx: EventContext, incident_id: str):
    spec = ctx.incidents.get(incident_id)
    if spec is None:
        raise ValueError(f"unknown incident_id {incident_id!r}; registered: {list(ctx.incidents)}")
    return spec


def _names_a_record(raw: RawIncident) -> bool:
    """The noise guard (handbook rules 7/8, PLAN_V2 §4.1.3): a shipment or lot id, or a plant together with any date."""
    has_date = any(
        getattr(raw, f) is not None
        for f in ("original_eta", "new_eta", "outage_start", "outage_end", "build_window_start", "build_window_end")
    )
    return bool(raw.shipment_id or raw.lot_id or (raw.plant and has_date))


class DropNoiseArgs(BaseModel):
    incident_id: str
    reason: str


@tool(
    "drop_noise",
    {CO},
    "control",
    "Mark a `noise` incident as having nothing to do with operations: no actions, no writes, recorded with your reason "
    "(handbook rule 7). Refused if the item names a shipment or lot id, or a plant together with a date: then a human "
    "must look, so escalate instead.",
)
def drop_noise(ctx: EventContext, args: DropNoiseArgs) -> dict[str, Any]:
    st = cs(ctx)
    spec = _incident(ctx, args.incident_id)
    if st.executed or args.incident_id in st.closed:
        raise ValueError("already settled")
    if spec.category != "noise":
        raise ValueError(
            f"{args.incident_id} is registered as {spec.category}, not noise. If it is not actionable, use escalate."
        )
    raw = st.raws[args.incident_id]
    if _names_a_record(raw) or st.needs_human.get(args.incident_id):
        st.noise_refused.add(args.incident_id)
        return {
            "refused": True,
            "why": "this item names a real record (a shipment/lot id, or a plant together with dates). It must not be "
            "dropped silently: call escalate for it (what_would_make_it_actionable: confirm the details).",
        }
    st.dropped[args.incident_id] = args.reason
    tl(ctx).step(CO, "decision", f"{args.incident_id}: noise, no action. {args.reason}")
    return {"dropped": args.incident_id, "writes": 0}


def _resolved_text(spec) -> str:
    b = _brief(spec)
    return ", ".join(f"{k} {v}" for k, v in b.items() if k not in ("incident_id", "confidence")) or spec.category


def _escalation_ground(ctx: EventContext, i: str) -> str | None:
    """The machine-verifiable circumstance (PLAN_V2 4.1) that allows `escalate`, or None when none holds."""
    st, spec = cs(ctx), ctx.incidents[i]
    raw = st.raws.get(i)
    if spec.category not in ACTIONABLE:
        return f"category {spec.category}"
    if st.needs_human.get(i):
        return "needs_human"
    if any(a.blocking for a in spec.ambiguities) or (raw is not None and raw.confidence < 0.7):
        return "unresolved id/date or low confidence"
    if i in st.noise_refused:
        return "drop_noise refused"
    if any(f.incident_id in (i, None) for f in blocking(st.last_findings)):
        return "blocking validator findings"
    if any(n >= MAX_ROUNDS and k[2] in (i, None) for k, n in st.rounds.items()):
        return "correction rounds exhausted"
    return None


class EscalateArgs(BaseModel):
    incident_id: str
    reason: str = Field(description="Why this incident cannot be acted on")
    what_would_make_it_actionable: str = Field(description="What a human should confirm or supply")


@tool(
    "escalate",
    {CO},
    "control",
    "Hand ONE incident to a human (the enterprise `escalate` tool; not a write). Queues exactly one escalate action "
    "for that incident and forbids any write for it. Code REFUSES it unless a circumstance holds: unconfirmed/other "
    "category, needs_human, a required id/date unresolved or confidence < 0.7, a noise item that names a real record "
    "(drop_noise refused), or blocking validator findings / exhausted correction rounds. A confirmed, fully resolved "
    "incident is never escalated for a nickname or an odd date phrase. Idempotent per incident.",
)
def escalate(ctx: EventContext, args: EscalateArgs) -> dict[str, Any]:
    st = cs(ctx)
    spec = _incident(ctx, args.incident_id)
    if args.incident_id in st.escalated:
        return {"noop": True, "note": f"{args.incident_id} is already escalated (one escalate per incident)."}
    if args.incident_id in st.closed:
        raise ValueError(f"{args.incident_id} was already executed; it cannot be escalated any more")
    ground = _escalation_ground(ctx, args.incident_id)
    if ground is None:
        raise ValueError(
            f"{args.incident_id} is confirmed and fully resolved ({_resolved_text(spec)}); the guard forbids "
            "escalating a confirmed incident for a nickname or an odd date phrase. Continue with "
            "delegate/validate_plan/execute. If the report is in fact unconfirmed, re-register it with category "
            "unconfirmed."
        )
    raw = st.raws.get(args.incident_id)
    evidence = f' "{raw.evidence}".' if raw else ""
    text = (
        f"{spec.incident_id} ({spec.category}, source: {ctx.event.get('source', '')}):{evidence} "
        f"Not actionable: {args.reason} What would make it actionable: {args.what_would_make_it_actionable} "
        "No operational action taken."
    )
    _queue_escalation(ctx, spec.incident_id, [spec.incident_id], text, "Escalated to a human: not safe to act on")
    st.dropped.pop(args.incident_id, None)
    _withdraw(ctx, args.incident_id)
    tl(ctx).step(CO, "decision", f"{args.incident_id}: escalated. {args.reason}", data={"reason": text})
    return {"escalated": args.incident_id, "writes": 0, "note": "queued; no write will be sent for this incident"}


def _queue_escalation(
    ctx: EventContext,
    incident_id: str | None,
    incident_ids: list[str],
    text: str,
    justification: str,
    *,
    settle: bool = True,
) -> None:
    st = cs(ctx)
    st.esc_queue.append(
        Action(
            seq=0,
            incident_id=incident_id,
            incident_ids=incident_ids,
            agent="coordinator",
            tool="escalate",
            args={"reason": text},
            justification=f"{justification} (handbook rules 7/8: no operational action for it)",
            path_ids=[],
        )
    )
    st.escalations.append({"incident_id": incident_id or ctx.event_id, "reason": text})
    if incident_id and settle:
        st.escalated[incident_id] = text


def _withdraw(ctx: EventContext, incident_id: str) -> None:
    """Remove everything staged for an escalated incident; event-wide results are stale and must be rerun."""
    st, pl = cs(ctx), ctx.plan
    for d in (pl.results, pl.finals):
        for k in [k for k in d if k[2] == incident_id]:
            del d[k]
    for k in [k for k in pl.staged if k[2] == incident_id]:
        del pl.staged[k]
    ctx.moves.pop(incident_id, None)
    ctx.impacts.pop(incident_id, None)
    ctx.state.get("proposed", set()).discard(incident_id)
    wide = [k for k in pl.results if k[2] is None]
    for k in wide:
        pl.results.pop(k, None)
        pl.finals.pop(k, None)
        st.done.pop(k, None)
        st.rounds.pop(k, None)
    for k in [k for k in pl.staged if k[2] is None]:
        del pl.staged[k]
    for k in [k for k in st.done if k[2] == incident_id]:
        del st.done[k]
    _replay_moves(ctx)


# ---------------------------------------------------------------------------------------------------------------
# delegate
# ---------------------------------------------------------------------------------------------------------------


class DelegateArgs(BaseModel):
    agent: Literal["supply_chain_planner", "dealer_network", "customer_care_quality"]
    task: Literal["reschedule", "quality_hold", "dealer_comms", "loaners"]
    incident_id: str | None = Field(
        default=None, description="Required for reschedule and quality_hold, omit otherwise"
    )
    payload: dict[str, Any] | None = Field(
        default=None, description="Extra notes for the specialist; for a correction round the validator findings"
    )


def _wide_missing(ctx: EventContext) -> list[str]:
    """Event-wide tasks still to run (or to re-run after a withdrawal) for the confirmed incidents."""
    if not open_incidents(ctx):
        return []
    need = []
    quality = [i for i in open_incidents(ctx) if ctx.incidents[i].category == "quality_hold"]
    if (ctx.moved_po_ids() or quality) and ("dealer_network", "dealer_comms", None) not in ctx.plan.results:
        need.append("dealer_comms")
    if ctx.affected_co_ids() and ("customer_care_quality", "loaners", None) not in ctx.plan.results:
        need.append("loaners")
    return need


def _per_incident_missing(ctx: EventContext) -> list[tuple[str, str]]:
    miss = []
    for i in open_incidents(ctx):
        task = "reschedule" if ctx.incidents[i].category != "quality_hold" else "quality_hold"
        if (TASKS[task][0], task, i) not in ctx.plan.results:
            miss.append((task, i))
    return miss


def _findings_for(ctx: EventContext, task: str, incident_id: str | None) -> list[dict[str, Any]]:
    st = cs(ctx)
    rel = [f for f in blocking(st.last_findings) if f.rule in TASK_RULES[task]]
    if incident_id is not None:
        rel = [f for f in rel if f.incident_id in (incident_id, None)]
    return [{**f.model_dump(mode="json"), "expected": _clip(f.expected), "got": _clip(f.got)} for f in rel]


def _brief_text(ctx: EventContext, task: str, incident_id: str | None, payload: dict[str, Any]) -> str:
    if task == "reschedule":
        spec = ctx.incidents[incident_id]  # type: ignore[index]
        others = [i for i in ctx.incidents if i != incident_id and ctx.incidents[i].category in ACTIONABLE]
        return (
            f"Reschedule task for incident {incident_id}. Resolved incident: {_brief(spec)}. Find the production "
            "orders this incident affects (affected_builds), propose the earliest feasible slots (propose_slots) and "
            "submit the plan. Slots are shared with the other incidents of this event"
            + (f" ({', '.join(others)})" if others else "")
            + "; propose_slots knows the board."
        )
    if task == "quality_hold":
        spec = ctx.incidents[incident_id]  # type: ignore[index]
        return (
            f"quality_hold task for incident {incident_id}. Resolved incident: {_brief(spec)}. Match the lot "
            "(match_lot), find the affected vehicles, compose the hold and the owner contacts, and submit "
            f"(task=quality_hold, incident_id={incident_id}). The Dealer Network agent composes the stop-sales."
        )
    if task == "dealer_comms":
        q = payload.get("quality_incidents")
        return (
            f"dealer_comms task for the whole event {ctx.event_id}. {payload['moved_po_count']} production orders were "
            "moved (payload.moved_po_ids). Compose exactly one dealer.notify per affected dealer for ALL moved orders "
            "of all incidents together"
            + (
                "; for each quality incident in payload.quality_incidents compose the stop-sales for its in-stock "
                "vehicles by dealer"
                if q
                else ""
            )
            + ", then submit the dealer plan."
        )
    return (
        f"loaners task for the whole event {ctx.event_id}. payload.co_ids is the handle of the {payload['co_count']} "
        "customer orders of all moved production orders. Run eligible_customers, ONE loaner_availability read for all "
        "dealers, rank_and_assign, and submit (task=loaners). One shared pool per dealer across all incidents."
    )


def _payload(ctx: EventContext, task: str, incident_id: str | None) -> dict[str, Any]:
    if task in ("reschedule", "quality_hold"):
        return {"incident": _brief(ctx.incidents[incident_id])}  # type: ignore[index]
    if task == "dealer_comms":
        po = ctx.moved_po_ids()
        out: dict[str, Any] = {"moved_po_count": len(po), "moved_po_ids": stash(ctx, "moved_po_ids", po) if po else []}
        q = []
        for i in open_incidents(ctx):
            if ctx.incidents[i].category == "quality_hold":
                imp = _lot_impact(ctx, i)  # raises with a clear message if affected_vehicles never ran
                q.append(
                    {
                        "incident_id": i,
                        "in_stock_by_dealer": stash(ctx, "in_stock_by_dealer", imp.in_stock_by_dealer),
                        "in_stock_total": sum(len(v) for v in imp.in_stock_by_dealer.values()),
                    }
                )
        if q:
            out["quality_incidents"] = q
        return out
    cos = ctx.affected_co_ids()
    return {"co_count": len(cos), "co_ids": stash(ctx, "co_ids", cos)}


@tool(
    "delegate",
    {CO},
    "control",
    "Run a specialist agent on a task and get its result summary back. Tasks: `reschedule` (supply_chain_planner; one "
    "per supplier_delay/plant_outage incident), `quality_hold` (customer_care_quality; one per quality_hold incident), "
    "`dealer_comms` (dealer_network; ONCE per event, for all incidents), `loaners` (customer_care_quality; ONCE per "
    "event). Per-incident tasks first, in text order; event-wide tasks only after every confirmed incident has its "
    "per-incident result. A repeat of a task is allowed only as a correction round after validate_plan found problems "
    "(the findings are attached automatically; at most 2 rounds per task).",
)
def delegate(ctx: EventContext, args: DelegateArgs) -> dict[str, Any]:
    st = cs(ctx)
    if st.executed:
        raise ValueError("the event was already executed")
    agent_id, per_incident, cats = TASKS[args.task]
    if args.agent != agent_id:
        raise ValueError(f"task {args.task} belongs to {agent_id}, not {args.agent}")
    inc = args.incident_id if per_incident else None
    if per_incident:
        if inc is None:
            raise ValueError(f"task {args.task} needs incident_id")
        spec = _incident(ctx, inc)
        if inc in st.escalated or inc in st.dropped:
            raise ValueError(f"{inc} was {'escalated' if inc in st.escalated else 'dropped as noise'}: no work for it")
        if st.needs_human.get(inc) or spec.category not in cats:
            raise ValueError(
                f"{inc} ({spec.category}) is not actionable for {args.task}"
                + (" (needs_human: escalate it)" if st.needs_human.get(inc) else "")
            )
    else:
        if open_incidents(ctx) == []:
            raise ValueError("no confirmed incident is left to act on")
        waiting = [m[1] for m in _per_incident_missing(ctx)]
        if waiting:
            raise ValueError(
                f"event-wide tasks run after every confirmed incident has its result; still missing: {waiting}"
            )
        if args.task == "dealer_comms" and not (
            ctx.moved_po_ids() or any(ctx.incidents[i].category == "quality_hold" for i in open_incidents(ctx))
        ):
            raise ValueError("nothing to communicate: no production order moved and no quality incident")
        if args.task == "loaners" and not ctx.affected_co_ids():
            raise ValueError("no affected customer orders: loaners are not needed")
    key = (agent_id, args.task, inc)
    is_repeat = key in st.done
    findings: list[dict[str, Any]] = []
    if is_repeat:
        rounds = st.rounds.get(key, 0)
        if rounds >= MAX_ROUNDS:
            raise ValueError(
                f"this task already had {MAX_ROUNDS} correction rounds and still fails validation: escalate this "
                "incident" + (f" ({inc})" if inc else " (the incident(s) named in the findings)")
            )
        findings = _findings_for(ctx, args.task, inc)
        if not findings:
            raise ValueError(
                "a repeat is only allowed as a correction round carrying validator findings; run validate_plan first "
                "(there are no open findings for this task)"
            )
        st.rounds[key] = rounds + 1
        st.correction_rounds += 1
    elif st.errors.get(key, 0) >= 2:
        raise ValueError("this task failed twice without producing a plan: escalate this incident")

    payload = {**(args.payload or {}), **_payload(ctx, args.task, inc)}
    task_text = _brief_text(ctx, args.task, inc, payload)
    if findings:
        payload["findings"] = findings
        task_text = (
            f"CORRECTION ROUND {st.rounds[key]} of {MAX_ROUNDS}. Your previous plan failed the handbook validators "
            f"(see INPUT.findings: rule, expected, got). Fix exactly those problems with your tools and submit again "
            f"(a new submit replaces the old one). Original task: {task_text}"
        )
    spec_obj = SPECIALISTS[agent_id]
    tline = tl(ctx)
    tline.step(
        CO, "message", task_text, from_agent=CO, to_agent=agent_id, data={"task": args.task, "incident_id": inc}, task=args.task,
    )  # fmt: skip
    res = run_agent(spec_obj, task_text, payload, ctx, tline, task_name=args.task)
    submitted = ctx.plan.results.get(key)
    if res.error or res.final is None or submitted is None:
        st.errors[key] = st.errors.get(key, 0) + 1
        why = res.error or "the agent finished without submitting a plan"
        tline.step(
            agent_id,
            "message",
            f"{spec_obj.display_name} failed: {why}",
            from_agent=agent_id,
            to_agent=CO,
            task=args.task,
        )
        return {"error": f"{spec_obj.display_name} produced no plan: {why}", "turns": res.turns,
                "hint": "retry once, otherwise escalate the incident"}  # fmt: skip
    st.done[key] = st.done.get(key, 0) + 1
    out = {
        "agent": agent_id, "task": args.task, "incident_id": inc, "actions_count": submitted.actions_count,
        "findings": submitted.findings, "reasoning_summary": submitted.reasoning_summary,
        "paths_count": submitted.paths_count, "turns": res.turns, "llm_calls": res.llm_calls,
        "cost_usd": res.cost_usd, "correction_round": st.rounds.get(key, 0),
    }  # fmt: skip
    tline.step(
        agent_id, "message",
        f"{submitted.reasoning_summary or 'plan submitted'} ({submitted.actions_count} actions)",
        from_agent=agent_id, to_agent=CO, data={k: out[k] for k in ("task", "incident_id", "actions_count", "findings")},
        task=args.task,
    )  # fmt: skip
    return out


# ---------------------------------------------------------------------------------------------------------------
# validate_plan
# ---------------------------------------------------------------------------------------------------------------


def run_validators(ctx: EventContext) -> list[Finding]:
    st = cs(ctx)
    findings = validate(
        ctx.world,
        ctx.graph,
        ctx.incidents,
        ctx.plan.actions(),
        escalated=set(st.escalated),
        pools=dict(ctx.state["pools"]) if ctx.state.get("pools") else None,
        policy=ctx.policy,
    )
    st.last_findings = findings
    return findings


class NoArgs(BaseModel):
    pass


@tool(
    "validate_plan",
    {CO},
    "code",
    "Run the handbook validators (rules 1-10 as code) over everything the specialists submitted so far. Returns the "
    "findings grouped by incident: `blocking` ones must be fixed (correction round via delegate, or escalate the "
    "incident), `warnings` are recorded only. Also lists tasks that are still missing.",
)
def validate_plan(ctx: EventContext, args: NoArgs) -> dict[str, Any]:
    findings = run_validators(ctx)
    by_inc: dict[str, list[dict[str, Any]]] = {}
    for f in findings:
        by_inc.setdefault(f.incident_id or "event", []).append(
            {"rule": f.rule, "severity": f.severity, "expected": _clip(f.expected), "got": _clip(f.got)}
        )
    bad = blocking(findings)
    missing = [m[1] + ":" + m[0] for m in _per_incident_missing(ctx)] + _wide_missing(ctx)
    for f in findings:
        if f.severity == "warning":
            tl(ctx).step(CO, "note", f"validator warning: {f.short()}")
    tl(ctx).step(
        CO,
        "decision",
        f"Plan validated: {len(bad)} blocking finding(s), {len(findings) - len(bad)} warning(s)"
        + (f"; missing tasks {missing}" if missing else ""),
        data={"blocking": len(bad)},
    )
    return {"ok": not bad and not missing, "blocking": len(bad), "warnings": len(findings) - len(bad),
            "by_incident": by_inc, "missing_tasks": missing}  # fmt: skip


# ---------------------------------------------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------------------------------------------


def _escalate_open(ctx: EventContext, reason: str, justification: str = "Guardrail: could not act safely") -> list[str]:
    """Settle every unsettled incident: plain noise that names no record is dropped, everything else is escalated."""
    st = cs(ctx)
    ids: list[str] = []
    for i, _ in unsettled(ctx):
        raw = st.raws.get(i)
        if (
            ctx.incidents[i].category == "noise"
            and raw is not None
            and not _names_a_record(raw)
            and not st.needs_human.get(i)
        ):
            st.dropped[i] = "loop ended; nothing names a record"
            tl(ctx).step(CO, "decision", f"{i}: noise, no action. {st.dropped[i]}")
            continue
        ids.append(i)
        _queue_escalation(
            ctx, i, [i], f'{i} ({ctx.incidents[i].category}): "{raw.evidence if raw else ""}". {reason} '
            "No operational action taken.", justification,
        )  # fmt: skip
    return ids


def _verification_reads(ctx: EventContext, writes: list[Action]) -> list[Action]:
    w = ctx.world
    slots = sorted(
        {
            (
                a.args.get("to_plant_id") or w.production_orders[a.args["production_order_id"]].plant_id,
                a.args["new_date"],
            )
            for a in writes
            if a.tool in MOVES
        }
    )
    return [
        Action(
            seq=0,
            agent="supply_chain_planner",
            tool="mes.get_schedule",
            args={"plant_id": p, "date": d},
            justification="Free read: confirm the target slot is free in the live world before any write",
            path_ids=[p],
        )  # fmt: skip
        for p, d in slots
    ]


def _fresh(ctx: EventContext, reads: list[Action]) -> str | None:
    """None when the live world matches the baseline the plan was computed from, else why not."""
    board = SlotBoard(ctx.world)
    for a in reads:
        r = a.result
        if r is None or not r.ok:
            return f"live read {a.tool} {a.args} failed: {r.error if r else 'no result'}"
        idx = ctx.world.calendar.idx(date.fromisoformat(a.args["date"]))
        if (r.response or {}).get("free_slots") != board.free(a.args["plant_id"], idx):
            return f"live world differs from the planning baseline at {a.tool} {a.args}: {r.response}"
    for d, n in (ctx.state.get("pools") or {}).items():
        if ctx.world.loaner_pool.get(d) != n:
            return f"live loaner pool of {d} is {n}, the baseline says {ctx.world.loaner_pool.get(d)}"
    return None


def _auditor_digest(ctx: EventContext) -> str:
    w = ctx.world
    acts = ctx.plan.actions()
    plans = []
    for i, s in ctx.incidents.items():
        if i not in open_incidents(ctx):
            continue
        mine = [a for a in acts if i in (a.incident_ids or [a.incident_id])]
        ms = ctx.moves.get(i)
        q = ctx.impacts.get(i) if s.category == "quality_hold" else None
        plans.append(
            SimpleNamespace(
                spec=s,
                moves=ms.moves if ms else [],
                actions=[
                    a for a in mine if a.tool in MOVES | {"quality.hold_lot", "dealer.stop_sale", "crm.notify_customer"}
                ],
                stopped=sum(len(v) for v in q.in_stock_by_dealer.values()) if q else 0,
                unsold_dealers=len(q.in_stock_by_dealer) if q else 0,
                owners=len(q.owners) if q else 0,
            )
        )
    care = [a for a in acts if a.tool in {"dealer.notify", "crm.assign_loaner"}]
    return plan_digest(w, plans, care, list(cs(ctx).escalated.values()))


def _seen(ctx: EventContext, a: Action, res: ToolResult) -> None:
    a.result = res
    a.transport = getattr(ctx.executor, "transport", None)


def _incs(a: Action) -> list[str]:
    return list(a.incident_ids) or ([a.incident_id] if a.incident_id else [])


def _po_incident(ctx: EventContext) -> dict[str, str]:
    return {m.po.id: inc for inc, ms in ctx.moves.items() for m in ms.moves}


def _trim_notice(ctx: EventContext, a: Action, keep: list[str], bad_pos: set[str]) -> None:
    """A dealer.notify that loses orders of failed moves is REGENERATED (ids and message) from the moves that went
    through, never just filtered: the old message would still describe the removed orders."""
    w = ctx.world
    moves = [m for ms in ctx.moves.values() for m in ms.moves if m.po.id not in bad_pos]
    cause = {m.po.id: ms.cause for ms in ctx.moves.values() for m in ms.moves}
    acts = plan_care(
        w, moves, {}, incident_id=None, cause=cause, policy=ctx.policy, co_ids=set(keep), include_loaners=False
    )
    new = next(x for x in acts if x.args["dealer_id"] == a.args["dealer_id"])
    po_inc = _po_incident(ctx)
    incs = list(dict.fromkeys(po_inc[w.customer_orders[c].production_order_id] for c in new.args["customer_order_ids"]))
    a.args = new.args
    a.incident_ids, a.incident_id = incs, (incs[0] if len(incs) == 1 else None)
    a.justification += " (recomputed after a failed move)"


def _recompute_loaners(
    ctx: EventContext, group: list[Action], bad_pos: set[str]
) -> tuple[list[Action], list[Action], list[tuple[Action, str]]]:
    """Loaners over the moves that went through and the recorded pools (the pool capacity a failed move leaves unused
    goes to the next entitled customer). Returns (to send in order, newly created, (not sent, why))."""
    eligible = ctx.state.get("loaner_eligible")
    if eligible is None:
        return group, [], []
    w, po_inc = ctx.world, _po_incident(ctx)
    moves = [m for ms in ctx.moves.values() for m in ms.moves if m.po.id not in bad_pos]
    acts = plan_care(
        w, moves, dict(ctx.state.get("pools") or {}), incident_id=None, cause="", policy=ctx.policy,
        loaner_given_to=set(), co_ids=set(eligible), include_notices=False,
    )  # fmt: skip
    staged = {x.args["customer_order_id"]: x for x in group}
    send: list[Action] = []
    extra: list[Action] = []
    for x in acts:
        co = x.args["customer_order_id"]
        if co in staged:
            send.append(staged.pop(co))
            continue
        (n,) = _stamp([x], CCQ, [po_inc[w.customer_orders[co].production_order_id]])
        n.justification += " (recomputed after a failed move)"
        send.append(n)
        extra.append(n)
    dropped = [
        (x, "skipped: dependency failed" if w.customer_orders[co].production_order_id in bad_pos
         else "skipped: recomputed after a failed move")
        for co, x in staged.items()
    ]  # fmt: skip
    if extra and ctx.twin is not None:  # law 5: nothing is sent that the twin did not rehearse
        for x, r in zip(extra, ctx.twin.rehearse(extra), strict=True):
            x.rehearsal = r
            if not r.ok:
                send.remove(x)
                dropped.append((x, f"skipped: rehearsal failed: {r.error}"))
    return send, extra, dropped


def _trim_quality(ctx: EventContext, a: Action, good: list[str]) -> bool:
    """Rebuild a merged stop-sale / owner contact from the incidents whose hold succeeded. False = nothing remains."""
    w = ctx.world
    if a.tool == "dealer.stop_sale":
        dealer, want = a.args["dealer_id"], set(a.args["vins"])
        surv = {i: want & set(getattr(ctx.impacts.get(i), "in_stock_by_dealer", {}).get(dealer, [])) for i in good}
        surv = {i: v for i, v in surv.items() if v}
        if not surv:
            return False
        first = next(iter(surv))
        impact = replace(
            ctx.impacts[first], in_stock_by_dealer={dealer: sorted(set().union(*surv.values()))}, owners={}
        )
        new = next(x for x in plan_quality(w, impact, incident_id=first, reason=_quality_reason(ctx, first))
                   if x.tool == "dealer.stop_sale")  # fmt: skip
    else:
        cust = a.args["customer_id"]
        req = ctx.state.get("owner_req", {})
        surv = {}
        for i in good:
            vins = req.get(i, {}).get(cust) or getattr(ctx.impacts.get(i), "owners", {}).get(cust)
            if vins:
                surv[i] = set(vins)
        if not surv:
            return False
        first = next(iter(surv))
        impact = replace(ctx.impacts[first], in_stock_by_dealer={}, owners={cust: sorted(set().union(*surv.values()))})
        new = next(x for x in plan_quality(w, impact, incident_id=first, reason=_quality_reason(ctx, first))
                   if x.tool == "crm.notify_customer")  # fmt: skip
    a.args = new.args
    a.incident_ids, a.incident_id = list(surv), (first if len(surv) == 1 else None)
    a.justification += " (recomputed after a failed hold)"
    return True


def _run_writes(ctx: EventContext, writes: list[Action]) -> tuple[list[Action], list[Action], list[Action]]:
    """Send the writes in phase order. Returns (failed, skipped, unknown). A failed move blocks what depends on it:
    notices are regenerated without its customer orders, loaners are recomputed over the moves that went through,
    a move into a slot that is still full (its occupant never left) is skipped, and merged stop-sales / owner
    contacts are rebuilt from the holds that succeeded. Recomputed loaners are appended to `writes` (in place)."""
    w = ctx.world
    failed: list[Action] = []
    skipped: list[Action] = []
    unknown: list[Action] = []
    bad_pos: set[str] = set()
    bad_holds: set[str] = set()
    board = SlotBoard(w)  # live occupancy as the writes land; failed/skipped moves leave their PO where it is
    halted = False
    loaners_checked = False

    def skip(a: Action, why: str) -> None:
        a.skipped = True
        a.transport = getattr(ctx.executor, "transport", None)
        a.result = ToolResult(ok=False, error=why, outcome="failed")
        skipped.append(a)
        if a.tool in MOVES:
            bad_pos.add(w.production_orders[a.args["production_order_id"]].id)
        if a.tool == "quality.hold_lot":
            bad_holds.update(_incs(a))
        _log(ctx, a)

    pending = list(writes)
    while pending:
        a = pending.pop(0)
        if halted:
            skip(a, "skipped: event stopped after an unknown outcome")
            continue
        if a.tool == "crm.assign_loaner" and not loaners_checked:
            loaners_checked = True
            if bad_pos:  # recompute before the first loaner write (phase 3)
                group = [a, *[x for x in pending if x.tool == "crm.assign_loaner"]]
                rest = [x for x in pending if x.tool != "crm.assign_loaner"]
                send, extra, dropped = _recompute_loaners(ctx, group, bad_pos)
                writes.extend(extra)
                for x, why in dropped:
                    skip(x, why)
                pending = [*send, *rest]
                continue
        dep, why = False, "skipped: dependency failed"
        to_plant, to_idx = "", -1
        if a.tool in MOVES:
            po = w.production_orders[a.args["production_order_id"]]
            to_plant = a.args.get("to_plant_id") or po.plant_id
            to_idx = w.calendar.idx(date.fromisoformat(a.args["new_date"]))
            if board.free(to_plant, to_idx) <= 0:
                dep, why = True, "skipped: target slot full after an earlier failed move"
        elif a.tool == "dealer.notify":
            orig = a.args["customer_order_ids"]
            keep = [c for c in orig if w.customer_orders[c].production_order_id not in bad_pos]
            if not keep:
                dep = True
            elif len(keep) < len(orig):
                _trim_notice(ctx, a, keep, bad_pos)
        elif a.tool == "crm.assign_loaner":
            dep = w.customer_orders[a.args["customer_order_id"]].production_order_id in bad_pos
        elif a.tool in {"dealer.stop_sale", "crm.notify_customer"}:
            incs = _incs(a)
            good = [i for i in incs if i not in bad_holds]
            if incs and not good:
                dep = True
            elif incs and len(good) < len(incs) and not _trim_quality(ctx, a, good):
                dep = True
        if dep:
            skip(a, why)
            continue
        res = ctx.executor.call(ctx.event_id, a.tool, a.args)
        _seen(ctx, a, res)
        _log(ctx, a)
        if res.ok:
            if a.tool in MOVES and a.args["production_order_id"] in board.loc:
                board.move(a.args["production_order_id"], to_plant, to_idx)
            continue
        if res.outcome == "unknown":
            unknown.append(a)
            halted = True
            tl(ctx).step(CO, "execute", f"{a.tool} outcome UNKNOWN ({res.error}); stopping the event, no retry")
        else:
            failed.append(a)
            tl(ctx).step(CO, "execute", f"{a.tool} failed ({res.error}); not retried, dependents are skipped")
        if a.tool in MOVES:
            bad_pos.add(w.production_orders[a.args["production_order_id"]].id)
        if a.tool == "quality.hold_lot":
            bad_holds.update(_incs(a))
    return failed, skipped, unknown


def flush_escalations(ctx: EventContext) -> None:
    """Send every queued `escalate` (after the operational work, last in the trace)."""
    st = cs(ctx)
    _log_planning_reads(ctx)
    while st.esc_queue:
        a = st.esc_queue.pop(0)
        a.rehearsal = ctx.twin.rehearse([a])[0] if ctx.twin is not None else Rehearsal(ok=True)
        _seen(ctx, a, ctx.executor.call(ctx.event_id, "escalate", a.args))
        _log(ctx, a)
        tl(ctx).step(CO, "execute", f"escalate: {a.args['reason'][:300]}", tool="escalate", transport=a.transport)


def _desc(a: Action) -> str:
    args = ", ".join(f"{k}={_clip(v, 60)}" for k, v in a.args.items() if k != "message")
    return f"{a.tool}({args})" + (f" -> {a.result.error}" if a.result and a.result.error else "")


@tool(
    "execute",
    {CO},
    "control",
    "Prove and act. Validators again, then the digital-twin rehearsal of the whole plan, the independent audit, a "
    "live-freshness check, and only then the writes through the MCP client in phase order (moves, notices, loaners, "
    "holds, stop-sales, owner contacts). Refused while blocking findings exist or a needed task is missing. A failed "
    "write is not retried: its dependents are skipped and the event is escalated with done/failed/skipped.",
)
def execute(ctx: EventContext, args: NoArgs) -> dict[str, Any]:
    st = cs(ctx)
    if st.executed:
        raise ValueError("already executed")
    ids = open_incidents(ctx)
    if not ids:
        raise ValueError("nothing to execute: every incident is noise or escalated. Call finish.")
    unrun = [i for i in ids if st.needs_human.get(i)]
    if unrun:
        raise ValueError(f"{unrun} need a human: escalate them first")
    pending = [f"{i}:{t}" for t, i in _per_incident_missing(ctx)] + _wide_missing(ctx)
    if pending:
        raise ValueError(f"tasks missing, delegate them first: {pending}")
    bad = blocking(run_validators(ctx))
    if bad:
        raise ValueError("blocking validator findings, fix or escalate: " + "; ".join(f.short()[:300] for f in bad[:5]))

    _log_planning_reads(ctx)
    for (
        r
    ) in ctx.plan.reads:  # a failed or unknown planning read means the plan rests on nothing: abort before any write
        res = r.result
        if res is None or not res.ok or res.outcome in {"failed", "unknown"}:
            why = f"A live read failed during planning ({r.tool} {r.args}: {res.error if res else 'no result'}); nothing executed"
            tl(ctx).step(CO, "execute", f"ABORT before any write: {why}")
            _escalate_open(ctx, why)
            flush_escalations(ctx)
            return {"status": "escalated", "writes_sent": 0, "why": why}
    writes = ctx.plan.actions()
    vreads = _verification_reads(ctx, writes)
    # 1. twin rehearsal of the full plan -------------------------------------------------------------------------
    rehearse = [*vreads, *writes, *st.esc_queue]
    results = ctx.twin.rehearse(rehearse)
    for a, r in zip(rehearse, results, strict=True):
        a.rehearsal = r
    broken = [(a, r) for a, r in zip(rehearse, results, strict=True) if not r.ok]
    tl(ctx).step(
        CO, "rehearse",
        f"Rehearsed {len(rehearse)} actions on the twin: {len(rehearse) - len(broken)} ok, {len(broken)} failed",
    )  # fmt: skip
    if broken:
        why = "; ".join(f"{_desc(a)}: {r.error}" for a, r in broken[:3])
        _escalate_open(ctx, f"Plan rejected by the twin rehearsal, nothing executed: {why}")
        flush_escalations(ctx)
        return {"status": "escalated", "writes_sent": 0, "why": f"rehearsal failed: {why}"}
    # 2. independent audit ---------------------------------------------------------------------------------------
    if opts(ctx).get("use_audit", True):
        acfg = agent_config("auditor")
        n0 = len(tl(ctx).llm_calls)
        verdict = audit(
            ctx.event["source"], ctx.event["text"], _auditor_digest(ctx), tl(ctx).llm_calls,
            provider=acfg.provider, model=acfg.model,
        )  # fmt: skip
        for call in tl(ctx).llm_calls[n0:]:
            tl(ctx).usage(CO, call.model, call.cost_usd, call.attempts)
        if verdict is None:
            tl(ctx).step(CO, "audit", "Auditor unavailable; continuing on the deterministic checks alone")
            st.audit_note = "auditor unavailable"
        else:
            hard = [c for c in verdict.concerns if c.severity == "blocking"]
            tl(ctx).step(
                CO, "audit",
                f"Auditor {'agrees' if verdict.agree and not hard else 'DISAGREES'}: {verdict.summary}"
                + "".join(f" [{c.severity}] rule {c.rule}: {c.issue}" for c in verdict.concerns),
            )  # fmt: skip
            st.audit_note = verdict.summary
            if hard:
                why = "Auditor disagreed, nothing executed: " + "; ".join(f"rule {c.rule}: {c.issue}" for c in hard)
                _escalate_open(ctx, why)
                flush_escalations(ctx)
                return {"status": "escalated", "writes_sent": 0, "why": why}
    # 3. live freshness (reads are free) ---------------------------------------------------------------------------
    for a in vreads:
        _seen(ctx, a, ctx.executor.call(ctx.event_id, a.tool, a.args))
        _log(ctx, a)
    stale = _fresh(ctx, vreads)
    if stale:
        tl(ctx).step(CO, "execute", f"ABORT before any write: {stale}")
        _escalate_open(ctx, f"The live world is not fresh, nothing executed: {stale}")
        flush_escalations(ctx)
        return {"status": "escalated", "writes_sent": 0, "why": stale}
    lot = any(ctx.incidents[i].category == "quality_hold" for i in ids)
    tl(ctx).step(
        CO, "execute",
        f"Freshness: {len(vreads)} slot reads, {len(ctx.state.get('pools') or {})} pool reads matched the baseline"
        + ("; quality holds have no read tool in this enterprise, lot state is not verifiable" if lot else ""),
    )  # fmt: skip
    # 4. writes ----------------------------------------------------------------------------------------------------
    failed, skipped, unknown = _run_writes(ctx, writes)
    st.executed = True
    done = [a for a in writes if ok(a)]
    ids_all = list(ids)
    tl(ctx).step(
        CO, "execute",
        f"Executed {len(done)}/{len(writes)} writes via {ctx.executor.name}: {len(failed)} failed, "
        f"{len(unknown)} unknown, {len(skipped)} skipped",
    )  # fmt: skip
    st.closed.update(ids_all)
    report: dict[str, Any] = {"status": "executed", "reads": len(vreads), "writes_ok": len(done),
                              "writes_failed": len(failed), "writes_unknown": len(unknown),
                              "writes_skipped": len(skipped), "by_tool": tool_counts(writes)}  # fmt: skip
    if failed or unknown or skipped:
        st.failed = True
        st.failure_text = (
            f"Execution stopped partway{' (unknown outcome, event halted)' if unknown else ''}; nothing was retried. "
            f"Done ({len(done)}): {tool_counts(writes)}. "
            f"Failed ({len(failed) + len(unknown)}): {[_desc(a) for a in [*failed, *unknown][:5]]}. "
            f"Skipped ({len(skipped)}): {dict(sorted(Counter(a.tool for a in skipped).items()))}. "
            "Please complete or reverse the remainder by hand."
        )
        hit = {i for a in [*failed, *unknown, *skipped] for i in _incs(a)}
        affected = [i for i in ids_all if i in hit] or ids_all
        for i in affected:
            st.partial[i] = st.failure_text
        _queue_escalation(ctx, affected[0], affected, st.failure_text, "A write failed during execution", settle=False)
        report["status"] = "failed"
        report["escalated"] = st.failure_text
    flush_escalations(ctx)
    return report


# ---------------------------------------------------------------------------------------------------------------
# finish + the factual draft
# ---------------------------------------------------------------------------------------------------------------


def status_of(ctx: EventContext) -> str:
    st = cs(ctx)
    if st.failed:
        return "failed"
    if any(a.writes and ok(a) for a in st.log):
        return "done"
    if ctx.incidents and all(s.category == "noise" for s in ctx.incidents.values()) and not st.escalated:
        return "noise"
    return "escalated"


def _partial_sentence(ctx: EventContext, i: str) -> str:
    mine = [a for a in cs(ctx).log if a.writes and i in _incs(a)]
    done = tool_counts(mine)
    bad = Counter(a.tool for a in mine if not ok(a) and not a.skipped)
    skp = Counter(a.tool for a in mine if a.skipped)
    return (
        f"{i}: executed partially — done {done or 'nothing'}; failed {dict(sorted(bad.items())) or 'nothing'}; "
        f"skipped {dict(sorted(skp.items())) or 'nothing'}; the remainder was escalated to a human."
    )


def draft(ctx: EventContext, error: str | None = None) -> tuple[str, str]:
    """Factual (summary, decision_reason) from the successful actions only."""
    st = cs(ctx)
    acts = st.log
    parts: list[str] = []
    for i, s in ctx.incidents.items():
        if i in st.escalated:
            parts.append(f"Escalated {i} to a human without operational change: {st.escalated[i][:300]}")
        elif i in st.dropped:
            parts.append(f"{i} is not an operational event: {st.dropped[i]}")
        elif i in st.partial:
            parts.append(_partial_sentence(ctx, i))
        elif s.category in ACTIONABLE and i in st.closed:
            parts.append(incident_sentence(ctx.world, s, acts))
    if st.failed:
        parts.append(st.failure_text)
    if error:
        parts.append(f"The coordinator stopped early ({error}); unfinished incidents were escalated.")
    status = status_of(ctx)
    if status == "noise":
        reason = (
            "No action: the message names no shipment, plant, part, lot or date and describes no disruption to "
            "production, dealers, loaners or owners (rule 7: noise gets no write tools)."
        )
    elif status == "escalated":
        reason = (
            "Not safe to act on, so it was handed to a human with no operational change (rule 8: unconfirmed or "
            "unclear reports are escalated): " + (" ".join(st.escalated.values())[:400] or (error or ""))
        )
    else:
        reason = (
            "Acted on every confirmed incident: ids and dates resolved against the data, the handbook validators passed, "
            "the digital-twin rehearsal passed, "
            + (f"the auditor agreed ({st.audit_note}), " if st.audit_note else "")
            + "and the live schedule baseline matched before the first write."
            + (" The unclear part was escalated without operational change (rule 8)." if st.escalated else "")
            + (" A call failed at execution, so the remainder was escalated." if st.failed else "")
        )
    return " ".join(parts) or "No operational action.", reason


class FinishArgs(BaseModel):
    summary_hint: str = Field(default="", description="Optional: one sentence on what mattered most in this event")


class CoordinatorFinal(BaseModel):
    outcome: str = ""


@tool(
    "finish",
    {CO},
    "control",
    "End the event: refused while any confirmed incident has neither an executed plan nor an escalation. Generates the "
    "business summary and the decision reason from the facts of the successful actions, and ends your loop.",
)
def finish(ctx: EventContext, args: FinishArgs) -> dict[str, Any]:
    st = cs(ctx)
    if not ctx.incidents:
        raise ValueError("register_incidents first")
    left = unsettled(ctx)
    if left:
        nxt = [f"{i}: {what}" for i, what in left]
        nxt += [f"delegate {t}" for t in _wide_missing(ctx)]
        raise ValueError(
            f"incidents {[i for i, _ in left]} have neither an executed plan nor an escalation (noise: nor a drop). Remaining: "
            + "; ".join(nxt)
        )
    summary, reason = draft(ctx)
    if opts(ctx).get("use_explain", True):
        cfg = agent_config(CO)
        n0 = len(tl(ctx).llm_calls)
        draft_s = summary + (f" Note: {args.summary_hint}" if args.summary_hint else "")
        summary, reason = explain(
            ctx.event["source"], ctx.event["text"], status_of(ctx), draft_s, reason, tl(ctx).llm_calls,
            provider=cfg.provider, model=cfg.model,
        )  # fmt: skip
        for call in tl(ctx).llm_calls[n0:]:
            tl(ctx).usage(CO, call.model, call.cost_usd, call.attempts)
    st.summary, st.reason, st.finished = summary, reason, True
    tl(ctx).step(CO, "decision", f"Event settled ({status_of(ctx)}): {summary}")
    ctx.state["stop_agent"] = (CO, {"outcome": status_of(ctx)})
    return {"finished": True, "status": status_of(ctx), "summary": summary}
