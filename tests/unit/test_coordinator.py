"""The v2 Coordinator end to end with a scripted fake LLM for ALL agents (offline) and the in-process twin as the
enterprise. The fake backend keys its script on the agent named in the system prompt ("You are the Coordinator ...").
The scripts play the part of the models; everything else (tools, validators, twin, executor, trace) is the real code.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import date

import pytest

from control_tower.graph.traverse import impact_outage, impact_supplier_delay
from control_tower.llm import adapter
from control_tower.llm.adapter import RawResponse
from control_tower.orchestration import coordinator as coord_mod
from control_tower.orchestration import coordinator_tools as ct
from control_tower.orchestration import runtime
from control_tower.orchestration.auditor import AuditConcern, AuditVerdict
from control_tower.orchestration.config import AgentConfig
from control_tower.orchestration.context import EventContext
from control_tower.orchestration.coordinator import Coordinator
from control_tower.planning.dealer_care import plan_care
from control_tower.planning.supply_chain import SlotBoard, moves_to_actions, plan_moves
from control_tower.schemas.action import ToolResult
from control_tower.schemas.incident import IncidentSpec
from control_tower.trace import Sink
from control_tower.understanding.resolve import EntityIndex
from control_tower.understanding.schemas import DateMention, RawIncident
from control_tower.world.executor import TwinExecutor


def sig(actions) -> Counter:
    return Counter((a.tool, json.dumps(a.args, sort_keys=True)) for a in actions)


def v1_moves(world, graph, specs):
    """What the v1 deterministic planner does for these incidents (text order, shared board)."""
    board, all_moves, actions, cause = SlotBoard(world), [], [], {}
    for s in specs:
        if s.category == "plant_outage":
            imp = impact_outage(graph, world, plant_id=s.plant_id, start=s.outage_start, end=s.outage_end)
            why = f"{s.plant_id} outage {s.outage_start} to {s.outage_end}"
        else:
            imp = impact_supplier_delay(
                graph, world, plant_id=s.plant_id, part_id=s.part_id, orig_eta=s.orig_eta, new_eta=s.new_eta,
                shipment_id=s.shipment_id,
            )  # fmt: skip
            why = f"late shipment {imp.shipment_id} of {s.part_id}, new ETA {s.new_eta}"
        moves, _ = plan_moves(world, board, imp)
        actions += moves_to_actions(imp, moves, s.incident_id)
        all_moves += moves
        cause |= {m.po.id: why for m in moves}
    return all_moves, actions, cause


E11_SPEC = IncidentSpec(
    incident_id="E-11#1", event_id="E-11", category="plant_outage", confidence=1.0, reason="t", plant_id="P_MS",
    outage_start=date(2027, 3, 26), outage_end=date(2027, 3, 30),
)  # fmt: skip


AGENT_OF = {
    "You are the Coordinator": "coordinator",
    "You are the Supply Chain Planner": "sc",
    "You are the Dealer Network": "dn",
    "You are the Customer Care & Quality": "ccq",
}


def T(tool, args=None, thought="step"):
    return {"thought": thought, "action_tool": tool, "action_args": args or {}}


def FINAL(res=None):
    return {"thought": "done", "final": res or {"task": "x"}}


class FakeLLM:
    """Scripts per agent (FIFO). Replies may be callables evaluated lazily (they need handles created at run time)."""

    name = "fake"

    def __init__(self) -> None:
        self.scripts: dict[str, list] = defaultdict(list)
        self.calls: Counter = Counter()

    def generate_json(self, model, system, user, schema):
        who = next((v for k, v in AGENT_OF.items() if system.startswith(k)), None)
        if who is None and "independent auditor" in system:
            agent, reply = "auditor", {"agree": True, "concerns": [], "summary": "Plan matches the message."}
        elif who is None and "audit-ready explanation" in system:
            agent = "explain"
            reply = {
                "summary": "Scripted summary of what the control tower did for this event, with numbers.",
                "decision_reason": "Scripted reason citing the handbook rules that drove the decision.",
            }
        else:
            agent = who
            assert agent, system[:80]
            q = self.scripts[agent]
            assert q, f"no scripted reply left for {agent}"
            reply = q.pop(0)
            reply = reply() if callable(reply) else reply
        self.calls[agent] += 1
        return RawResponse(text=json.dumps(reply), input_tokens=10, output_tokens=5)


# --- incidents as the coordinator model would read them ---------------------------------------------------------


def D(text):
    return DateMention(text=text)


def raw_outage(plant, start, end, conf=0.95):
    return RawIncident(
        category="plant_outage", evidence="x", reason="r", confidence=conf, plant=plant,
        outage_start=D(start), outage_end=D(end),
    )  # fmt: skip


def raw_delay(plant, part, supplier, orig, new):
    return RawIncident(
        category="supplier_delay", evidence="x", reason="r", confidence=0.95, plant=plant, part=part, supplier=supplier,
        original_eta=D(orig), new_eta=D(new),
    )  # fmt: skip


E11_RAW = raw_outage("Jackson", "Friday Mar 26", "Tuesday Mar 30")
E01_RAW = [
    raw_outage("San Antonio", "next Friday", "Monday Mar 22"),
    raw_delay("Princeton", "infotainment chip", "Quanta", "next Monday", "next Friday"),
]
E03_RAW = RawIncident(
    category="quality_hold", evidence="faulty weld", reason="r", confidence=0.95, plant="Jackson",
    part="infotainment chip", supplier="Kestrel", build_window_start=D("Thursday Feb 25"),
    build_window_end=D("last Monday"),
)  # fmt: skip
UNCONFIRMED = RawIncident(
    category="unconfirmed",
    evidence="something may be off with a seat material",
    reason="rumor",
    confidence=0.9,
    part="seat material",
)
NOISE = RawIncident(category="noise", evidence="brochure", reason="a brochure request", confidence=0.99)


def ev(eid, text="synthetic message"):
    return {"event_id": eid, "received_at": "2027-03-08T08:00:00", "source": "ops chat", "text": text}


# --- scripts for the agents -------------------------------------------------------------------------------------


def register(*raws):
    return T("register_incidents", {"incidents": [r.model_dump(mode="json", exclude_none=True) for r in raws]})


def delegate(agent, task, incident_id=None):
    return T("delegate", {"agent": agent, "task": task, "incident_id": incident_id})


def d_sc(inc):
    return delegate("supply_chain_planner", "reschedule", inc)


D_DEALER = delegate("dealer_network", "dealer_comms")
D_LOANERS = delegate("customer_care_quality", "loaners")
D_QUALITY = lambda inc: delegate("customer_care_quality", "quality_hold", inc)  # noqa: E731


def sc_script(inc):
    return [
        T("affected_builds", {"incident_id": inc}),
        T("propose_slots", {"incident_id": inc}),
        T("submit_reschedule_plan", {"incident_id": inc, "reasoning_summary": "moved them"}),
        FINAL({"task": "reschedule", "incident_id": inc}),
    ]


def last(ctx, label):
    keys = [k for k in ctx.store if isinstance(k, str) and k.startswith(f"h:{ctx.event_id}:{label}:")]
    return max(keys, key=lambda k: int(k.rsplit(":", 1)[1]))


def dn_script(ctx, drop_first_dealer=False):
    def notices():
        by_dealer = ctx.store[last(ctx, "by_dealer")]
        if drop_first_dealer:
            by_dealer = {d: v for d, v in list(by_dealer.items())[1:]}
        return T("compose_notices", {"by_dealer": by_dealer})

    return [
        lambda: T("customer_orders_of", {"po_ids": ctx.moved_po_ids()}),
        notices,
        T("submit_dealer_plan", {"reasoning_summary": "one notice per dealer"}),
        FINAL({"task": "dealer_comms"}),
    ]


def dn_good(ctx):
    return dn_script(ctx)


def ccq_loaners(ctx):
    return [
        lambda: T("eligible_customers", {"co_ids": ctx.affected_co_ids()}),
        lambda: T("loaner_availability", {"dealer_ids": sorted({r["dealer_id"] for r in ctx.store[last(ctx, "eligible")]})}),
        lambda: T("rank_and_assign", {"eligible": last(ctx, "eligible")}),
        T("submit_care_plan", {"task": "loaners", "reasoning_summary": "priority order within pools"}),
        FINAL({"task": "loaners"}),
    ]  # fmt: skip


def acting_flow(inc_ids, *, extra_before_execute=()):
    steps = [d_sc(i) for i in inc_ids]
    return [*steps, D_DEALER, D_LOANERS, *extra_before_execute, T("validate_plan"), T("execute"), T("finish", {})]


# --- harness ----------------------------------------------------------------------------------------------------


@pytest.fixture()
def rig(monkeypatch, world, graph, twin, tmp_path):
    adapter.LEDGER.calls.clear()
    fake = FakeLLM()
    adapter.register_backend("fake", fake)
    cfg = lambda _id: AgentConfig(provider="fake", model="m", max_turns=24)  # noqa: E731
    monkeypatch.setattr(runtime, "agent_config", cfg)
    monkeypatch.setattr(ct, "agent_config", cfg)
    captured: list[EventContext] = []

    class Cap(EventContext):
        def __post_init__(self):
            super().__post_init__()
            captured.append(self)

    monkeypatch.setattr(coord_mod, "EventContext", Cap)
    index = EntityIndex(world)

    class Rig:
        llm = fake
        ctxs = captured
        executor = None
        log = tmp_path / "action_log.jsonl"

        @property
        def ctx(self):
            return captured[-1]

        def coordinator(self, executor=None, **kw):
            self.executor = executor or TwinExecutor(self.log)
            kw.setdefault("use_tiebreak", False)
            return Coordinator(
                world, graph, index, twin, self.executor, traces_dir=tmp_path / "traces", sink=Sink(None), **kw
            )

        def script(self, coord, sc=(), dn=None, ccq=()):
            fake.scripts["coordinator"] = list(coord)
            fake.scripts["sc"] = list(sc)
            fake.scripts["dn"] = list(dn or [])
            fake.scripts["ccq"] = list(ccq)

        def run(self, event, coordinator=None):
            t = (coordinator or self.coordinator()).handle(event)
            if os.environ.get("CT_DUMP"):  # debugging aid: python -m pytest -s with CT_DUMP=1
                for r in t.agents:
                    for s in r.steps:
                        print(r.agent, s.kind, s.text[:240], s.result if s.kind == "tool" else "")
            return t

    return Rig()


def tool_results(trace, name):
    return [s.result for r in trace.agents for s in r.steps if s.kind == "tool" and s.tool == name]


def writes(trace):
    return [a for a in trace.actions if a.writes]


def esc(trace):
    return [a for a in trace.actions if a.tool == "escalate"]


def sc_for(*incs):
    return [s for i in incs for s in sc_script(i)]


# --- E-11: acts -------------------------------------------------------------------------------------------------


def _pick(x):
    return x() if callable(x) else x


def dn_rounds(rig, bad):
    """Dealer Network script: one 4-step round per entry of `bad` (True = that round omits the first dealer)."""
    cache: dict[int, list] = {}

    def at(r, i):
        if r not in cache:
            cache[r] = dn_script(rig.ctx, drop_first_dealer=bad[r])
        return _pick(cache[r][i])

    return [lambda r=r, i=i: at(r, i) for r in range(len(bad)) for i in range(4)]


def ccq_rounds(rig):
    return [lambda i=i: _pick(ccq_loaners(rig.ctx)[i]) for i in range(5)]


def lazy_scripts(rig, *, drop_first_dealer=False):
    return dn_rounds(rig, [drop_first_dealer]), ccq_rounds(rig)


def test_e11_acts_matches_v1_and_runs_four_agents(rig, world, graph):
    dn, ccq = lazy_scripts(rig)
    rig.script([register(E11_RAW), *acting_flow(["E-11#1"])], sc=sc_script("E-11#1"), dn=dn, ccq=ccq)
    t = rig.run(ev("E-11"))
    assert t.status == "done" and t.classification.category == "plant_outage"
    assert [r.agent for r in t.agents] == [
        "coordinator",
        "supply_chain_planner",
        "dealer_network",
        "customer_care_quality",
    ]
    assert all(r.llm_calls > 0 and r.model == "m" for r in t.agents)
    moves, mv, cause = v1_moves(world, graph, [E11_SPEC])
    care = plan_care(world, moves, dict(world.loaner_pool), incident_id="E-11#1", cause=cause, loaner_given_to=set())
    assert sig(writes(t)) == sig(mv + care) and len(writes(t)) > 20
    assert all(a.result.ok and a.rehearsal.ok and a.transport == "twin" for a in writes(t))
    assert t.orchestration.mcp_transport == "twin" and t.orchestration.correction_rounds == 0
    assert t.orchestration.escalations == [] and esc(t) == []
    assert any(a.tool == "crm.loaner_availability" for a in t.actions)  # the specialists' live reads are in the trace
    assert [a.seq for a in t.actions] == list(range(1, len(t.actions) + 1))
    assert t.summary.startswith("Scripted") and t.llm.total_cost_usd == 0
    assert t.world_diff.moved_pos and t.counterfactual.customers_affected > 0
    assert t.paths["E-11#1"] and rig.log.read_text().count("\n") >= len(writes(t))
    tools = [a.tool for a in writes(t)]  # phase order: moves, notices, loaners
    last_move = max(i for i, x in enumerate(tools) if x.startswith("mes."))
    assert last_move < tools.index("dealer.notify") < tools.index("crm.assign_loaner")


# --- escalate / noise -------------------------------------------------------------------------------------------


def test_e02_unconfirmed_escalates_with_minimal_path(rig):
    rig.script([
        register(UNCONFIRMED),
        T("escalate", {"incident_id": "E-02#1", "reason": "rumor, no dates or ids",
                       "what_would_make_it_actionable": "the shipment or lot id, the plant and the dates"}),
        T("finish", {}),
    ])  # fmt: skip
    t = rig.run(ev("E-02", "Rumor from a supplier rep: something may be off with a seat material."))
    assert t.status == "escalated" and [a.tool for a in t.actions] == ["escalate"]
    assert not writes(t) and "what would make it actionable" in t.actions[0].args["reason"].lower()
    assert t.orchestration.escalations[0].incident_id == "E-02#1"
    (path,) = t.paths["E-02#1"]
    assert path.nodes[0].type == "Event" and path.nodes[0].id == "E-02"
    assert [r.agent for r in t.agents] == ["coordinator"]


def test_escalate_is_idempotent(rig):
    arg = {"incident_id": "E-02#1", "reason": "r", "what_would_make_it_actionable": "w"}
    rig.script([register(UNCONFIRMED), T("escalate", arg), T("escalate", arg), T("finish", {})])
    t = rig.run(ev("E-02"))
    assert len(esc(t)) == 1
    assert tool_results(t, "escalate")[1]["noop"] is True


def test_e05_noise_makes_no_calls(rig):
    rig.script(
        [register(NOISE), T("drop_noise", {"incident_id": "E-05#1", "reason": "brochure request"}), T("finish", {})]
    )
    t = rig.run(ev("E-05", "Dealer Amarillo, TX asks where to find the new brochure PDF."))
    assert t.status == "noise" and t.actions == [] and rig.log.read_text() == ""
    assert t.classification.category == "noise" and t.counterfactual is None
    assert t.paths["E-05#1"][0].nodes[0].type == "Event"
    assert "brochure" in t.summary.lower() or t.summary.startswith("Scripted")


def test_event_path_mentions_scanned_entities(rig):
    rig.script([register(NOISE), T("drop_noise", {"incident_id": "E-05#1", "reason": "brochure"}), T("finish", {})])
    t = rig.run(ev("E-05", "The Jackson plant manager asks for the brochure."))
    path = t.paths["E-05#1"][0]
    assert [n.id for n in path.nodes] == ["E-05", "P_MS"] and path.edges[0].type == "MENTIONS"


def test_drop_noise_refused_when_a_shipment_is_named(rig):
    named = NOISE.model_copy(update={"shipment_id": "SH-0190", "evidence": "SH-0190 is stuck"})
    rig.script([
        register(named),
        T("drop_noise", {"incident_id": "E-05#1", "reason": "looks like noise"}),
        T("escalate", {"incident_id": "E-05#1", "reason": "names SH-0190",
                       "what_would_make_it_actionable": "confirm what happened to SH-0190"}),
        T("finish", {}),
    ])  # fmt: skip
    t = rig.run(ev("E-05", "SH-0190 is stuck somewhere, no idea"))
    assert tool_results(t, "drop_noise")[0]["refused"] is True
    assert t.status == "escalated" and len(esc(t)) == 1 and not writes(t)


def test_drop_noise_refused_for_plant_with_dates(rig):
    named = NOISE.model_copy(update={"plant": "Jackson", "outage_start": D("next Monday")})
    rig.script([register(named), T("drop_noise", {"incident_id": "E-05#1", "reason": "x"}),
                T("escalate", {"incident_id": "E-05#1", "reason": "r", "what_would_make_it_actionable": "w"}),
                T("finish", {})])  # fmt: skip
    t = rig.run(ev("E-05"))
    assert tool_results(t, "drop_noise")[0]["refused"] is True and len(esc(t)) == 1


def test_brochure_that_mentions_a_city_stays_noise(rig):
    named = NOISE.model_copy(update={"plant": "San Antonio"})  # a place, but no dates and no ids
    rig.script([register(named), T("drop_noise", {"incident_id": "E-05#1", "reason": "brochure"}), T("finish", {})])
    t = rig.run(ev("E-05", "Brochure for the San Antonio open day"))
    assert t.status == "noise" and esc(t) == []


# --- compound ---------------------------------------------------------------------------------------------------


def test_e01_compound_shares_slots_and_pool(rig, world, graph):
    dn, ccq = lazy_scripts(rig)
    rig.script([register(*E01_RAW), *acting_flow(["E-01#1", "E-01#2"])], sc=sc_for("E-01#1", "E-01#2"), dn=dn, ccq=ccq)
    t = rig.run(ev("E-01"))
    assert t.status == "done" and t.classification.category == "compound" and len(t.incidents) == 2
    moves, mv, cause = v1_moves(world, graph, list(rig.ctx.incidents.values()))
    care = plan_care(world, moves, dict(world.loaner_pool), incident_id=None, cause=cause, loaner_given_to=set())
    assert sig(writes(t)) == sig(mv + care)
    notified = [a.args["dealer_id"] for a in t.actions if a.tool == "dealer.notify"]
    assert notified and len(notified) == len(set(notified))  # one notice per dealer for the whole event
    notice = next(a for a in t.actions if a.tool == "dealer.notify")
    assert notice.incident_ids  # event-wide actions list the incidents they serve
    reads = [a for a in t.actions if a.tool == "crm.loaner_availability"]
    assert reads and all(a.result.ok for a in reads)


def test_compound_escalates_only_the_unclear_part(rig):
    dn, ccq = lazy_scripts(rig)
    rig.script(
        [
            register(E11_RAW, UNCONFIRMED),
            T("escalate", {"incident_id": "E-11#2", "reason": "rumor", "what_would_make_it_actionable": "details"}),
            *acting_flow(["E-11#1"]),
        ],
        sc=sc_script("E-11#1"), dn=dn, ccq=ccq,
    )  # fmt: skip
    t = rig.run(ev("E-11"))
    assert t.status == "done" and len(esc(t)) == 1 and esc(t)[0].seq == t.actions[-1].seq
    assert esc(t)[0].incident_ids == ["E-11#2"] and writes(t)


# --- delegation cadence -----------------------------------------------------------------------------------------


def test_delegation_rules_are_enforced(rig):
    rig.script(
        [
            register(*E01_RAW),
            D_DEALER,  # before any per-incident result
            d_sc("E-01#1"),
            d_sc("E-01#1"),  # repeat without findings
            delegate("supply_chain_planner", "quality_hold", "E-01#1"),  # wrong agent for the task
            delegate("customer_care_quality", "quality_hold", "E-01#2"),  # wrong category
            d_sc(None),  # missing incident id
            T("execute"),
            T("finish", {}),
        ],
        sc=sc_script("E-01#1"),
    )
    t = rig.run(ev("E-01"))
    errs = [r.get("error", "") for r in tool_results(t, "delegate")]
    assert "still missing" in errs[0] and "correction round" in errs[2]
    assert "belongs to" in errs[3] and "not actionable" in errs[4] and "needs incident_id" in errs[5]
    assert "tasks missing" in tool_results(t, "execute")[0]["error"]
    assert "incidents ['E-01#1', 'E-01#2'] have neither" in tool_results(t, "finish")[0]["error"]
    assert t.status == "escalated" and not writes(t)  # loop ran out of script -> the unfinished incidents are escalated
    assert len(esc(t)) == 2


def test_needs_human_incident_cannot_be_delegated(rig):
    vague = raw_outage("the northern facility", "next Tuesday", "next Thursday")
    rig.script(
        [register(vague), d_sc("E-07#1"), T("escalate", {"incident_id": "E-07#1", "reason": "plant unresolved",
                                                          "what_would_make_it_actionable": "which plant"}), T("finish", {})]
    )  # fmt: skip
    t = rig.run(ev("E-07"))
    assert "needs_human" in tool_results(t, "delegate")[0]["error"]
    assert tool_results(t, "register_incidents")[0]["incidents"][0]["needs_human"] is True
    assert t.status == "escalated" and not writes(t) and len(esc(t)) == 1


def test_low_confidence_escalates(rig):
    shaky = raw_outage("Jackson", "Friday Mar 26", "Tuesday Mar 30", conf=0.4)
    rig.script([register(shaky), d_sc("E-07#1"),
                T("escalate", {"incident_id": "E-07#1", "reason": "confidence 0.4", "what_would_make_it_actionable": "confirm"}),
                T("finish", {})])  # fmt: skip
    t = rig.run(ev("E-07"))
    assert "needs_human" in tool_results(t, "delegate")[0]["error"] and t.status == "escalated" and not writes(t)


def test_finish_refused_before_completion(rig):
    dn, ccq = lazy_scripts(rig)
    rig.script([register(E11_RAW), T("finish", {}), *acting_flow(["E-11#1"])], sc=sc_script("E-11#1"), dn=dn, ccq=ccq)
    t = rig.run(ev("E-11"))
    assert "neither an executed plan nor an escalation" in tool_results(t, "finish")[0]["error"]
    assert t.status == "done"


# --- validation and correction rounds ---------------------------------------------------------------------------


def test_correction_round_fixes_a_missing_dealer(rig):
    ccq = ccq_rounds(rig)
    rig.script(
        [
            register(E11_RAW), d_sc("E-11#1"), D_DEALER, D_LOANERS, T("validate_plan"),
            D_DEALER,  # correction round
            T("validate_plan"), T("execute"), T("finish", {}),
        ],
        sc=sc_script("E-11#1"), dn=dn_rounds(rig, [True, False]), ccq=ccq,
    )  # fmt: skip
    t = rig.run(ev("E-11"))
    v = tool_results(t, "validate_plan")
    assert v[0]["ok"] is False and v[1]["ok"] is True
    assert any(f["rule"] == "V3" for fs in v[0]["by_incident"].values() for f in fs)
    assert t.orchestration.correction_rounds == 1 and t.status == "done"
    msgs = [s for s in t.agents[0].steps if s.kind == "message" and "CORRECTION ROUND 1" in s.text]
    assert msgs and msgs[0].to_agent == "dealer_network"
    notified = [a.args["dealer_id"] for a in t.actions if a.tool == "dealer.notify"]
    assert len(notified) == len(set(notified))


def test_two_failed_rounds_escalate(rig):
    ccq = ccq_rounds(rig)
    dn = dn_rounds(rig, [True, True, True])
    rig.script(
        [
            register(E11_RAW), d_sc("E-11#1"), D_DEALER, D_LOANERS, T("validate_plan"),
            D_DEALER, T("validate_plan"), D_DEALER, T("validate_plan"),
            D_DEALER,  # third attempt: refused
            T("escalate", {"incident_id": "E-11#1", "reason": "dealer notices keep failing validation",
                           "what_would_make_it_actionable": "a person to check the dealer list"}),
            T("finish", {}),
        ],
        sc=sc_script("E-11#1"), dn=dn, ccq=ccq,
    )  # fmt: skip
    t = rig.run(ev("E-11"))
    delegates = tool_results(t, "delegate")
    assert "escalate this incident" in delegates[-1]["error"]
    assert t.orchestration.correction_rounds == 2
    assert t.status == "escalated" and not writes(t) and len(esc(t)) == 1


# --- execution: failures ----------------------------------------------------------------------------------------


class Wrap(TwinExecutor):
    """TwinExecutor whose Nth write (or the first write matching `match`) fails."""

    def __init__(self, path, *, match=None, nth=None, outcome="failed"):
        super().__init__(path)
        self.match, self.nth, self.outcome, self.n, self.sent = match, nth, outcome, 0, []

    def call(self, event_id, tool, args):
        self.sent.append((tool, json.dumps(args, sort_keys=True)))
        if tool in (
            "mes.reschedule",
            "mes.transfer",
            "dealer.notify",
            "crm.assign_loaner",
            "dealer.stop_sale",
            "quality.hold_lot",
            "crm.notify_customer",
        ):
            self.n += 1
            if (self.match and self.match(tool, args)) or self.nth == self.n:
                self.match = None
                self.nth = -1
                return ToolResult(ok=False, error="server said no", outcome=self.outcome)
        return super().call(event_id, tool, args)


def _first_loaner_po(world, graph):
    moves, _, cause = v1_moves(world, graph, [E11_SPEC])
    care = plan_care(world, moves, dict(world.loaner_pool), incident_id="E-11#1", cause=cause, loaner_given_to=set())
    co = next(a.args["customer_order_id"] for a in care if a.tool == "crm.assign_loaner")
    return world.customer_orders[co].production_order_id


def test_failed_move_skips_dependents_and_escalates_once(rig, world, graph):
    bad_po = _first_loaner_po(world, graph)
    ex = Wrap(rig.log, match=lambda tool, args: tool.startswith("mes.") and args["production_order_id"] == bad_po)
    dn, ccq = lazy_scripts(rig)
    rig.script([register(E11_RAW), *acting_flow(["E-11#1"])], sc=sc_script("E-11#1"), dn=dn, ccq=ccq)
    t = rig.run(ev("E-11"), rig.coordinator(ex))
    assert t.status == "failed" and len(esc(t)) == 1 and "Failed" in esc(t)[0].args["reason"]
    skipped = [a for a in t.actions if a.skipped]
    assert skipped and all(a.result.error == "skipped: dependency failed" and not a.result.ok for a in skipped)
    assert any(a.tool == "crm.assign_loaner" for a in skipped)
    assert bad_po not in [m.production_order_id for m in t.world_diff.moved_pos]
    assert t.world_diff.moved_pos  # the other moves went through
    co_bad = {c.id for c in world.cos_by_po[bad_po]}
    listed = {c for n in t.world_diff.notified_dealers for c in n.customer_order_ids}
    assert not (listed & co_bad)  # notices were recomputed from the moves that succeeded
    loaned = {a.args["customer_order_id"] for a in t.actions if a.tool == "crm.assign_loaner" and a.result.ok}
    assert not (loaned & co_bad)
    assert t.orchestration.escalations and t.counterfactual is not None
    assert esc(t)[0].seq == t.actions[-1].seq


def test_unknown_outcome_stops_the_whole_event(rig):
    ex = Wrap(rig.log, nth=3, outcome="unknown")
    dn, ccq = lazy_scripts(rig)
    rig.script([register(E11_RAW), *acting_flow(["E-11#1"])], sc=sc_script("E-11#1"), dn=dn, ccq=ccq)
    t = rig.run(ev("E-11"), rig.coordinator(ex))
    assert t.status == "failed" and len(esc(t)) == 1
    sent_writes = [s for s in ex.sent if s[0] not in ("mes.get_schedule", "crm.loaner_availability", "escalate")]
    assert len(sent_writes) == 3  # nothing after the unknown outcome was sent
    after = [a for a in writes(t)][3:]
    assert after and all(a.skipped and "unknown" in a.result.error for a in after)
    assert "unknown outcome" in esc(t)[0].args["reason"]
    assert len(t.world_diff.moved_pos) == 2


# --- execution: guardrails --------------------------------------------------------------------------------------


def test_auditor_blocking_concern_escalates_with_no_writes(rig, monkeypatch):
    verdict = AuditVerdict(
        agree=False,
        summary="wrong plant",
        concerns=[AuditConcern(rule="interpretation", issue="plant is not Jackson", severity="blocking")],
    )
    monkeypatch.setattr(ct, "audit", lambda *a, **k: verdict)
    dn, ccq = lazy_scripts(rig)
    rig.script([register(E11_RAW), *acting_flow(["E-11#1"])], sc=sc_script("E-11#1"), dn=dn, ccq=ccq)
    t = rig.run(ev("E-11"))
    assert t.status == "escalated" and not writes(t) and len(esc(t)) == 1
    assert "Auditor disagreed" in esc(t)[0].args["reason"]
    assert rig.log.read_text().count('"tool": "escalate"') == 1


def test_rehearsal_failure_escalates_with_no_writes(rig, monkeypatch, twin):
    from control_tower.schemas.action import Rehearsal

    real = twin.rehearse
    monkeypatch.setattr(
        twin, "rehearse", lambda acts: [Rehearsal(ok=False, error="would be rejected") for _ in real(acts)]
    )
    dn, ccq = lazy_scripts(rig)
    rig.script([register(E11_RAW), *acting_flow(["E-11#1"])], sc=sc_script("E-11#1"), dn=dn, ccq=ccq)
    t = rig.run(ev("E-11"))
    assert t.status == "escalated" and not writes(t) and "rehearsal" in esc(t)[0].args["reason"]


def test_stale_live_world_escalates_before_any_write(rig):
    ex = TwinExecutor(rig.log)
    for _ in range(2):  # the second run finds the first run's changes in the live world
        dn, ccq = lazy_scripts(rig)
        rig.script([register(E11_RAW), *acting_flow(["E-11#1"])], sc=sc_script("E-11#1"), dn=dn, ccq=ccq)
        t = rig.run(ev("E-11"), rig.coordinator(ex))
    assert t.status == "escalated" and not [a for a in writes(t) if a.result and a.result.ok]
    assert "not fresh" in esc(t)[0].args["reason"] or "differs" in esc(t)[0].args["reason"]


def test_loop_error_escalates_unfinished_incidents_with_zero_writes(rig):
    rig.script([register(*E01_RAW)] + [T("nonexistent_tool")] * 5)  # two rejections in a row end the loop
    t = rig.run(ev("E-01"))
    assert t.status == "escalated" and not writes(t) and len(esc(t)) == 2
    assert "unknown tool" in esc(t)[0].args["reason"] or "Not completed" in esc(t)[0].args["reason"]


def test_loop_error_before_registration_escalates_the_event(rig):
    rig.script([T("nope"), T("nope")])
    t = rig.run(ev("E-09", "some text"))
    assert t.status == "escalated" and len(esc(t)) == 1 and t.paths["E-09"][0].nodes[0].type == "Event"


# --- quality incident -------------------------------------------------------------------------------------------


def test_e03_quality_hold(rig, world, graph):
    def dn_stop():
        return [
            lambda: T(
                "compose_stop_sales", {"incident_id": "E-03#1", "vins_by_dealer": last(rig.ctx, "in_stock_by_dealer")}
            ),
            T("submit_dealer_plan", {}),
            FINAL({"task": "dealer_comms"}),
        ]

    rig.script([register(E03_RAW), T("delegate", {"agent": "customer_care_quality", "task": "quality_hold", "incident_id": "E-03#1"}), D_DEALER, T("validate_plan"), T("execute"), T("finish", {})],
               dn=[lambda i=i: _pick(dn_stop()[i]) for i in range(3)],
               ccq=[
                   T("match_lot", {"incident_id": "E-03#1"}),
                   T("affected_vehicles", {"lot_id": "LOT-0130"}),
                   T("compose_hold", {"lot_id": "LOT-0130"}),
                   lambda: T("compose_owner_contacts", {"incident_id": "E-03#1", "owners": last(rig.ctx, "owners")}),
                   T("submit_care_plan", {"task": "quality_hold", "incident_id": "E-03#1"}),
                   FINAL({"task": "quality_hold"}),
               ])  # fmt: skip
    t = rig.run(ev("E-03"))
    assert t.status == "done"
    assert {a.tool for a in writes(t)} == {"quality.hold_lot", "dealer.stop_sale", "crm.notify_customer"}
    assert [r.agent for r in t.agents] == ["coordinator", "dealer_network", "customer_care_quality"]
    assert t.paths["E-03#1"] and t.world_diff.held_lots == ["LOT-0130"]
    assert not any(a.tool == "crm.assign_loaner" for a in t.actions)  # no loaners task for a quality-only event


# --- the escalation circumstances of PLAN_V2 4.1 (one per circumstance) and the nickname guard ------------------
# 1 unconfirmed: test_e02_unconfirmed_escalates_with_minimal_path
# 2 unresolved id / low confidence: test_needs_human_incident_cannot_be_delegated, test_low_confidence_escalates
# 3 noise names a record: test_drop_noise_refused_when_a_shipment_is_named / ..._for_plant_with_dates
# 4 validators fail twice: test_two_failed_rounds_escalate
# 5 rehearsal fails / auditor blocks: test_rehearsal_failure_..., test_auditor_blocking_...
# 6 a write fails: test_failed_move_skips_dependents_and_escalates_once, test_unknown_outcome_...
# 7 world not fresh: test_stale_live_world_escalates_before_any_write


@pytest.mark.parametrize("plant", ["the Texas plant", "San Antonio"])
def test_nicknames_resolve_by_alias_and_are_not_escalated(rig, plant):
    dn, ccq = lazy_scripts(rig)
    raw = raw_outage(plant, "next Friday", "Monday Mar 22")
    rig.script([register(raw), *acting_flow(["E-04#1"])], sc=sc_script("E-04#1"), dn=dn, ccq=ccq)
    t = rig.run(ev("E-04"))
    inc = tool_results(t, "register_incidents")[0]["incidents"][0]
    assert inc["plant_id"] == "P_TX" and inc["needs_human"] is False and inc["actionable"] is True
    assert t.status == "done" and esc(t) == []


def test_resolve_tools_report_candidates(rig):
    rig.script([
        register(UNCONFIRMED),
        T("resolve_entity", {"type": "plant", "mention": "Alamo City"}),
        T("resolve_entity", {"type": "plant", "mention": "San Antonio"}),
        T("resolve_date", {"phrase": "next Friday"}),
        T("resolve_date", {"phrase": "Saturday Mar 13"}),
        T("escalate", {"incident_id": "E-02#1", "reason": "r", "what_would_make_it_actionable": "w"}),
        T("finish", {}),
    ])  # fmt: skip
    t = rig.run(ev("E-02"))
    ent, dt = tool_results(t, "resolve_entity"), tool_results(t, "resolve_date")
    assert ent[0]["pick"] is None and ent[1]["pick"] == "P_TX"
    assert dt[0]["date"] == "2027-03-19" and dt[0]["working_day"] is True
    assert dt[1]["working_day"] is False and dt[1]["next_working_day"]
