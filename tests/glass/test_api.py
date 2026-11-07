"""Offline tests for the FastAPI skeleton: example traces + temp run dir, no server, no network."""

import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))  # `api/` lives at the repo root, outside pyproject's pythonpath

from api.app import Settings, create_app, tail_ndjson  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    return Settings(
        traces_dir=ROOT / "traces" / "examples",
        run_dir=tmp_path,
        events_path=ROOT / "hack_the_highway" / "data" / "events.json",
        poll_s=0.01,
    )


@pytest.fixture
def client(cfg):
    return TestClient(create_app(cfg))


def test_events_merge_feed_with_trace_status(client):
    rows = {r["event_id"]: r for r in client.get("/api/events").json()}
    assert len(rows) == 15
    assert (rows["E-12"]["status"], rows["E-12"]["category"]) == ("done", "supplier_delay")
    assert rows["E-05"]["status"] == "noise" and rows["E-02"]["status"] == "escalated"
    assert rows["E-01"]["status"] == "queued" and rows["E-01"]["category"] is None


@pytest.mark.parametrize("eid", ["E-12", "E-05", "E-02"])
def test_example_traces_load_through_the_contract(client, eid):
    r = client.get(f"/api/traces/{eid}")
    assert r.status_code == 200 and r.json()["event_id"] == eid


def test_trace_404s(client):
    assert client.get("/api/traces/E-01").status_code == 404  # valid id, no trace yet
    assert client.get("/api/traces/E-1x").status_code == 404
    assert client.get("/api/traces/..%2Fsecret").status_code == 404


def test_graph_is_merged_deduped_and_keeps_from_alias(client):
    g = client.get("/api/graph/E-12").json()
    ids = [n["id"] for n in g["nodes"]]
    assert len(ids) == len(set(ids)) and "SH-0182" in ids and "grp:cos:E-12#1" in ids
    assert all("from" in e and "to" in e for e in g["edges"])
    keys = [(e["from"], e["to"], e["type"]) for e in g["edges"]]
    assert len(keys) == len(set(keys))
    assert client.get("/api/graph/E-05").json() == {"nodes": [], "edges": []}


def test_actions_and_kpis_from_log(client, cfg):
    rows = [
        {"event_id": "E-12", "tool": "mes.get_schedule", "args": {}, "ok": True},
        {"event_id": "E-12", "tool": "mes.reschedule", "args": {}, "ok": True},
        {"event_id": "E-12", "tool": "mes.reschedule", "args": {}, "ok": False},
        {"event_id": "E-02", "tool": "escalate", "args": {"reason": "x"}, "ok": True},
    ]
    cfg.action_log.write_text("\n".join(json.dumps(r) for r in rows) + '\n{"half')
    a = client.get("/api/actions").json()
    assert [x["write"] for x in a] == [False, True, True, False] and a[0]["line"] == 1
    assert len(client.get("/api/actions", params={"event_id": "E-02"}).json()) == 1
    k = client.get("/api/kpis").json()
    assert (k["actions"], k["writes"], k["failed"], k["escalations"]) == (4, 2, 1, 1)
    assert k["events_total"] == 15 and k["by_status"] == {"done": 1, "noise": 1, "escalated": 1}
    assert "example/example-model" in k["models"]


def test_empty_log_is_empty_not_error(client):
    assert client.get("/api/actions").json() == []
    assert client.get("/api/kpis").json()["failed"] == 0


def test_run_is_not_wired_yet(client):
    assert client.post("/api/run", params={"all": True}).status_code == 501
    assert client.post("/api/run").status_code == 422
    assert client.post("/api/run", params={"event_id": "nope"}).status_code == 422


def test_cors_allows_vite(client):
    r = client.get("/api/kpis", headers={"Origin": "http://localhost:5173"})
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def _collect(path, *, from_start, writer=None, n=1):
    async def run():
        got, calls = [], 0

        async def disconnected():
            nonlocal calls
            calls += 1
            if writer and calls == 2:
                writer()
            return len(got) >= n or calls > 200

        async for m in tail_ndjson(path, from_start=from_start, poll_s=0.001, disconnected=disconnected):
            got.append(m)
        return got

    return asyncio.run(run())


def test_stream_tails_new_lines_only_by_default(cfg):
    path = cfg.stream_file
    path.write_text(json.dumps({"type": "event_received", "payload": {"event_id": "OLD"}}) + "\n")

    def append():
        with path.open("a") as f:
            f.write("not json\n" + json.dumps({"type": "bogus"}) + "\n")
            f.write(json.dumps({"type": "action", "payload": {"event_id": "E-12", "seq": 1}}) + "\n")

    got = _collect(path, from_start=False, writer=append)
    assert got == [{"event": "action", "data": json.dumps({"event_id": "E-12", "seq": 1})}]


def test_stream_replay_and_missing_file(cfg):
    assert _collect(cfg.stream_file, from_start=True, n=1) == []  # file absent: no crash, no messages
    cfg.stream_file.write_text(json.dumps({"type": "event_done", "payload": {"event_id": "E-05"}}) + "\n")
    assert [m["event"] for m in _collect(cfg.stream_file, from_start=True)] == ["event_done"]


def test_stream_waits_for_complete_line(cfg):
    cfg.stream_file.write_text("")

    def partial_then_rest():
        with cfg.stream_file.open("a") as f:
            f.write('{"type": "event_received", "pay')

    assert _collect(cfg.stream_file, from_start=False, writer=partial_then_rest) == []
