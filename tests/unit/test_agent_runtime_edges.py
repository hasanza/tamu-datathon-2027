"""Runtime edge cases: handle uniqueness, provider errors, retry policy, tool schema rendering."""

import json
from typing import Literal

import pytest
from pydantic import BaseModel

from control_tower.llm import adapter
from control_tower.llm.adapter import RawResponse
from control_tower.orchestration import runtime
from control_tower.orchestration.config import AgentConfig
from control_tower.orchestration.runtime import AgentSpec, run_agent
from control_tower.orchestration.tools import ToolContext, ToolSpec, compact, render_tools, tool
from control_tower.trace import Sink, Timeline


class Answer(BaseModel):
    plant_name: str


class NoArgs(BaseModel):
    pass


@tool("test_big_list", {"coordinator"}, "code", "Return two long sibling lists.")
def _big(ctx: ToolContext, args: NoArgs) -> dict:
    return {"a": list(range(25)), "b": list(range(30))}


class Scripted:
    name = "fake"

    def __init__(self, replies):
        self.replies = list(replies)

    def generate_json(self, model, system, user, schema):
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return RawResponse(text=json.dumps(r), input_tokens=10, output_tokens=5)


@pytest.fixture
def make(monkeypatch, world):
    monkeypatch.setattr(runtime, "agent_config", lambda _id: AgentConfig(provider="fake", model="m", max_turns=4))

    def _make(replies):
        fake = Scripted(replies)
        adapter.register_backend("fake", fake)
        spec = AgentSpec("coordinator", "Edge", "sys", [t for t in _specs()], Answer)
        return (
            fake,
            spec,
            Timeline("E-99", "2027-03-08T09:00:00", Sink(None)),
            ToolContext(world=world, event_id="E-99"),
        )

    return _make


def _specs():
    from control_tower.orchestration.tools import tools_for

    return tools_for("coordinator")


def test_sibling_long_lists_get_distinct_handles():
    store: dict = {}
    out = compact({"a": list(range(25)), "b": list(range(30)), "nest": [list(range(21)), list(range(22))]}, store, "k")
    assert out["a"]["stored_key"] != out["b"]["stored_key"]
    assert store[out["a"]["stored_key"]] == list(range(25)) and store[out["b"]["stored_key"]] == list(range(30))
    assert len({x["stored_key"] for x in out["nest"]}) == 2 and len(store) == 4


def test_stored_keys_unique_across_runs(make):
    seen = []
    for _ in range(2):
        _, spec, tl, ctx = make(
            [
                {"thought": "t", "action_tool": "test_big_list", "action_args": {}},
                {"thought": "d", "final": {"plant_name": "x"}},
            ]
        )
        assert run_agent(spec, "t", {}, ctx, tl).error is None
        seen.append(set(ctx.store))
        assert len(ctx.store) == 2
    assert not seen[0] & seen[1]


def test_provider_exception_is_terminal_not_raised(make):
    fake, spec, tl, ctx = make([ValueError("400 bad request")])
    res = run_agent(spec, "t", {}, ctx, tl)
    assert res.final is None and "provider" in res.error and res.llm_calls == 1 and fake.replies == []


def test_schema_failure_is_two_provider_calls_total(make):
    fake, spec, tl, ctx = make([{"nonsense": 1}, {"nonsense": 2}, {"never": 3}])
    res = run_agent(spec, "t", {}, ctx, tl)
    assert res.final is None and "schema" in res.error and res.llm_calls == 2 and len(fake.replies) == 1


def test_schema_retry_inside_adapter_counts_attempts(make):
    _, spec, tl, ctx = make([{"nonsense": 1}, {"thought": "d", "final": {"plant_name": "x"}}])
    res = run_agent(spec, "t", {}, ctx, tl)
    assert res.error is None and res.llm_calls == 2 and tl.runs["coordinator"].llm_calls == 2


def test_render_tools_includes_full_schema():
    class Inner(BaseModel):
        kind: Literal["a", "b"]

    class Args(BaseModel):
        items: list[Inner]

    text = render_tools([ToolSpec("t", "x", "code", "d", Args, lambda c, a: {})])
    assert '"enum":["a","b"]' in text and "$defs" in text


def test_summarize_args():
    from control_tower.orchestration.tools import summarize_args

    assert summarize_args({"incidents": [{"category": "noise"}]}) == "1 incident (noise)"
    assert summarize_args({"po_ids": list("123456789")}) == "9 po_ids"
    assert summarize_args({"by_dealer": "h:E-1:by_dealer:3"}) == "by_dealer list"
    assert summarize_args({"x": None, "y": "", "z": False}) == ""
    assert summarize_args({"meta": {"a": 1, "b": 2}}) == "meta 2 fields"
    s = summarize_args({"plant_id": "P_MS", "n": 3, "po_ids": ["a", "b"], "note": "x" * 40, "extra": 1})
    assert s.startswith("2 po_ids · plant_id P_MS · n 3") and s.endswith("+2 more")
    assert summarize_args({"note": "x" * 40}) == "note " + "x" * 23 + "…"
    assert summarize_args({"tools": [{"tool": "a"}, {"tool": "b"}, {"tool": "a"}]}) == "3 tools (a, b)"
