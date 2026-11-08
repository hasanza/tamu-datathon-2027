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


class Flaky:
    name = "flaky"

    def __init__(self, errors: list[Exception], answer: str) -> None:
        self.errors, self.answer, self.calls = list(errors), answer, 0

    def generate_json(self, model, system, user, schema):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return RawResponse(text=self.answer, input_tokens=100, output_tokens=10)


class ApiError(Exception):
    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code


OK = json.dumps({"plant_id": "P_TX", "days": 2})


def test_transient_errors_are_retried_with_backoff(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(adapter.time, "sleep", sleeps.append)
    fake = Flaky([ApiError(429, "429 RESOURCE_EXHAUSTED"), ApiError(503, "503 UNAVAILABLE")], OK)
    adapter.register_backend("flaky", fake)
    out, call = complete_json(Toy, "s", "u", "extract", provider="flaky", model="m")
    assert out.days == 2 and fake.calls == 3 and call.attempts == 3
    assert 2 <= sleeps[0] < 3.01 and 4 <= sleeps[1] < 5.01


def test_server_supplied_retry_delay_is_honoured_and_capped(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(adapter.time, "sleep", sleeps.append)
    fake = Flaky(
        [ApiError(429, "{'error': {'details': [{'retryDelay': '14s'}]}}"), ApiError(429, "retryDelay: 900s")], OK
    )
    adapter.register_backend("flaky", fake)
    complete_json(Toy, "s", "u", "extract", provider="flaky", model="m")
    assert 14 <= sleeps[0] < 15.01 and 60 <= sleeps[1] < 61.01


def test_transient_error_gives_up_after_the_configured_attempts(monkeypatch):
    monkeypatch.setattr(adapter.time, "sleep", lambda s: None)
    monkeypatch.setenv("CT_LLM_RETRIES", "3")
    fake = Flaky([ApiError(503, "overloaded")] * 9, OK)
    adapter.register_backend("flaky", fake)
    with pytest.raises(adapter.LLMError) as ei:
        complete_json(Toy, "s", "u", "extract", provider="flaky", model="m")
    assert ei.value.kind == "provider" and ei.value.attempts == 3 and fake.calls == 3


def test_401_fails_without_retry(monkeypatch):
    monkeypatch.setattr(adapter.time, "sleep", lambda s: pytest.fail("must not sleep"))
    fake = Flaky([ApiError(401, "invalid API key")], OK)
    adapter.register_backend("flaky", fake)
    with pytest.raises(adapter.LLMError) as ei:
        complete_json(Toy, "s", "u", "extract", provider="flaky", model="m")
    assert ei.value.attempts == 1 and fake.calls == 1
