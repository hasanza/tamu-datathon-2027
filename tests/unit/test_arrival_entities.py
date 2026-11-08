"""Contract 0.2.4: event_incoming lead-in (run.py) and Brief.entities (report.entities_of)."""

import json
import threading
from pathlib import Path

import pytest

from control_tower import run
from control_tower.data.loader import load_world
from control_tower.orchestration.report import entities_of, incident_brief
from control_tower.schemas.incident import IncidentSpec
from control_tower.schemas.trace import Trace
from control_tower.trace import Sink

ROOT = Path(__file__).resolve().parents[2]
EVENTS = [{"event_id": f"X-{i}", "received_at": "2027-03-08T09:00:00", "source": "email"} for i in range(4)]


@pytest.mark.parametrize("parallel", [1, 3])
def test_announce_once_per_event_before_handle(parallel):
    log, lock = [], threading.Lock()

    def announce(ev):
        with lock:
            log.append(("announce", ev["event_id"]))

    def handle(ev):
        with lock:
            log.append(("handle", ev["event_id"]))

    res = run.run_feed(handle, EVENTS, parallel=parallel, announce=announce, stagger=(0.0, 0.0))
    assert [r[0]["event_id"] for r in res] == [e["event_id"] for e in EVENTS]
    for e in EVENTS:
        assert [k for k, i in log if i == e["event_id"]] == ["announce", "handle"]
    if parallel == 1:
        assert log == [(k, e["event_id"]) for e in EVENTS for k in ("announce", "handle")]


def test_no_announce_by_default():
    assert len(run.run_feed(lambda ev: None, EVENTS)) == len(EVENTS)


def test_announcer_writes_event_incoming_before_event_received(tmp_path):
    sink = Sink(tmp_path / "events.ndjson")
    announce = run.make_announcer(sink, 0)
    assert announce
    ev = EVENTS[0]

    def handle(e):
        sink.emit("event_received", e["event_id"], {"received_at": e["received_at"], "source": e["source"], "text": ""})

    run.run_feed(handle, [ev], announce=announce)
    lines = [json.loads(x) for x in (tmp_path / "events.ndjson").read_text().splitlines()]
    assert [x["type"] for x in lines] == ["event_incoming", "event_received"]
    assert lines[0]["payload"] == {"received_at": ev["received_at"], "source": "email"}


def test_announcer_lead_sleeps_jittered(tmp_path, monkeypatch):
    slept = []
    monkeypatch.setattr(run.time, "sleep", slept.append)
    run.make_announcer(Sink(tmp_path / "e.ndjson"), 1.0)(EVENTS[0])
    assert 0.8 <= slept[0] <= 1.4
    assert run.make_announcer(Sink(None), 1.0) is None


# --- Brief.entities -----------------------------------------------------------------------------------------------


def test_pipeline_version():
    assert Trace.model_fields["pipeline_version"].default == "0.2.4"


def test_entities_supplier_delay_and_quality_hold():
    w = load_world()
    sh = next(iter(w.shipments.values()))
    spec = IncidentSpec(
        incident_id="T#1", event_id="T", category="supplier_delay", confidence=1, plant_id=sh.plant_id,
        part_id=sh.part_id, supplier_id=sh.supplier_id, shipment_id=sh.shipment_id,
        orig_eta=sh.eta_date, new_eta=sh.eta_date.replace(day=28), reason="t",
    )  # fmt: skip
    br = incident_brief(w, spec, [])
    got = entities_of(w, spec, br)
    for want in (w.plants[sh.plant_id].name, sh.part_id, w.parts[sh.part_id].name, sh.shipment_id, br.window):
        assert want in got
    assert len(got) == len(set(got)) and all(got)
    assert entities_of(w, spec)[-1] == br.window  # without a brief the window is built the same way

    lot = next(iter(w.lots.values()))
    q = IncidentSpec(
        incident_id="Q#1", event_id="Q", category="quality_hold", confidence=1, plant_id=lot.plant_id,
        part_id=lot.part_id, lot_id=lot.lot_id, reason="t",
    )  # fmt: skip
    qb = incident_brief(w, q, [])  # nothing held: the title carries the lot id only
    assert entities_of(w, q, qb) == [lot.lot_id]
    assert w.plants[lot.plant_id].name in entities_of(w, q)


def test_fixture_entities_appear_in_brief_text():
    seen = 0
    for p in sorted((ROOT / "traces" / "examples" / "v2").glob("*.json")):
        t = Trace.model_validate(json.loads(p.read_text()))
        assert t.pipeline_version == "0.2.4"
        if not t.brief:
            continue
        b = t.brief
        text = " | ".join(
            [b.headline]
            + [i.title for i in b.incidents]
            + [i.window or "" for i in b.incidents]
            + [i.note or "" for i in b.incidents]
            + [f"{f.value} {f.detail or ''}" for i in b.incidents for f in i.facts]
        )
        assert all(e in text for e in b.entities), p.name
        assert len(b.entities) == len(set(b.entities))
        seen += 1
    assert seen >= 3
