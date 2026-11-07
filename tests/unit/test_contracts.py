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
