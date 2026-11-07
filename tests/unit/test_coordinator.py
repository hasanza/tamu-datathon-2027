"""Coordinator end-to-end with a scripted extractor (no LLM) and the in-process twin as the enterprise.

Scenarios are synthetic. They exercise the guardrails: noise, unconfirmed, mixed actionable + unclear, compound shared
state, world drift before the first write, a plan that fails rehearsal, and that the grader catches planted mistakes.
"""

import json

import pytest

from control_tower.agents import coordinator as coord_mod
from control_tower.agents.coordinator import Coordinator
from control_tower.schemas.trace import LLMCall, Trace
from control_tower.trace import Sink
from control_tower.understanding.resolve import EntityIndex
from control_tower.understanding.schemas import DateMention, ExtractionResult, RawIncident
from control_tower.world.executor import TwinExecutor
from eval.replay_grader import grade


def _call():
    return LLMCall(provider="fake", model="fake", purpose="extract", input_tokens=1, output_tokens=1, cost_usd=0.0)


def scripted(*incidents: RawIncident):
    def _extractor(source, received_at, text, provider=None, model=None):
        return ExtractionResult(incidents=list(incidents)), _call()

    return _extractor


EVENT = {"event_id": "E-01", "received_at": "2027-03-08T08:00:00", "source": "ops chat", "text": "synthetic"}


def outage(plant, start, end, conf=0.95):
    return RawIncident(
        category="plant_outage", evidence="x", reason="r", confidence=conf, plant=plant,
        outage_start=DateMention(text=start), outage_end=DateMention(text=end),
    )  # fmt: skip


def delay(plant, part, supplier, orig, new):
    return RawIncident(
        category="supplier_delay", evidence="x", reason="r", confidence=0.95, plant=plant, part=part, supplier=supplier,
        original_eta=DateMention(text=orig), new_eta=DateMention(text=new),
    )  # fmt: skip


@pytest.fixture()
def make(world, graph, twin, tmp_path):
    index = EntityIndex(world)

    def _make(extractor, executor=None):
        ex = executor or TwinExecutor(tmp_path / "action_log.jsonl")
        return Coordinator(
            world, graph, index, twin, ex, traces_dir=tmp_path / "traces", sink=Sink(None), extractor=extractor
        ), ex

    return _make


def test_noise_makes_no_calls(make, tmp_path):
    c, _ = make(scripted(RawIncident(category="noise", evidence="x", reason="brochure", confidence=0.99)))
    t = c.handle(EVENT)
    assert t.status == "noise" and t.actions == [] and (tmp_path / "action_log.jsonl").read_text() == ""


def test_unconfirmed_only_escalates(make, tmp_path):
    c, _ = make(
        scripted(RawIncident(category="unconfirmed", evidence="a rumor", reason="r", confidence=0.9, part="some seats"))
    )
    t = c.handle(EVENT)
    assert t.status == "escalated" and [a.tool for a in t.actions] == ["escalate"]
    assert not any(a.writes for a in t.actions)


def test_compound_one_notice_per_dealer_and_clean_replay(make, tmp_path):
    c, _ = make(scripted(outage("the Texas plant", "next Friday", "Monday Mar 22"),
                         delay("Princeton", "infotainment chip", "Quanta", "next Monday", "next Friday")))  # fmt: skip
    t = c.handle(EVENT)
    assert t.status == "done" and t.classification.category == "compound" and len(t.incidents) == 2
    notified = [a.args["dealer_id"] for a in t.actions if a.tool == "dealer.notify"]
    assert len(notified) == len(set(notified))
    assert all(a.result.ok for a in t.actions) and all(a.rehearsal.ok for a in t.actions)
    rows, totals = grade(tmp_path / "action_log.jsonl", tmp_path / "traces")
    assert totals["clean"] == 1, rows


def test_mixed_actionable_and_unclear_acts_on_the_clear_part_and_escalates_the_rest(make):
    vague = RawIncident(category="unconfirmed", evidence="rumor", reason="r", confidence=0.9, plant="Jackson")
    c, _ = make(scripted(outage("the Kentucky plant", "next Tuesday", "next Thursday"), vague))
    t = c.handle(EVENT)
    tools = {a.tool for a in t.actions}
    assert t.status == "done" and "mes.reschedule" in tools and "escalate" in tools
    esc = next(a for a in t.actions if a.tool == "escalate")
    assert esc.seq == max(a.seq for a in t.actions)  # escalation last, after the operational work
    assert all(a.args.get("production_order_id") for a in t.actions if a.tool == "mes.reschedule")


