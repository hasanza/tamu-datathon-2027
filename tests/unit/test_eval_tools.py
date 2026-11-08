"""Offline checks of the v2 eval tooling: paraphrase-bench signature through the real coordinator agent loop, and the
identity comparison helpers."""

from __future__ import annotations

from control_tower.llm import adapter
from control_tower.understanding.resolve import EntityIndex
from eval import paraphrase_bench as pb
from eval import run_identity as ri
from tests.unit.test_coordinator import E11_RAW, FINAL, FakeLLM, register


def test_paraphrase_signature_reads_the_registered_incidents(monkeypatch, world):
    fake = FakeLLM()
    adapter.register_backend("fake", fake)
    monkeypatch.setenv("CT_MODEL_COORDINATOR", "fake/m")
    fake.scripts["coordinator"] = [register(E11_RAW), FINAL({"ok": True})]
    sig = pb.signature(world, EntityIndex(world), "E-11", "Jackson plant down Mar 26 to Mar 30", "ops chat")
    assert sig == [("plant_outage", "P_MS", None, None, None, "None", "None", "2027-03-26", "2027-03-30", False)]
    assert fake.calls["coordinator"] == 2


def test_paraphrase_signature_skips_noise_and_flags_needs_human(monkeypatch, world):
    from tests.unit.test_coordinator import NOISE, raw_outage

    fake = FakeLLM()
    adapter.register_backend("fake", fake)
    monkeypatch.setenv("CT_MODEL_COORDINATOR", "fake/m")
    fake.scripts["coordinator"] = [
        register(NOISE, raw_outage("the northern facility", "next Tuesday", "next Thursday")),
        FINAL({"ok": True}),
    ]
    (row,) = pb.signature(world, EntityIndex(world), "E-07", "x", "ops chat")
    assert row[0] == "plant_outage" and row[-1] is True


def test_identity_multiset_ignores_reads_and_skipped():
    tr = {"actions": [
        {"tool": "mes.get_schedule", "args": {"a": 1}},
        {"tool": "dealer.notify", "args": {"b": 2, "a": 1}},
        {"tool": "dealer.notify", "args": {"a": 1, "b": 2}, "skipped": True},
    ]}  # fmt: skip
    assert dict(ri.multiset(tr)) == {("dealer.notify", '{"a": 1, "b": 2}'): 1}
