"""Adapter behaviour with a fake backend: validation retry, ledger, no cache. No network."""

import json

import pytest
from pydantic import BaseModel

from control_tower.llm import adapter
from control_tower.llm.adapter import LLMValidationError, RawResponse, complete_json


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
def isolated():
    adapter.LEDGER.calls.clear()
    yield


def test_every_call_is_live_and_ledgered():
    fake = FakeBackend([json.dumps({"plant_id": "P_TX", "days": 2})] * 2)
    adapter.register_backend("fake", fake)
    out, call = complete_json(Toy, "sys", "user", "extract", provider="fake", model="m")
    assert out == Toy(plant_id="P_TX", days=2)
    assert call.input_tokens == 100 and not call.cached
    out2, call2 = complete_json(Toy, "sys", "user", "extract", provider="fake", model="m")
    assert out2 == out and not call2.cached and fake.calls == 2
    assert len(adapter.LEDGER.calls) == 2


def test_invalid_then_valid_retries_once():
    fake = FakeBackend(['{"plant_id": "P_TX"}', '{"plant_id": "P_TX", "days": 3}'])
    adapter.register_backend("fake", fake)
    out, call = complete_json(Toy, "s", "u", "extract", provider="fake", model="m")
    assert out.days == 3 and fake.calls == 2 and call.input_tokens == 200


def test_twice_invalid_raises():
    adapter.register_backend("fake", FakeBackend(["{}", "{}"]))
    with pytest.raises(LLMValidationError):
        complete_json(Toy, "s", "u", "extract", provider="fake", model="m")


def test_ledger_writes_models_json(tmp_path):
    adapter.register_backend("fake", FakeBackend(['{"plant_id": "P_TX", "days": 1}']))
    complete_json(Toy, "s", "u", "extract", provider="fake", model="m")
    adapter.LEDGER.write(tmp_path / "models.json")
    data = json.loads((tmp_path / "models.json").read_text())
    assert data["models"][0]["calls"] == 1 and data["models"][0]["input_tokens"] == 100
