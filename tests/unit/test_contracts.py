"""The example traces must always validate; the UI is built against them."""

import json
from pathlib import Path

import pytest

from control_tower.schemas import Trace

EXAMPLES = sorted((Path(__file__).resolve().parents[2] / "traces" / "examples").glob("*.json"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_example_trace_validates(path: Path) -> None:
    trace = Trace.model_validate(json.loads(path.read_text()))
    assert trace.event_id == path.stem
    if trace.status in {"noise", "escalated"}:
        assert not [a for a in trace.actions if a.writes], "noise/escalated traces must have no write actions"
    if trace.status == "done":
        kinds = {a.tool for a in trace.actions if a.writes}
        assert len(kinds) >= 3, "a real incident ends with at least three kinds of write action (rule 9)"
        assert all(a.rehearsal and a.rehearsal.ok for a in trace.actions if a.writes)


def test_examples_exist() -> None:
    assert {p.stem for p in EXAMPLES} >= {"E-02", "E-05", "E-12"}


def test_e12_fixture_ids_exist_and_belong_together():
    """The fixture the UI is built on must cite real, consistent ids (a handwritten fixture got one wrong once)."""
    from control_tower.data.loader import load_world

    w = load_world()
    trace = Trace.model_validate(json.loads((EXAMPLES[0].parent / "E-12.json").read_text()))
    for a in trace.actions:
        if a.tool == "dealer.notify":
            for co_id in a.args["customer_order_ids"]:
                assert w.customer_orders[co_id].dealer_id == a.args["dealer_id"]
        if a.tool == "crm.assign_loaner":
            assert w.customers[w.customer_orders[a.args["customer_order_id"]].customer_id].tier in {"Platinum", "Gold"}
    for path in trace.paths["E-12#1"]:
        for e in path.edges:
            if e.type == "FULFILLED_BY" and not e.from_.startswith("grp:"):
                assert w.customer_orders[e.from_].production_order_id == e.to
