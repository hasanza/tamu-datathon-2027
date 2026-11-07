"""Adapter behaviour with a fake backend: validation retry, caching, replay-only, ledger. No network."""

import json

import pytest
from pydantic import BaseModel

from control_tower.llm import adapter
from control_tower.llm.adapter import LLMReplayMiss, LLMValidationError, RawResponse, complete_json


class Toy(BaseModel):
    plant_id: str
    days: int


class FakeBackend:
    name = "fake"

    def __init__(self, answers: list[str]) -> None:
        self.answers = list(answers)
        self.calls = 0

    def generate_json(self, model, system, user, schema):
        self.calls += 1
        return RawResponse(text=self.answers.pop(0), input_tokens=100, output_tokens=10)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("LLM_REPLAY_ONLY", raising=False)
    adapter.LEDGER.calls.clear()
    yield


def test_valid_answer_is_cached_and_ledgered(tmp_path):
    fake = FakeBackend([json.dumps({"plant_id": "P_TX", "days": 2})])
    adapter.register_backend("fake", fake)
    out, call = complete_json(Toy, "sys", "user", "extract", provider="fake", model="m")
    assert out == Toy(plant_id="P_TX", days=2)
    assert call.input_tokens == 100 and not call.cached
    assert len(list(tmp_path.glob("*.json"))) == 1

    out2, call2 = complete_json(Toy, "sys", "user", "extract", provider="fake", model="m")
    assert out2 == out and call2.cached and fake.calls == 1
    assert len(adapter.LEDGER.calls) == 2


def test_invalid_then_valid_retries_once():
    fake = FakeBackend(['{"plant_id": "P_TX"}', '{"plant_id": "P_TX", "days": 3}'])
    adapter.register_backend("fake", fake)
    out, call = complete_json(Toy, "s", "u", "extract", provider="fake", model="m", use_cache=False)
    assert out.days == 3 and fake.calls == 2 and call.input_tokens == 200


def test_twice_invalid_raises():
    adapter.register_backend("fake", FakeBackend(["{}", "{}"]))
    with pytest.raises(LLMValidationError):
        complete_json(Toy, "s", "u", "extract", provider="fake", model="m", use_cache=False)


def test_replay_only_blocks_network(monkeypatch):
    monkeypatch.setenv("LLM_REPLAY_ONLY", "1")
    adapter.register_backend("fake", FakeBackend(['{"plant_id": "P_TX", "days": 1}']))
    with pytest.raises(LLMReplayMiss):
        complete_json(Toy, "s", "never-seen", "extract", provider="fake", model="m")


def test_ledger_writes_models_json(tmp_path):
    adapter.register_backend("fake", FakeBackend(['{"plant_id": "P_TX", "days": 1}']))
    complete_json(Toy, "s", "u", "extract", provider="fake", model="m", use_cache=False)
    adapter.LEDGER.write(tmp_path / "models.json")
    data = json.loads((tmp_path / "models.json").read_text())
    assert data["models"][0]["calls"] == 1 and data["models"][0]["input_tokens"] == 100
