"""v0.2.0 is additive: every committed v1 trace still validates; planner zone stays free of LLM imports."""

import json
from pathlib import Path

import pytest

from control_tower.schemas import Trace

ROOT = Path(__file__).resolve().parents[2]
TRACES = sorted(p for d in ("snapshot", "final", "examples") for p in (ROOT / "traces" / d).glob("E-*.json"))


@pytest.mark.parametrize("path", TRACES, ids=[f"{p.parent.name}/{p.stem}" for p in TRACES])
def test_v1_trace_validates(path: Path) -> None:
    Trace.model_validate(json.loads(path.read_text()))


def test_v2_fields_roundtrip() -> None:
    t = Trace.model_validate(json.loads((ROOT / "traces" / "examples" / "E-12.json").read_text()))
    assert t.orchestration is None
    d = t.model_dump(mode="json")
    d["pipeline_version"] = "0.2.0"
    d["orchestration"] = {
        "mode": "parallel",
        "correction_rounds": 1,
        "escalations": [{"incident_id": "E-12#1", "reason": "x"}],
    }
    d["agents"].append(
        {"agent": "dealer_network", "started": d["received_at"], "model": "m", "llm_calls": 2, "cost_usd": 0.01,
         "steps": [{"t": d["received_at"], "kind": "tool", "text": "x", "turn": 1, "tool": "echo", "args": {}, "result": {},
                    "transport": "mcp/stdio", "model": "m", "cost_usd": 0.0}]}
    )  # fmt: skip
    assert Trace.model_validate(d).orchestration.mode == "parallel"


def test_planner_zone_has_no_llm_imports() -> None:
    banned = ("anthropic", "google", "control_tower.llm", "control_tower.understanding", "control_tower.orchestration")
    for pkg in ("planning", "graph", "world"):
        for py in (ROOT / "src" / "control_tower" / pkg).glob("*.py"):
            for line in py.read_text().splitlines():
                if line.startswith(("import ", "from ")):
                    assert not any(b in line for b in banned), f"{py.name}: {line}"
