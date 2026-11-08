"""The agent loop with a scripted fake backend: tool -> final, bad tool -> retry, max_turns, compaction. No network."""

import json

import pytest
from pydantic import BaseModel

from control_tower.llm import adapter
from control_tower.llm.adapter import RawResponse
from control_tower.orchestration import runtime
from control_tower.orchestration.config import AgentConfig
from control_tower.orchestration.runtime import AgentSpec, Turn, run_agent
from control_tower.orchestration.tools import REGISTRY, ToolContext, compact, render_tools, tools_for
from control_tower.trace import Sink, Timeline


class Answer(BaseModel):
    plant_name: str


class Scripted:
    name = "fake"

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def generate_json(self, model, system, user, schema):
        self.prompts.append(user)
        return RawResponse(text=json.dumps(self.replies.pop(0)), input_tokens=100, output_tokens=10)


def tool_turn(tool, args, thought="thinking"):
    return {"thought": thought, "action_tool": tool, "action_args": args}


def final_turn(final, thought="done"):
    return {"thought": thought, "final": final}


@pytest.fixture
def setup(monkeypatch, world):
    adapter.LEDGER.calls.clear()
    monkeypatch.setattr(runtime, "agent_config", lambda _id: AgentConfig(provider="fake", model="m", max_turns=4))

    def make(replies):
        fake = Scripted(replies)
        adapter.register_backend("fake", fake)
        spec = AgentSpec("coordinator", "Coordinator", "You are a test agent.", tools_for("coordinator"), Answer)
        tl = Timeline("E-99", "2027-03-08T09:00:00", Sink(None))
        return fake, spec, tl, ToolContext(world=world, event_id="E-99")

    return make


def test_tool_then_final(setup):
    fake, spec, tl, ctx = setup(
        [tool_turn("lookup_record", {"record_id": "P_TX"}), final_turn({"plant_name": "Texas"})]
    )
    res = run_agent(spec, "name the plant", {"plant": "P_TX"}, ctx, tl)
    assert res.error is None and isinstance(res.final, Answer) and res.turns == 2 and res.llm_calls == 2
    assert "lookup_record" in fake.prompts[1] and "PREVIOUS TOOL CALLS" in fake.prompts[1]
    steps = tl.runs["coordinator"].steps
    assert [s.kind for s in steps] == ["thought", "tool", "thought", "decision"]
    tool_step = steps[1]
    assert tool_step.tool == "lookup_record" and tool_step.args == {"record_id": "P_TX"}
    assert tool_step.transport == "in-process" and tool_step.turn == 1 and tool_step.result["found"] is True
    assert steps[0].model == "m" and steps[0].cost_usd is not None
    assert tl.runs["coordinator"].llm_calls == 2 and len(tl.llm_calls) == 2


def test_bad_tool_name_retries_once_then_final(setup):
    fake, spec, tl, ctx = setup([tool_turn("nope", {}), final_turn({"plant_name": "x"})])
    res = run_agent(spec, "t", {}, ctx, tl)
    assert res.error is None and res.turns == 2
    assert "unknown tool 'nope'" in fake.prompts[1]


def test_bad_args_then_bad_again_fails(setup):
    _, spec, tl, ctx = setup([tool_turn("lookup_record", {}), tool_turn("lookup_record", {"wrong": 1})])
    res = run_agent(spec, "t", {}, ctx, tl)
    assert res.final is None and "bad args" in res.error


def test_invalid_final_schema_retries(setup):
    fake, spec, tl, ctx = setup([final_turn({"nothing": 1}), final_turn({"plant_name": "ok"})])
    res = run_agent(spec, "t", {}, ctx, tl)
    assert res.error is None and "result schema" in fake.prompts[1]


def test_max_turns_exceeded(setup):
    _, spec, tl, ctx = setup([tool_turn("echo", {"text": str(i)}) for i in range(4)])
    res = run_agent(spec, "t", {}, ctx, tl)
    assert res.final is None and "max_turns=4" in res.error and res.turns == 4


def test_long_lists_are_compacted_and_stored():
    store: dict = {}
    out = compact({"ids": [f"PO-{i}" for i in range(30)], "few": [1, 2, 3]}, store, "k")
    assert out["few"] == [1, 2, 3]
    assert out["ids"] == {"count": 30, "sample": ["PO-0", "PO-1", "PO-2", "PO-3", "PO-4"], "stored_key": "k.ids"}
    assert len(store["k.ids"]) == 30


def test_turn_requires_exactly_one_action():
    with pytest.raises(ValueError):
        Turn(thought="x")
    with pytest.raises(ValueError):
        Turn(thought="x", action_tool="echo", final={})


def test_registry_and_render():
    assert {"echo", "lookup_record"} <= set(REGISTRY)
    text = render_tools(tools_for("coordinator"))
    assert "lookup_record" in text and "[graph]" in text and "record_id" in text
    assert REGISTRY["lookup_record"].args_schema["required"] == ["record_id"]


def test_lookup_record_finds_tables(world):
    ctx = ToolContext(world=world)
    fn = REGISTRY["lookup_record"].fn
    args = REGISTRY["lookup_record"].args_model
    plant = next(iter(world.plants))
    r = fn(ctx, args(record_id=plant))
    assert r["found"] and r["type"] == "plant" and r["record"]["plant_id"] == plant
    po = next(iter(world.production_orders))
    assert fn(ctx, args(record_id=po))["type"] == "production_order"
    assert fn(ctx, args(record_id="ZZZ"))["found"] is False
