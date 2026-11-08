"""Parallel mode: 4 events at once produce the same per-event action sets as sequential, one trace each, in event order."""

from __future__ import annotations

import json
import threading
from collections import Counter

from control_tower.llm import adapter
from control_tower.orchestration import coordinator as coord_mod
from control_tower.orchestration import coordinator_tools as ct
from control_tower.orchestration import runtime
from control_tower.orchestration.config import AgentConfig
from control_tower.orchestration.context import EventContext
from control_tower.orchestration.coordinator import Coordinator
from control_tower.run import run_feed
from control_tower.trace import Sink
from control_tower.understanding.resolve import EntityIndex
from control_tower.world.executor import TwinExecutor
from tests.unit.test_coordinator import (
    E11_RAW,
    NOISE,
    UNCONFIRMED,
    FakeLLM,
    T,
    acting_flow,
    ev,
    lazy_scripts,
    register,
    sc_script,
)

TL = threading.local()


class ThreadFake(FakeLLM):
    """FakeLLM whose scripts and captured context are per worker thread (one event is handled inside one thread)."""

    @property
    def scripts(self):
        if not hasattr(TL, "scripts"):
            from collections import defaultdict

            TL.scripts = defaultdict(list)
        return TL.scripts

    @scripts.setter
    def scripts(self, _v):  # FakeLLM.__init__ assigns it
        pass

    def generate_json(self, *a, **k):
        # calls is shared; the lock keeps the counter exact
        return super().generate_json(*a, **k)


class _Rig:
    """The pieces lazy_scripts() needs from a rig: the current thread's context and the scripts."""

    @property
    def ctx(self):
        return TL.ctx

    def script(self, coord, sc=(), dn=None, ccq=()):
        s = TL_fake.scripts
        s["coordinator"], s["sc"], s["dn"], s["ccq"] = list(coord), list(sc), list(dn or []), list(ccq)


TL_fake = ThreadFake()


def _scripts_for(eid):
    """(event dict, installer) for four different events."""
    r = _Rig()
    if eid == "E-11":
        dn, ccq = lazy_scripts(r)
        return ev(eid), lambda: r.script(
            [register(E11_RAW), *acting_flow(["E-11#1"])], sc=sc_script("E-11#1"), dn=dn, ccq=ccq
        )
    if eid == "E-02":
        return ev(eid), lambda: r.script([
            register(UNCONFIRMED),
            T("escalate", {"incident_id": "E-02#1", "reason": "rumor", "what_would_make_it_actionable": "ids"}),
            T("finish", {}),
        ])  # fmt: skip
    if eid == "E-05":
        return ev(eid), lambda: r.script(
            [register(NOISE), T("drop_noise", {"incident_id": "E-05#1", "reason": "brochure"}), T("finish", {})]
        )
    dn, ccq = lazy_scripts(r)  # E-12: the same outage again but as its own event id
    return ev(eid), lambda: r.script(
        [register(E11_RAW), *acting_flow([f"{eid}#1"])], sc=sc_script(f"{eid}#1"), dn=dn, ccq=ccq
    )


def _run(monkeypatch, world, graph, twin, tmp_path, parallel):
    adapter.register_backend("fake", TL_fake)
    cfg = lambda _id: AgentConfig(provider="fake", model="m", max_turns=24)  # noqa: E731
    monkeypatch.setattr(runtime, "agent_config", cfg)
    monkeypatch.setattr(ct, "agent_config", cfg)

    class Cap(EventContext):
        def __post_init__(self):
            super().__post_init__()
            TL.ctx = self

    monkeypatch.setattr(coord_mod, "EventContext", Cap)
    log = tmp_path / f"log{parallel}.jsonl"
    coord = Coordinator(
        world, graph, EntityIndex(world), twin, TwinExecutor(log), traces_dir=tmp_path / f"t{parallel}", sink=Sink(tmp_path / f"s{parallel}.ndjson"),
        use_tiebreak=False, mode="parallel" if parallel > 1 else "sequential",
    )  # fmt: skip
    jobs = {e: _scripts_for(e) for e in ("E-11", "E-02", "E-05", "E-12")}

    def handle(event):
        jobs[event["event_id"]][1]()  # install this event's scripts in the current thread
        return coord.handle(event)

    return run_feed(handle, [jobs[e][0] for e in jobs], parallel=parallel), log, tmp_path / f"s{parallel}.ndjson"


def _sets(results):
    return {
        ev_["event_id"]: (tr.status, Counter((a.tool, json.dumps(a.args, sort_keys=True)) for a in tr.actions))
        for ev_, tr, _tb, _w in results
    }


def test_parallel_matches_sequential_action_sets(monkeypatch, world, graph, twin, tmp_path):
    seq, _, _ = _run(monkeypatch, world, graph, twin, tmp_path, 1)
    par, log, stream = _run(monkeypatch, world, graph, twin, tmp_path, 4)
    assert all(tr is not None for _e, tr, _t, _w in seq + par), [tb for _e, tr, tb, _w in par if tr is None]
    assert [e["event_id"] for e, *_ in par] == ["E-11", "E-02", "E-05", "E-12"]  # event order, not completion order
    a, b = _sets(seq), _sets(par)
    assert a == b
    assert a["E-11"][0] == "done" and a["E-02"][0] == "escalated" and a["E-05"][0] == "noise"
    assert {tr.orchestration.mode for _e, tr, *_ in par} == {"parallel"}
    assert {tr.orchestration.mode for _e, tr, *_ in seq} == {"sequential"}
    assert sorted(p.name for p in (tmp_path / "t4").glob("*.json")) == [
        "E-02.json",
        "E-05.json",
        "E-11.json",
        "E-12.json",
    ]
    lines = [json.loads(x) for x in stream.read_text().splitlines()]  # every stream line is intact JSON
    assert {x["event_id"] for x in lines} == {"E-11", "E-02", "E-05", "E-12"}
    assert sum(1 for x in log.read_text().splitlines()) > 40


def test_a_crashing_event_does_not_stop_the_others():
    def handle(event):
        if event["event_id"] == "E-02":
            raise RuntimeError("boom")
        return object()

    out = run_feed(handle, [ev("E-01"), ev("E-02"), ev("E-03")], parallel=3)
    assert [e["event_id"] for e, *_ in out] == ["E-01", "E-02", "E-03"]
    assert out[1][1] is None and "boom" in out[1][2] and out[0][1] is not None and out[2][1] is not None
