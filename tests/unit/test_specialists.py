"""Specialist tools, agents and validators with a scripted fake LLM: the produced action set must equal what the v1
planners produce for the same incidents. Offline."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date

import pytest

from control_tower.graph.traverse import impact_lot, impact_outage, impact_supplier_delay
from control_tower.llm import adapter
from control_tower.llm.adapter import RawResponse
from control_tower.orchestration import runtime
from control_tower.orchestration.config import AgentConfig
from control_tower.orchestration.context import EventContext
from control_tower.orchestration.runtime import run_agent
from control_tower.orchestration.specialist_tools import resolve
from control_tower.orchestration.specialists import CUSTOMER_CARE_QUALITY, DEALER_NETWORK, SUPPLY_CHAIN_PLANNER
from control_tower.planning.dealer_care import plan_care
from control_tower.planning.quality import plan_quality
from control_tower.planning.supply_chain import SlotBoard, moves_to_actions, plan_moves
from control_tower.planning.validators import blocking, validate
from control_tower.schemas.action import Action
from control_tower.schemas.incident import IncidentSpec
from control_tower.trace import Sink, Timeline
from control_tower.world.executor import TwinExecutor


def spec(event_id, n, category, **kw) -> IncidentSpec:
    return IncidentSpec(
        incident_id=f"{event_id}#{n}", event_id=event_id, category=category, confidence=1.0, reason="test", **kw
    )


E11 = spec("E-11", 1, "plant_outage", plant_id="P_MS", outage_start=date(2027, 3, 26), outage_end=date(2027, 3, 30))
E03 = spec(
    "E-03",
    1,
    "quality_hold",
    plant_id="P_MS",
    part_id="CHIP-IVI",
    supplier_id="SUP-06",
    lot_id="LOT-0130",
    build_window_start=date(2027, 2, 25),
    build_window_end=date(2027, 3, 1),
)
E01A = spec("E-01", 1, "plant_outage", plant_id="P_TX", outage_start=date(2027, 3, 19), outage_end=date(2027, 3, 22))
E01B = spec(
    "E-01",
    2,
    "supplier_delay",
    plant_id="P_IN",
    part_id="CHIP-IVI",
    supplier_id="SUP-12",
    shipment_id="SH-0190",
    orig_eta=date(2027, 3, 15),
    new_eta=date(2027, 3, 19),
)


class Scripted:
    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)

    def generate_json(self, model, system, user, schema):
        r = self.replies.pop(0)
        r = r() if callable(r) else r
        return RawResponse(text=json.dumps(r), input_tokens=10, output_tokens=5)


def T(tool, args, thought="step"):
    return {"thought": thought, "action_tool": tool, "action_args": args}


def FINAL(res=None, thought="done"):
    return {"thought": thought, "final": res if res is not None else {"task": "x"}}


@pytest.fixture
def make(monkeypatch, world, graph):
    adapter.LEDGER.calls.clear()
    monkeypatch.setattr(runtime, "agent_config", lambda _id: AgentConfig(provider="fake", model="m", max_turns=14))

    def build(event_id, *incs):
        ctx = EventContext(
            world=world,
            graph=graph,
            executor=TwinExecutor(),
            event_id=event_id,
            incidents={i.incident_id: i for i in incs},
        )
        tl = Timeline(event_id, "2027-03-08T09:00:00", Sink(None))
        return ctx, tl

    def run(agent, ctx, tl, replies, task="t", payload=None):
        adapter.register_backend("fake", Scripted(replies))
        res = run_agent(agent, task, payload or {}, ctx, tl)
        assert res.error is None, res.error
        return res

    return build, run


def last(ctx, label):
    """Most recent handle with this label (handles are `h:<event>:<label>:<n>`)."""
    keys = [k for k in ctx.store if isinstance(k, str) and k.startswith(f"h:{ctx.event_id}:{label}:")]
    return max(keys, key=lambda k: int(k.rsplit(":", 1)[1]))


def sig(actions) -> Counter:
    return Counter((a.tool, json.dumps(a.args, sort_keys=True)) for a in actions)


def sc_script(inc):
    return [
        T("affected_builds", {"incident_id": inc}),
        T("propose_slots", {"incident_id": inc}),
        T("submit_reschedule_plan", {"incident_id": inc, "reasoning_summary": "ok"}),
        FINAL({"task": "reschedule", "incident_id": inc}),
    ]


def v1_moves(world, graph, specs):
    board, all_moves, actions, cause = SlotBoard(world), [], [], {}
    for s in specs:
        if s.category == "plant_outage":
            imp = impact_outage(graph, world, plant_id=s.plant_id, start=s.outage_start, end=s.outage_end)
            why = f"{s.plant_id} outage {s.outage_start} to {s.outage_end}"
        else:
            imp = impact_supplier_delay(
                graph,
                world,
                plant_id=s.plant_id,
                part_id=s.part_id,
                orig_eta=s.orig_eta,
                new_eta=s.new_eta,
                shipment_id=s.shipment_id,
            )
            why = f"late shipment {imp.shipment_id} of {s.part_id}, new ETA {s.new_eta}"
        moves, _ = plan_moves(world, board, imp)
        actions += moves_to_actions(imp, moves, s.incident_id)
        all_moves += moves
        cause |= {m.po.id: why for m in moves}
    return all_moves, actions, cause


def run_event_wide(run, ctx, tl, with_loaners=True):
    run(
        DEALER_NETWORK,
        ctx,
        tl,
        [
            T("customer_orders_of", {"po_ids": ctx.moved_po_ids()}),
            lambda: T("compose_notices", {"by_dealer": last(ctx, "by_dealer")}),
            T("submit_dealer_plan", {}),
            FINAL({"task": "dealer_comms"}),
        ],
    )
    if not with_loaners:
        return
    dealer = ctx.world.customer_orders[ctx.affected_co_ids()[0]].dealer_id
    run(
        CUSTOMER_CARE_QUALITY,
        ctx,
        tl,
        [
            T("eligible_customers", {"co_ids": ctx.affected_co_ids()}),
            T("loaner_availability", {"dealer_id": dealer}),
            lambda: T("rank_and_assign", {"eligible": last(ctx, "eligible")}),
            T("submit_care_plan", {"task": "loaners"}),
            FINAL({"task": "loaners"}),
        ],
    )


# --- equality with v1 ------------------------------------------------------------------------------------------


def test_e11_supply_chain_equals_v1(make, world, graph):
    build, run = make
    ctx, tl = build("E-11", E11)
    res = run(
        SUPPLY_CHAIN_PLANNER,
        ctx,
        tl,
        [T("get_schedule", {"plant_id": "P_MS", "date": "2027-03-31"}), *sc_script("E-11#1")],
    )
    _, v1, _ = v1_moves(world, graph, [E11])
    assert sig(ctx.plan.actions()) == sig(v1) and len(v1) > 0
    assert all(a.agent == "supply_chain_planner" and a.incident_ids == ["E-11#1"] for a in ctx.plan.actions())
    assert res.final is not None
    assert next(iter(ctx.plan.results.values())).actions_count == len(v1)
    read = ctx.plan.reads[0]
    assert read.tool == "mes.get_schedule" and read.transport == "twin" and read.result.ok


def test_e11_full_event_equals_v1(make, world, graph):
    build, run = make
    ctx, tl = build("E-11", E11)
    run(SUPPLY_CHAIN_PLANNER, ctx, tl, sc_script("E-11#1"))
    run_event_wide(run, ctx, tl)
    moves, mv_actions, cause = v1_moves(world, graph, [E11])
    care = plan_care(world, moves, dict(world.loaner_pool), incident_id="E-11#1", cause=cause, loaner_given_to=set())
    assert sig(ctx.plan.actions()) == sig(mv_actions + care)
    assert {a.tool for a in ctx.plan.actions()} >= {"mes.reschedule", "dealer.notify"}
    assert {a.agent for a in ctx.plan.by_task()["dealer_comms"]} == {"dealer_network"}
    assert all(a.agent == "customer_care_quality" for a in ctx.plan.by_task()["loaners"])
    assert not blocking(validate(world, graph, ctx.incidents, ctx.plan.actions()))


def quality_run(run, ctx, tl):
    run(
        CUSTOMER_CARE_QUALITY,
        ctx,
        tl,
        [
            T("match_lot", {"incident_id": "E-03#1"}),
            T("affected_vehicles", {"lot_id": "LOT-0130"}),
            T("compose_hold", {"lot_id": "LOT-0130"}),
            lambda: T("compose_owner_contacts", {"incident_id": "E-03#1", "owners": last(ctx, "owners")}),
            T("submit_care_plan", {"task": "quality_hold", "incident_id": "E-03#1"}),
            FINAL({"task": "quality_hold"}),
        ],
    )
    run(
        DEALER_NETWORK,
        ctx,
        tl,
        [
            lambda: T(
                "compose_stop_sales", {"incident_id": "E-03#1", "vins_by_dealer": last(ctx, "in_stock_by_dealer")}
            ),
            T("submit_dealer_plan", {}),
            FINAL({"task": "dealer_comms"}),
        ],
    )


def test_e03_quality_equals_v1(make, world, graph):
    build, run = make
    ctx, tl = build("E-03", E03)
    quality_run(run, ctx, tl)
    q = impact_lot(graph, world, "LOT-0130")
    v1 = plan_quality(world, q, incident_id="E-03#1", reason="SUP-06 reported a defect in CHIP-IVI")
    assert sig(ctx.plan.actions()) == sig(v1)
    assert {a.tool for a in ctx.plan.actions()} == {"quality.hold_lot", "dealer.stop_sale", "crm.notify_customer"}
    assert not validate(world, graph, ctx.incidents, ctx.plan.actions())


def test_e01_compound_shares_board_and_pool(make, world, graph):
    build, run = make
    ctx, tl = build("E-01", E01A, E01B)
    run(SUPPLY_CHAIN_PLANNER, ctx, tl, sc_script("E-01#1"))
    run(SUPPLY_CHAIN_PLANNER, ctx, tl, sc_script("E-01#2"))
    run_event_wide(run, ctx, tl)
    moves, mv_actions, cause = v1_moves(world, graph, [E01A, E01B])
    care = plan_care(world, moves, dict(world.loaner_pool), incident_id=None, cause=cause, loaner_given_to=set())
    assert sig(ctx.plan.actions()) == sig(mv_actions + care)
    notices = [a for a in ctx.plan.actions() if a.tool == "dealer.notify"]
    assert len({a.args["dealer_id"] for a in notices}) == len(notices)  # one per dealer for the whole event
    assert not blocking(validate(world, graph, ctx.incidents, ctx.plan.actions()))


def test_propose_slots_idempotent_and_order_independent(make, world, graph):
    build, run = make
    ctx, tl = build("E-01", E01A, E01B)
    # incident 2 first, then 1, then 2 again: the result must equal the text-order v1 plan
    run(
        SUPPLY_CHAIN_PLANNER,
        ctx,
        tl,
        [
            T("propose_slots", {"incident_id": "E-01#2"}),
            T("propose_slots", {"incident_id": "E-01#1"}),
            T("propose_slots", {"incident_id": "E-01#2"}),
            T("submit_reschedule_plan", {"incident_id": "E-01#1"}),
            T("submit_reschedule_plan", {"incident_id": "E-01#2"}),
            T("submit_reschedule_plan", {"incident_id": "E-01#2"}),  # replaces, never duplicates
            FINAL({"task": "reschedule"}),
        ],
    )
    _, v1, _ = v1_moves(world, graph, [E01A, E01B])
    assert sig(ctx.plan.actions()) == sig(v1)
    assert len(ctx.plan.results) == 2


def test_set_result_replaces(make):
    build, run = make
    ctx, tl = build("E-11", E11)
    run(SUPPLY_CHAIN_PLANNER, ctx, tl, sc_script("E-11#1"))
    n = len(ctx.plan.actions())
    run(SUPPLY_CHAIN_PLANNER, ctx, tl, sc_script("E-11#1"))
    assert len(ctx.plan.actions()) == n and len(ctx.plan.results) == 1


# --- handles ---------------------------------------------------------------------------------------------------


def test_handles_resolve_and_unknown_rejected(make, world, graph):
    build, run = make
    ctx, _ = build("E-11", E11)
    from control_tower.orchestration.specialist_tools import (
        CustomerOrdersArgs,
        ProposeSlotsArgs,
        customer_orders_of,
        propose_slots,
        stash,
    )

    propose_slots(ctx, ProposeSlotsArgs(incident_id="E-11#1"))
    pos = ctx.moved_po_ids()
    h = stash(ctx, "pos", pos)
    out = customer_orders_of(ctx, CustomerOrdersArgs(po_ids=h))
    assert out["po_count"] == len(pos)
    assert resolve(ctx, {"count": len(pos), "sample": [], "stored_key": h}) == pos
    assert isinstance(resolve(ctx, out["by_dealer"]), dict)
    with pytest.raises(ValueError, match="unknown handle"):
        customer_orders_of(ctx, CustomerOrdersArgs(po_ids="h:nope"))


def test_tool_errors_for_unaffected_inputs(make):
    build, run = make
    ctx, _ = build("E-11", E11)
    from control_tower.orchestration.specialist_tools import ComposeNoticesArgs, ProposeSlotsArgs, compose_notices
    from control_tower.orchestration.specialist_tools import propose_slots as ps

    ps(ctx, ProposeSlotsArgs(incident_id="E-11#1"))
    unaffected = next(
        co for co in ctx.world.customer_orders.values() if co.production_order_id not in ctx.moved_po_ids()
    )
    with pytest.raises(ValueError, match="not a customer order of a moved"):
        compose_notices(ctx, ComposeNoticesArgs(by_dealer={unaffected.dealer_id: [unaffected.id]}))


# --- validators ------------------------------------------------------------------------------------------------


@pytest.fixture
def good_e01(make, world, graph):
    build, run = make
    ctx, tl = build("E-01", E01A, E01B)
    run(SUPPLY_CHAIN_PLANNER, ctx, tl, sc_script("E-01#1"))
    run(SUPPLY_CHAIN_PLANNER, ctx, tl, sc_script("E-01#2"))
    run_event_wide(run, ctx, tl)
    return ctx, ctx.plan.actions()


def rules(findings):
    return sorted((f.rule, f.severity) for f in findings)


def test_validators_clean(good_e01, world, graph):
    ctx, acts = good_e01
    assert validate(world, graph, ctx.incidents, acts) == []


def test_validators_missing_notice(good_e01, world, graph):
    ctx, acts = good_e01
    notice = next(a for a in acts if a.tool == "dealer.notify")
    f = validate(world, graph, ctx.incidents, [a for a in acts if a is not notice])
    assert rules(f) == [("V3", "blocking")] and "no notice" in f[0].got


def test_validators_unaffected_po_move(good_e01, world, graph):
    ctx, acts = good_e01
    moved = {a.args["production_order_id"] for a in acts if a.tool.startswith("mes.")}
    po = next(p for p in world.production_orders.values() if p.id not in moved and p.build_date >= date(2027, 3, 8))
    extra = Action(
        seq=0,
        incident_id="E-01#1",
        incident_ids=["E-01#1"],
        agent="supply_chain_planner",
        tool="mes.reschedule",
        args={"production_order_id": po.id, "new_date": "2027-04-02"},
        justification="x",
    )
    f = validate(world, graph, ctx.incidents, [*acts, extra])
    assert rules(f) == [("V1", "blocking")] and po.id in str(f[0].got)


def test_validators_over_assigned_loaner(good_e01, world, graph):
    ctx, acts = good_e01
    done = {a.args["customer_order_id"] for a in acts if a.tool == "crm.assign_loaner"}
    affected = {co for a in acts if a.tool == "dealer.notify" for co in a.args["customer_order_ids"]}
    extra_co = sorted(affected - done)[0]
    extra = Action(
        seq=0,
        incident_id="E-01#1",
        incident_ids=["E-01#1"],
        agent="customer_care_quality",
        tool="crm.assign_loaner",
        args={"customer_order_id": extra_co},
        justification="x",
    )
    f = validate(world, graph, ctx.incidents, [*acts, extra])
    assert rules(f) == [("V4", "blocking")]


def test_validators_dropped_stop_sale(make, world, graph):
    build, run = make
    ctx, tl = build("E-03", E03)
    quality_run(run, ctx, tl)
    acts = ctx.plan.actions()
    stop = next(a for a in acts if a.tool == "dealer.stop_sale")
    f = validate(world, graph, ctx.incidents, [a for a in acts if a is not stop])
    assert rules(f) == [("V5", "blocking")]
    assert stop.args["dealer_id"] in f[0].got["missing_dealers"]


def test_validators_wrong_slot_and_noise_and_rule9(good_e01, world, graph):
    ctx, acts = good_e01
    mv = next(a for a in acts if a.tool == "mes.reschedule")
    bad = mv.model_copy(update={"args": {**mv.args, "new_date": "2027-04-02"}})
    f = validate(world, graph, ctx.incidents, [bad if a is mv else a for a in acts])
    assert ("V2", "blocking") in rules(f)
    noise = spec("E-01", 3, "noise")
    stray = Action(
        seq=0,
        incident_id="E-01#3",
        incident_ids=["E-01#3"],
        agent="coordinator",
        tool="quality.hold_lot",
        args={"lot_id": "LOT-0130"},
        justification="x",
    )
    inc = {**ctx.incidents, "E-01#3": noise}
    f = validate(world, graph, inc, [*acts, stray])
    assert rules(f) == [("V8", "blocking")]
    # rule 9 is a warning only
    only_moves = [a for a in acts if a.tool.startswith("mes.")]
    f = validate(world, graph, {"E-11#1": E11}, [a for a in only_moves if False])
    assert all(x.severity in {"blocking", "warning"} for x in f)


def test_v7_is_warning(make, world, graph):
    build, run = make
    ctx, tl = build("E-11", E11)
    run(SUPPLY_CHAIN_PLANNER, ctx, tl, sc_script("E-11#1"))
    f = validate(world, graph, ctx.incidents, ctx.plan.actions())
    assert ("V7", "warning") in rules(f)  # moves alone are 1 kind
    assert all(x.severity == "warning" for x in f if x.rule == "V7")


def test_escalate_exempt_from_v8(world, graph):
    esc = Action(
        seq=0, incident_id="E-05#1", agent="coordinator", tool="escalate", args={"reason": "r"}, justification="x"
    )
    s = spec("E-05", 1, "unconfirmed")
    assert validate(world, graph, {"E-05#1": s}, [esc]) == []


# --- graph / import hygiene ------------------------------------------------------------------------------------


def test_summary_paths_end_in_customers_group(world, graph):
    imp = impact_outage(graph, world, plant_id="P_MS", start=date(2027, 3, 26), end=date(2027, 3, 30))
    p = imp.summary_paths[0]
    node = next(n for n in p.nodes if n.id.startswith("grp:customers:"))
    assert node.type == "Customer" and node.group == "customers" and node.count >= 1
    assert any(e.type == "FOR" and e.to == node.id and e.from_.startswith("grp:cos:") for e in p.edges)


def test_validators_has_no_llm_imports():
    from pathlib import Path

    src = (Path(__file__).resolve().parents[2] / "src/control_tower/planning/validators.py").read_text()
    for line in src.splitlines():
        if line.startswith(("import ", "from ")):
            assert not any(b in line for b in ("anthropic", "google", "control_tower.llm", "orchestration"))
