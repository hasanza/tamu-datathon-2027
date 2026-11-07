"""Task 3.1: the Coordinator. One event in, one Trace out.

  understand (LLM + resolver) -> gate -> dispatch to specialists (shared slot board + loaner pools)
  -> rehearse on the twin -> verify the live world -> execute -> trace

The LLM only appears in `understand`. Everything after it is deterministic code. Nothing is sent to the real server
unless the whole plan rehearsed cleanly and the live world still matches the baseline the plan was computed from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import networkx as nx

from control_tower.agents.auditor import audit, plan_digest
from control_tower.agents.dealer_care import plan_care
from control_tower.agents.explain import explain
from control_tower.agents.policy import DEFAULT_POLICY, Policy
from control_tower.agents.quality import plan_quality
from control_tower.agents.supply_chain import Move, SlotBoard, moves_to_actions, plan_moves
from control_tower.data.loader import LOANER_TIERS, World
from control_tower.graph.traverse import (
    customer_orders_of,
    impact_lot,
    impact_outage,
    impact_supplier_delay,
)
from control_tower.llm.adapter import AUDIT_MODELS, LLMError, default_provider
from control_tower.schemas.action import WRITE_TOOLS, Action, Rehearsal, ToolResult
from control_tower.schemas.incident import IncidentSpec
from control_tower.schemas.trace import (
    Classification,
    Counterfactual,
    GraphPath,
    LLMUsage,
    MovedPO,
    NotifiedDealer,
    Trace,
    WorldDiff,
)
from control_tower.trace import Sink, Timeline, write_trace
from control_tower.understanding.extract import extract
from control_tower.understanding.resolve import CONFIDENCE_GATE, EntityIndex, build_incident
from control_tower.understanding.schemas import RawIncident
from control_tower.understanding.tiebreak import make_tiebreak
from control_tower.world.executor import Executor
from control_tower.world.twin import Twin, check_invariants


@dataclass
class IncidentPlan:
    spec: IncidentSpec
    actions: list[Action] = field(default_factory=list)
    po_ids: set[str] = field(default_factory=set)
    co_ids: set[str] = field(default_factory=set)
    moves: list[Move] = field(default_factory=list)
    paths: list[GraphPath] = field(default_factory=list)
    unplaceable: list[str] = field(default_factory=list)
    cause: str = ""
    stopped: int = 0
    owners: int = 0
    unsold_dealers: int = 0
    headline: str = ""


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
        provider: str | None = None,
        model: str | None = None,
        extractor=extract,
        use_tiebreak: bool = False,
        use_audit: bool = False,
        use_explain: bool = False,
        audit_model: str | None = None,
    ) -> None:
        self.world, self.g, self.index, self.twin, self.executor = world, graph, index, twin, executor
        self.traces_dir, self.sink, self.policy = traces_dir, sink or Sink(None), policy
        self.provider, self.model, self.extractor = provider, model, extractor
        self.use_tiebreak = use_tiebreak
        self.use_audit, self.use_explain, self.audit_model = use_audit, use_explain, audit_model

    # ------------------------------------------------------------------ public
    def handle(self, event: dict[str, Any]) -> Trace:
        eid = event["event_id"]
        tl = Timeline(eid, event["received_at"], self.sink)
        self.sink.emit("event_received", eid, {k: event[k] for k in ("received_at", "source", "text")})

        # 1. understand ---------------------------------------------------------------------------------------
        try:
            extraction, call = self.extractor(
                event["source"], event["received_at"], event["text"], provider=self.provider, model=self.model
            )
        except LLMError as e:
            return self._finish_escalation(event, tl, [], [], f"Understanding failed ({type(e).__name__}): {e}")
        tl.llm(call)
        tl.step(
            "coordinator",
            "llm",
            f"Extracted {len(extraction.incidents)} incident(s): "
            + ", ".join(i.category for i in extraction.incidents),
            {
                "model": call.model,
                "input_tokens": call.input_tokens,
                "output_tokens": call.output_tokens,
                "cached": call.cached,
            },
        )
        tiebreak = (
            make_tiebreak(self.world, tl.llm_calls, provider=self.provider, model=self.model)
            if self.use_tiebreak
            else None
        )
        pairs = []
        for n, raw in enumerate(extraction.incidents, 1):
            res = build_incident(
                self.world, self.index, raw, event_id=eid, n=n, event_text=event["text"], tiebreak=tiebreak
            )
            pairs.append((raw, res))
            for st in res.spec.resolution_steps:
                if st.method in {"data_snap", "fuzzy", "llm"}:
                    tl.step(
                        "coordinator",
                        "gate",
                        f"{st.entity_type} {st.mention!r} -> {st.chosen} via {st.method}: {st.note or ''}".strip(),
                    )

        # 2. gate ---------------------------------------------------------------------------------------------
        noise = [(r, x) for r, x in pairs if x.spec.category == "noise"]
        real = [(r, x) for r, x in pairs if x.spec.category != "noise"]
        if not real:
            return self._finish_noise(event, tl, noise)
        actionable = [(r, x) for r, x in real if not x.needs_human]
        unclear = [(r, x) for r, x in real if x.needs_human]
        for _, x in noise:
            tl.step("coordinator", "gate", f"{x.spec.incident_id}: noise, no action. {x.spec.reason}")
        for _, x in unclear:
            tl.step(
                "coordinator",
                "gate",
                f"{x.spec.incident_id}: {x.spec.category} NOT actionable (confidence {x.spec.confidence:.2f}); "
                + "; ".join(a.issue for a in x.spec.ambiguities if a.blocking)[:300],
            )
        for _, x in actionable:
            tl.step(
                "coordinator",
                "gate",
                f"{x.spec.incident_id}: {x.spec.category} confirmed, confidence {x.spec.confidence:.2f} >= {CONFIDENCE_GATE} -> act",
            )

        # 3. dispatch to specialists with shared state ---------------------------------------------------------
        board, pool, given = SlotBoard(self.world), dict(self.world.loaner_pool), set()
        baseline = SlotBoard(self.world)  # the world as it is before this event touches anything
        plans: list[IncidentPlan] = []
        extra_escalations: list[str] = []
        try:
            for _, x in actionable:
                plan = self._plan_incident(x.spec, board, pool, given, tl)
                plans.append(plan)
                if plan.unplaceable:
                    extra_escalations.append(f"{x.spec.incident_id}: no feasible slot for {plan.unplaceable}")
                if not plan.po_ids and not plan.stopped and x.spec.category != "quality_hold":
                    extra_escalations.append(
                        f"{x.spec.incident_id}: confirmed {x.spec.category} but no production order is affected"
                    )
        except Exception as e:  # a planner bug must never become a half-executed plan
            return self._finish_escalation(
                event, tl, [x.spec for _, x in real], plans, f"Planning failed: {type(e).__name__}: {e}"
            )

        care_actions = self._plan_care(plans, pool, given, tl)
        plan_actions = [a for p in plans for a in p.actions] + care_actions
        reads = self._verification_reads(plans, baseline)
        escalate_reasons = [self._escalation_reason(event, r, x.spec) for r, x in unclear] + extra_escalations
        esc_actions: list[Action] = []
        if escalate_reasons:
            esc_actions.append(
                Action(
                    seq=0,
                    incident_id=unclear[0][1].spec.incident_id if unclear else plans[0].spec.incident_id,
                    agent="coordinator",
                    tool="escalate",
                    args={"reason": " | ".join(escalate_reasons)},
                    justification="Rule 8: unconfirmed or unclear -> escalate, no operational action for that part",
                )
            )
        all_actions = reads + plan_actions + esc_actions
        for i, a in enumerate(all_actions, 1):
            a.seq = i

        # 4. rehearse on the twin -------------------------------------------------------------------------------
        if all_actions:
            results = self.twin.rehearse(all_actions)
            for a, r in zip(all_actions, results, strict=True):
                a.rehearsal = r
            failed = [(a, r) for a, r in zip(all_actions, results, strict=True) if not r.ok]
            problems = check_invariants(
                plan_actions,
                allowed_po_ids={x for p in plans for x in p.po_ids},
                allowed_co_ids={x for p in plans for x in p.co_ids},
                real_incident=bool(plans),
            )
            hard = [m for m in problems if "rule 9" not in m]
            for m in problems:
                if "rule 9" in m:
                    tl.step("coordinator", "rehearse", f"note - {m}")
            tl.step(
                "coordinator",
                "rehearse",
                f"Rehearsed {len(all_actions)} actions on the twin: {len(all_actions) - len(failed)} ok, {len(failed)} failed. "
                f"Invariants: {'ok' if not hard else '; '.join(hard)}",
            )
            if failed or hard:
                why = "; ".join([f"{a.tool} {a.args}: {r.error}" for a, r in failed[:3]] + hard[:3])
                for a in all_actions:
                    a.rehearsal = a.rehearsal or Rehearsal(ok=False)
                return self._finish_escalation(
                    event, tl, [x.spec for _, x in real], plans, f"Plan rejected by rehearsal, nothing executed: {why}"
                )

        # 4b. independent audit (second model, second channel) ------------------------------------------------
        if self.use_audit and plans:
            digest = plan_digest(self.world, plans, care_actions, escalate_reasons)
            verdict = audit(
                event["source"],
                event["text"],
                digest,
                tl.llm_calls,
                provider=self.provider,
                model=self.audit_model or AUDIT_MODELS.get(self.provider or default_provider()),
            )
            if verdict is None:
                tl.step("coordinator", "audit", "Auditor unavailable; continuing on the deterministic checks alone")
            else:
                blocking = [c for c in verdict.concerns if c.severity == "blocking"]
                tl.step(
                    "coordinator",
                    "audit",
                    f"Auditor {'agrees' if verdict.agree and not blocking else 'DISAGREES'}: {verdict.summary}"
                    + "".join(f" [{c.severity}] rule {c.rule}: {c.issue}" for c in verdict.concerns),
                )
                if blocking:
                    why = "Auditor disagreed, nothing executed: " + "; ".join(
                        f"rule {c.rule}: {c.issue}" for c in blocking
                    )
                    return self._finish_escalation(event, tl, [x.spec for _, x in real], plans, why)

        # 5. verify the live world, then execute ----------------------------------------------------------------
        read_ids = {id(a) for a in reads}
        executed: list[Action] = []
        runtime_failures: list[str] = []
        aborted: str | None = None
        for a in all_actions:
            res = self.executor.call(eid, a.tool, a.args)
            a.result = res
            executed.append(a)
            self.sink.emit("action", eid, a.model_dump(mode="json"))
            if id(a) in read_ids:
                if not res.ok or not self._read_matches(a, res, baseline):
                    aborted = f"live world differs from the planning baseline at {a.tool} {a.args}: {res.error or res.response}"
                    tl.step("coordinator", "execute", f"ABORT before any write: {aborted}")
                    break
            elif not res.ok:
                runtime_failures.append(f"{a.tool} {a.args}: {res.error}")
                tl.step("coordinator", "execute", f"call failed (not retried): {a.tool} -> {res.error}")
        if aborted:
            return self._finish_escalation(event, tl, [x.spec for _, x in real], plans, aborted, executed=executed)
        writes = [a for a in executed if a.tool in WRITE_TOOLS]
        tl.step(
            "coordinator",
            "execute",
            f"Executed {len(executed)} calls via {self.executor.name}: {sum(bool(a.result and a.result.ok) for a in executed)} ok, "
            f"{len(runtime_failures)} failed ({len(writes)} writes, {len(reads)} verification reads)",
        )
        status = "failed" if runtime_failures else ("done" if writes else "escalated")
        return self._assemble(event, tl, pairs, plans, executed, status, runtime_failures)

    # ------------------------------------------------------------------ planning
    def _plan_incident(
        self, spec: IncidentSpec, board: SlotBoard, pool: dict[str, int], given: set[str], tl: Timeline
    ) -> IncidentPlan:
        w, g = self.world, self.g
        plan = IncidentPlan(spec=spec)
        if spec.category in {"supplier_delay", "plant_outage"}:
            if spec.category == "supplier_delay":
                impact = impact_supplier_delay(
                    g,
                    w,
                    plant_id=spec.plant_id,
                    part_id=spec.part_id,
                    orig_eta=spec.orig_eta,
                    new_eta=spec.new_eta,
                    shipment_id=spec.shipment_id,
                )
                tl.step(
                    "supply_chain",
                    "graph",
                    f"Shipment {impact.shipment_id} -> part {spec.part_id} -> models using it -> POs at {spec.plant_id} building {spec.orig_eta}..{spec.new_eta} (new ETA exclusive): {len(impact.pos)} affected: {impact.po_ids}",
                )
                cause = f"late shipment {impact.shipment_id} of {spec.part_id}, new ETA {spec.new_eta}"
                plan.headline = f"{impact.shipment_id}|{spec.part_id}|{spec.plant_id}|{spec.orig_eta}|{spec.new_eta}"
            else:
                impact = impact_outage(g, w, plant_id=spec.plant_id, start=spec.outage_start, end=spec.outage_end)
                tl.step(
                    "supply_chain",
                    "graph",
                    f"Plant {spec.plant_id} -> POs building {spec.outage_start}..{spec.outage_end} (inclusive): {len(impact.pos)} affected: {impact.po_ids}",
                )
                cause = f"{spec.plant_id} outage {spec.outage_start} to {spec.outage_end}"
                plan.headline = f"{spec.plant_id}|{spec.outage_start}|{spec.outage_end}"
            if impact.already_built:
                tl.step(
                    "supply_chain",
                    "note",
                    f"{len(impact.already_built)} order(s) in the window are already built and cannot move: {impact.already_built}",
                )
            moves, left = plan_moves(w, board, impact, self.policy)
            plan.moves, plan.unplaceable = moves, [p.id for p in left]
            n_transfer = sum(m.kind == "transfer" for m in moves)
            tl.step(
                "supply_chain",
                "plan",
                f"Restart index {impact.disruption_end_idx}; slots 5/day, shared across this event. {len(moves) - n_transfer} reschedule(s), {n_transfer} transfer(s), {len(left)} unplaceable. "
                + "; ".join(f"{m.po.id}->{m.to_plant} {m.to_date}" for m in moves[:12])
                + ("..." if len(moves) > 12 else ""),
                {"policy": {"claim_order": self.policy.claim_order, "transfer_min_day": self.policy.transfer_min_day}},
            )
            plan.actions = moves_to_actions(impact, moves, spec.incident_id)
            plan.cause = cause
            plan.co_ids = {c.id for c in customer_orders_of(g, w, [m.po.id for m in moves])}
            plan.po_ids = {m.po.id for m in moves} | {p.id for p in left}
            plan.paths = impact.summary_paths
        else:  # quality_hold
            q = impact_lot(g, w, spec.lot_id)
            tl.step(
                "quality",
                "graph",
                f"Lot {q.lot.lot_id} -> part {q.lot.part_id} -> models using it -> POs at {q.lot.plant_id} built {q.window[0]}..{q.window[1]}: {len(q.pos)} POs, {len(q.vehicles)} vehicles ({sum(len(v) for v in q.in_stock_by_dealer.values())} unsold at {len(q.in_stock_by_dealer)} dealers, {len(q.owners)} owners)",
            )
            plan.actions = plan_quality(
                w, q, incident_id=spec.incident_id, reason=f"{spec.supplier_id} reported a defect in {spec.part_id}"
            )
            tl.step(
                "quality",
                "plan",
                f"Hold {q.lot.lot_id}; stop sale at {len(q.in_stock_by_dealer)} dealers; contact {len(q.owners)} owners once each.",
            )
            plan.paths = q.summary_paths
            plan.stopped = sum(len(v) for v in q.in_stock_by_dealer.values())
            plan.owners, plan.unsold_dealers = len(q.owners), len(q.in_stock_by_dealer)
            plan.headline = (
                f"{q.lot.lot_id}|{q.lot.part_id}|{q.lot.plant_id}|{q.window[0]}|{q.window[1]}|{q.lot.supplier_id}"
            )
        return plan

    def _plan_care(
        self, plans: list[IncidentPlan], pool: dict[str, int], given: set[str], tl: Timeline
    ) -> list[Action]:
        """Dealer & Customer Care runs ONCE per event over every moved order, so each dealer gets exactly one notice
        (rule 4) and loaner priority is ranked across all incidents of the event (rule 5)."""
        moves = [m for p in plans for m in p.moves]
        if not moves:
            return []
        w = self.world
        cos = [co for m in moves for co in w.cos_by_po.get(m.po.id, [])]
        disruption = [p for p in plans if p.moves]
        incident_id = disruption[0].spec.incident_id if len(disruption) == 1 else None
        tl.step(
            "dealer_care",
            "graph",
            f"{len(cos)} customer orders on {len(moves)} moved POs across {len({c.dealer_id for c in cos})} dealers (all incidents of this event together)",
        )
        cause = {m.po.id: p.cause for p in disruption for m in p.moves}
        actions = plan_care(
            w, moves, pool, incident_id=incident_id, cause=cause, policy=self.policy, loaner_given_to=given
        )
        ent = sum(w.customers[c.customer_id].tier in LOANER_TIERS for c in cos)
        n_loan = sum(a.tool == "crm.assign_loaner" for a in actions)
        tl.step(
            "dealer_care",
            "plan",
            f"One notice per dealer; {ent} Platinum/Gold customer orders entitled, {n_loan} loaner(s) assigned within pool limits (Platinum, then Gold, earlier promise, lower id).",
        )
        return actions

    def _verification_reads(self, plans: list[IncidentPlan], baseline: SlotBoard) -> list[Action]:
        reads: list[Action] = []
        slots = {(m.to_plant, m.to_idx) for p in plans for m in p.moves}
        for plant, idx in sorted(slots):
            reads.append(
                Action(
                    seq=0,
                    agent="supply_chain",
                    tool="mes.get_schedule",
                    args={"plant_id": plant, "date": self.world.calendar.date_of(idx).isoformat()},
                    justification="Free read: confirm the target slot is free in the live world before any write",
                    path_ids=[plant],
                )
            )
        dealers = sorted(
            {
                self.world.customer_orders[a.args["customer_order_id"]].dealer_id
                for p in plans
                for a in p.actions
                if a.tool == "crm.assign_loaner"
            }
        )
        for d in dealers:
            reads.append(
                Action(
                    seq=0,
                    agent="dealer_care",
                    tool="crm.loaner_availability",
                    args={"dealer_id": d},
                    justification="Free read: confirm the loaner pool before assigning",
                    path_ids=[d],
                )
            )
        return reads

    def _read_matches(self, a: Action, res: ToolResult, baseline: SlotBoard) -> bool:
        r = res.response or {}
        if a.tool == "mes.get_schedule":
            idx = self.world.calendar.idx(date.fromisoformat(a.args["date"]))
            return r.get("free_slots") == baseline.free(a.args["plant_id"], idx)
        if a.tool == "crm.loaner_availability":
            return r.get("available") == self.world.loaner_pool[a.args["dealer_id"]]
        return True

    # ------------------------------------------------------------------ finishing
    def _escalation_reason(self, event: dict[str, Any], raw: RawIncident, spec: IncidentSpec) -> str:
        issues = "; ".join(a.issue for a in spec.ambiguities if a.blocking) or "not specific or confirmed"
        questions = {
            "part_id": "which part",
            "supplier_id": "which supplier",
            "specificity": "which lot or shipment, which plant, and the dates",
        }
        asks = [questions.get(f, f) for f in sorted({a.field for a in spec.ambiguities if a.blocking})]
        ask = "; ".join(dict.fromkeys(asks)) or "the specific shipment or lot, plant and dates"
        return (
            f'{spec.incident_id} ({spec.category}, source: {event["source"]}): "{raw.evidence}". '
            f"Not actionable: {issues}. Please confirm: {ask}. No operational action taken."
        )

    def _finish_noise(self, event, tl: Timeline, noise) -> Trace:
        reasons = " ".join(x.spec.reason for _, x in noise)
        tl.step("coordinator", "gate", f"Noise -> no write tools, no escalation (rule 7). {reasons}")
        specs = [x.spec for _, x in noise]
        cls = Classification(category="noise", confidence=min(s.confidence for s in specs), reason=reasons)
        return self._build(
            event,
            tl,
            status="noise",
            cls=cls,
            specs=specs,
            plans=[],
            actions=[],
            summary=f"Not an operational event. {reasons}",
            reason=(
                "No action: the message names no shipment, plant, part, lot or date and describes no disruption "
                "to production, dealers, loaners or owners (rule 7: noise gets no write tools)."
            ),
        )

    def _finish_escalation(
        self,
        event,
        tl: Timeline,
        specs: list[IncidentSpec],
        plans: list[IncidentPlan],
        why: str,
        executed: list[Action] | None = None,
    ) -> Trace:
        esc = Action(
            seq=len(executed or []) + 1,
            incident_id=specs[0].incident_id if specs else None,
            agent="coordinator",
            tool="escalate",
            args={"reason": why},
            justification="Guardrail: could not act safely -> hand to a human, no operational change",
            rehearsal=Rehearsal(ok=True),
        )
        esc.result = self.executor.call(event["event_id"], "escalate", esc.args)
        self.sink.emit("action", event["event_id"], esc.model_dump(mode="json"))
        tl.step("coordinator", "execute", f"escalate: {why[:300]}")
        actions = [*(executed or []), esc]
        category = specs[0].category if len(specs) == 1 else ("compound" if specs else "unconfirmed")
        cls = Classification(category=category, confidence=min((s.confidence for s in specs), default=0.0), reason=why)
        return self._build(
            event,
            tl,
            status="escalated",
            cls=cls,
            specs=specs,
            plans=plans,
            actions=actions,
            summary=f"Handed to a human without operational change. {why}",
            reason=why,
        )

    def _assemble(
        self,
        event,
        tl: Timeline,
        pairs,
        plans: list[IncidentPlan],
        executed: list[Action],
        status: str,
        failures: list[str],
    ) -> Trace:
        specs = [x.spec for _, x in pairs if x.spec.category != "noise"]
        escalated = any(a.tool == "escalate" for a in executed)
        cats = {p.spec.category for p in plans}
        category = "compound" if len(specs) > 1 else specs[0].category
        cls = Classification(
            category=category, confidence=min(s.confidence for s in specs), reason=" ".join(s.reason for s in specs)
        )
        care = [a for a in executed if a.agent == "dealer_care"]
        parts = [self._summarize_plan(p, care) for p in plans]
        if escalated:
            parts.append("Part of the message was not actionable and was escalated to a human.")
        if failures:
            parts.append(f"{len(failures)} call(s) failed at execution and were not retried: {failures[:2]}")
        reason = (
            "Acted on every confirmed incident: ids and dates resolved against the data, rehearsal on the digital "
            "twin passed with zero failures, the live schedule baseline matched before the first write."
            + (" The unclear part was escalated without operational change (rule 8)." if escalated else "")
            + (f" Incident types handled: {', '.join(sorted(cats))}." if cats else "")
        )
        return self._build(
            event,
            tl,
            status=status,
            cls=cls,
            specs=[x.spec for _, x in pairs],
            plans=plans,
            actions=executed,
            summary=" ".join(parts),
            reason=reason,
        )

    def _summarize_plan(self, p: IncidentPlan, care: list[Action]) -> str:
        w, s = self.world, p.spec
        if s.category == "supplier_delay":
            t = sum(m.kind == "transfer" for m in p.moves)
            notified = {
                a.args["dealer_id"]
                for a in care
                if a.tool == "dealer.notify" and set(a.args["customer_order_ids"]) & p.co_ids
            }
            loans = sum(a.tool == "crm.assign_loaner" and a.args["customer_order_id"] in p.co_ids for a in care)
            sup = w.suppliers[s.supplier_id].name if s.supplier_id else "the supplier"
            return (
                f"{sup}'s {w.parts[s.part_id].name} shipment {s.shipment_id or ''} to {w.plants[s.plant_id].name} slips from {s.orig_eta} to {s.new_eta}. "
                f"{len(p.moves)} affected production orders were moved to the earliest free slots ({len(p.moves) - t} rescheduled, {t} transferred); "
                f"{len(notified)} dealers were each notified once for {len(p.co_ids)} customer orders; {loans} Platinum/Gold customers received loaners within pool limits."
            )
        if s.category == "plant_outage":
            t = sum(m.kind == "transfer" for m in p.moves)
            notified = {
                a.args["dealer_id"]
                for a in care
                if a.tool == "dealer.notify" and set(a.args["customer_order_ids"]) & p.co_ids
            }
            loans = sum(a.tool == "crm.assign_loaner" and a.args["customer_order_id"] in p.co_ids for a in care)
            return (
                f"{w.plants[s.plant_id].name} is down {s.outage_start} to {s.outage_end}. {len(p.moves)} production orders were moved "
                f"({len(p.moves) - t} rescheduled at the same plant"
                + (f", {t} transferred to other plants because no same-plant slot was free" if t else "")
                + "); "
                f"{len(notified)} dealers notified once each for {len(p.co_ids)} customer orders; {loans} loaners assigned."
            )
        lot = w.lots[s.lot_id]
        return (
            f"Lot {lot.lot_id} ({w.parts[lot.part_id].name} from {w.suppliers[lot.supplier_id].name} at {w.plants[lot.plant_id].name}, built {lot.first_build_date} to {lot.last_build_date}) "
            f"was placed on hold. {p.stopped} unsold vehicles were stopped from sale at {p.unsold_dealers} dealers and {p.owners} owners of sold vehicles were contacted."
        )

    def _build(
        self,
        event,
        tl: Timeline,
        *,
        status,
        cls: Classification,
        specs,
        plans: list[IncidentPlan],
        actions: list[Action],
        summary: str,
        reason: str,
    ) -> Trace:
        w = self.world
        moved = [m for p in plans for m in p.moves]
        diff = WorldDiff(
            moved_pos=[
                MovedPO(
                    production_order_id=m.po.id,
                    kind=m.kind,
                    from_plant=m.po.plant_id,
                    from_date=m.po.build_date,
                    to_plant=m.to_plant,
                    to_date=m.to_date,
                )
                for m in moved
            ],
            notified_dealers=[
                NotifiedDealer(dealer_id=a.args["dealer_id"], customer_order_ids=a.args["customer_order_ids"])
                for a in actions
                if a.tool == "dealer.notify" and a.result and a.result.ok
            ],
            loaners=[
                a.args["customer_order_id"]
                for a in actions
                if a.tool == "crm.assign_loaner" and a.result and a.result.ok
            ],
            held_lots=[a.args["lot_id"] for a in actions if a.tool == "quality.hold_lot" and a.result and a.result.ok],
            stopped_vins=[
                v for a in actions if a.tool == "dealer.stop_sale" and a.result and a.result.ok for v in a.args["vins"]
            ],
            contacted_customers=[
                a.args["customer_id"] for a in actions if a.tool == "crm.notify_customer" and a.result and a.result.ok
            ],
        )
        cf = None
        if plans:
            cos = {c for p in plans for c in p.co_ids}
            ent = sum(w.customers[w.customer_orders[c].customer_id].tier in LOANER_TIERS for c in cos)
            slips = [
                max(0, (m.to_date - m.po.build_date).days) for m in moved
            ]  # a transfer to an earlier day is not a slip
            cf = Counterfactual(
                customers_affected=len(cos),
                avg_slip_days=round(sum(slips) / len(slips), 1) if slips else None,
                loaners_entitled=ent,
                loaners_assigned=len(diff.loaners),
                vehicles_pulled=len(diff.stopped_vins),
                owners_contacted=len(diff.contacted_customers),
            )
        if self.use_explain:
            summary, reason = explain(
                event["source"],
                event["text"],
                status,
                summary,
                reason,
                tl.llm_calls,
                provider=self.provider,
                model=self.model,
            )
        trace = Trace(
            event_id=event["event_id"], received_at=event["received_at"], source=event["source"], text=event["text"], status=status, classification=cls,
            incidents=list(specs), paths={p.spec.incident_id: p.paths for p in plans if p.paths}, agents=tl.agent_runs(), actions=actions, world_diff=diff, counterfactual=cf,
            llm=LLMUsage(calls=tl.llm_calls, total_cost_usd=round(sum(c.cost_usd for c in tl.llm_calls), 6)), summary=summary, decision_reason=reason,
        )  # fmt: skip
        write_trace(self.traces_dir, event["event_id"], trace.model_dump_json(indent=2, by_alias=True))
        self.sink.emit(
            "event_done", event["event_id"], {"status": status, "category": cls.category, "actions": len(actions)}
        )
        return trace