def test_unresolvable_plant_is_escalated_not_guessed(make):
    c, _ = make(scripted(outage("the northern facility", "next Tuesday", "next Thursday")))
    t = c.handle(EVENT)
    assert t.status == "escalated" and not any(a.writes for a in t.actions)


def test_world_drift_aborts_before_any_write(make, tmp_path):
    c, ex = make(scripted(outage("the Kentucky plant", "next Tuesday", "next Thursday")))
    # something else already used up a slot the plan relies on: the live read will not match the baseline
    first = c.handle({**EVENT, "event_id": "E-04"})
    assert first.status == "done"
    second = c.handle({**EVENT, "event_id": "E-04"})  # same event world again: slots/loaners already changed
    assert second.status == "escalated"
    assert not any(a.writes and a.result and a.result.ok for a in second.actions)
    assert "differs" in second.actions[-1].args["reason"]


def test_plan_failing_rehearsal_is_never_executed(make, monkeypatch, tmp_path):
    real = coord_mod.moves_to_actions

    def broken(impact, moves, incident_id):
        acts = real(impact, moves, incident_id)
        acts[0].args["new_date"] = "2027-03-13"  # a Saturday: the twin must reject it
        return acts

    monkeypatch.setattr(coord_mod, "moves_to_actions", broken)
    c, _ = make(scripted(outage("the Kentucky plant", "next Tuesday", "next Thursday")))
    t = c.handle(EVENT)
    assert t.status == "escalated" and "rejected by rehearsal" in t.actions[-1].args["reason"]
    assert all(not a.writes for a in t.actions)
    assert (tmp_path / "action_log.jsonl").read_text().count('"escalate"') == 1  # only the escalation reached the log


def test_trace_roundtrips_through_the_contract(make, tmp_path):
    c, _ = make(scripted(delay("Princeton", "surround view cameras", "Orbit", "next Monday", "Thursday Mar 18")))
    t = c.handle(EVENT)
    again = Trace.model_validate_json((tmp_path / "traces" / "E-01.json").read_text())
    assert again.event_id == t.event_id and len(again.actions) == len(t.actions)
    assert (
        t.world_diff.moved_pos
        and t.counterfactual
        and t.counterfactual.loaners_assigned <= t.counterfactual.loaners_entitled
    )


def _run_and_corrupt(make, tmp_path, mutate):
    c, _ = make(scripted(outage("the Kentucky plant", "next Tuesday", "next Thursday")))
    c.handle(EVENT)
    log = tmp_path / "action_log.jsonl"
    lines = [json.loads(x) for x in log.read_text().splitlines()]
    log.write_text("\n".join(json.dumps(x) for x in mutate(lines)) + "\n")
    return grade(log, tmp_path / "traces")


def test_grader_catches_an_extra_move(make, tmp_path, world):
    def add_extra(lines):
        stray = next(
            p.id
            for p in world.production_orders.values()
            if p.plant_id == "P_TX" and p.build_date.isoformat() == "2027-03-30"
        )
        return [
            *lines,
            {
                "event_id": "E-01",
                "tool": "mes.reschedule",
                "args": {"production_order_id": stray, "new_date": "2027-04-02"},
                "ok": True,
            },
        ]

    rows, totals = _run_and_corrupt(make, tmp_path, add_extra)
    assert totals["clean"] == 0 and any("moved POs differ" in i for i in rows[0]["issues"])


def test_grader_catches_a_missing_notification(make, tmp_path):
    def drop_one(lines):
        i = next(n for n, x in enumerate(lines) if x["tool"] == "dealer.notify")
        return lines[:i] + lines[i + 1 :]

    rows, _ = _run_and_corrupt(make, tmp_path, drop_one)
    assert any("notifications differ" in i for i in rows[0]["issues"])


def test_grader_catches_a_wrong_loaner(make, tmp_path):
    def swap_loaner(lines):
        out = list(lines)
        i = next(n for n, x in enumerate(out) if x["tool"] == "crm.assign_loaner")
        del out[i]  # the entitled customer never got the loaner
        return out

    rows, _ = _run_and_corrupt(make, tmp_path, swap_loaner)
    assert any("loaners differ" in i for i in rows[0]["issues"])
