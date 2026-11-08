"""Offline tests for the FastAPI skeleton: example traces + temp run dir, no server, no network."""

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.app import Settings, create_app, tail_ndjson

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def isolated_root(monkeypatch, tmp_path_factory):
    """POST /api/run deletes stale traces/live/E-*.json under api.app.ROOT: never let a test touch the real repo."""
    import api.app as appmod

    monkeypatch.setattr(appmod, "ROOT", tmp_path_factory.mktemp("root"))


@pytest.fixture
def cfg(tmp_path):
    return Settings(
        traces_dir=ROOT / "traces" / "examples",
        run_dir=tmp_path,
        custom_dir=tmp_path / "custom",
        custom_run_dir=tmp_path / "custom_run",
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


def test_run_starts_subprocess_and_rejects_double_start(client, monkeypatch):
    started = []

    class FakeProc:
        returncode = None

        def poll(self):
            return None

    monkeypatch.setattr("api.app.subprocess.Popen", lambda cmd, **kw: started.append(cmd) or FakeProc())
    assert client.post("/api/run").status_code == 422
    assert client.post("/api/run", params={"event_id": "nope"}).status_code == 422
    r = client.post("/api/run", params={"event_id": "E-11", "mode": "dry"})
    assert r.status_code == 202 and r.json()["running"] is True
    assert started[0][-2:] == ["--event", "E-11"]
    assert client.post("/api/run", params={"all": True}).status_code == 409
    assert client.get("/api/run/status").json()["running"] is True


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


def test_stream_adds_top_level_event_id_to_payload(cfg):
    # CORE's runner writes {"type", "event_id", "payload"}; the SSE data must carry event_id too.
    cfg.stream_file.write_text(
        json.dumps({"type": "event_done", "event_id": "E-05", "payload": {"status": "noise"}}) + "\n"
    )
    (msg,) = _collect(cfg.stream_file, from_start=True)
    assert msg["event"] == "event_done" and json.loads(msg["data"]) == {"status": "noise", "event_id": "E-05"}


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


SNAPSHOT = ROOT / "traces" / "snapshot"


@pytest.fixture
def snap(cfg):
    cfg.traces_dir = SNAPSHOT
    return TestClient(create_app(cfg))


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="no real traces yet")
def test_every_real_trace_passes_the_contract_and_graph_merge(snap):
    rows = snap.get("/api/events").json()
    assert len(rows) == 15 and all(r["status"] != "queued" for r in rows)
    for r in rows:
        eid = r["event_id"]
        assert snap.get(f"/api/traces/{eid}").status_code == 200, eid
        g = snap.get(f"/api/graph/{eid}").json()
        ids = [n["id"] for n in g["nodes"]]
        assert len(ids) == len(set(ids)), eid
        assert all(e["from"] in ids and e["to"] in ids for e in g["edges"]), f"dangling edge in {eid}"


@pytest.mark.skipif(not SNAPSHOT.exists(), reason="no real traces yet")
def test_real_traces_status_mix_and_no_writes_on_noise_or_escalation(snap):
    by = {r["event_id"]: r for r in snap.get("/api/events").json()}
    assert {by[e]["status"] for e in ("E-05", "E-06", "E-07")} == {"noise"}
    assert {by[e]["status"] for e in ("E-02", "E-13")} == {"escalated"}
    for eid in ("E-05", "E-06", "E-07", "E-02", "E-13"):
        t = snap.get(f"/api/traces/{eid}").json()
        assert not [
            a for a in t["actions"] if a["tool"] not in ("escalate", "mes.get_schedule", "crm.loaner_availability")
        ]


class FakeProc:
    def __init__(self, code=None):
        self.code, self.returncode = code, code

    def poll(self):
        return self.code


def test_run_endpoints(client, monkeypatch):
    import api.app as appmod

    started = []
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda cmd, **kw: started.append(cmd) or FakeProc())
    assert client.get("/api/run/status").json()["running"] is False
    assert client.post("/api/run").status_code == 422
    assert client.post("/api/run", params={"event_id": "bad"}).status_code == 422
    assert client.post("/api/run", params={"all": True, "mode": "rm -rf"}).status_code == 422
    r = client.post("/api/run", params={"all": True, "mode": "dry", "pace": 0})
    assert r.status_code == 202 and r.json()["running"] and r.json()["mode"] == "dry"
    cmd = started[0]
    assert cmd[1:3] == ["-m", "control_tower.live"] and "--event" not in cmd
    assert client.post("/api/run", params={"all": True}).status_code == 409  # one run at a time
    assert len(started) == 1


def test_run_single_event_passes_event_flag(client, monkeypatch):
    import api.app as appmod

    started = []
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda cmd, **kw: started.append(cmd) or FakeProc(0))
    assert client.post("/api/run", params={"event_id": "E-12"}).status_code == 202
    assert started[0][-2:] == ["--event", "E-12"]
    assert client.get("/api/run/status").json() == {
        **client.get("/api/run/status").json(),
        "running": False,
        "exit_code": 0,
    }


def test_stream_follows_run_dir_switch(tmp_path):
    # A client connected before POST /api/run must receive the new run's events (cfg.run_dir changes mid-stream).
    old, new = tmp_path / "old.ndjson", tmp_path / "new.ndjson"
    old.write_text("")
    current = {"p": old}

    def switch_and_write():
        current["p"] = new
        new.write_text(json.dumps({"type": "event_received", "payload": {"event_id": "E-01"}}) + "\n")

    got = _collect(lambda: current["p"], from_start=False, writer=switch_and_write)
    assert [m["event"] for m in got] == ["event_received"]


def test_reset_returns_to_the_startup_directories(client, cfg, monkeypatch):
    import api.app as appmod

    start = (cfg.traces_dir, cfg.run_dir)
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda cmd, **kw: FakeProc(0))
    assert client.post("/api/run", params={"all": True}).status_code == 202
    assert (cfg.traces_dir, cfg.run_dir) != start  # run switched to traces/live + runs/live (under the temp ROOT)
    r = client.post("/api/reset")
    assert r.status_code == 200 and r.json() == {"running": False, "mode": None, "exit_code": None, "started": None}
    assert (cfg.traces_dir, cfg.run_dir) == start
    assert client.get("/api/run/status").json()["mode"] is None


def test_reset_refused_while_running(client, monkeypatch):
    import api.app as appmod

    monkeypatch.setattr(appmod.subprocess, "Popen", lambda cmd, **kw: FakeProc())
    client.post("/api/run", params={"all": True})
    assert client.post("/api/reset").status_code == 409


def test_custom_event_sandbox(client, cfg, monkeypatch):
    import subprocess as sp

    seen = {}

    def fake_run(cmd, **kw):
        seen["timeout"] = kw["timeout"]
        assert cmd[-2] == "--custom"
        ev = json.loads(Path(cmd[-1]).read_text())[0]
        assert ev["event_id"] == "C-01" and ev["text"] == "The Huntsville line is down Wednesday."
        src = json.loads((ROOT / "traces/examples/E-05.json").read_text())
        src.update(event_id="C-01", text=ev["text"])
        cfg.custom_dir.mkdir(parents=True, exist_ok=True)
        (cfg.custom_dir / "C-01.json").write_text(json.dumps(src))
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("api.app.subprocess.run", fake_run)
    assert client.post("/api/custom", json={"text": "x"}).status_code == 422
    r = client.post("/api/custom", json={"text": "The Huntsville line is down Wednesday."})
    assert r.status_code == 200 and r.json()["event_id"] == "C-01"
    assert r.json()["target"] == "sandbox"  # a custom event is a sandbox run (contract 0.2.2 will put it on the trace)
    assert seen["timeout"] == 300  # a real LLM run is about two minutes
    assert client.get("/api/traces/C-01").json()["event_id"] == "C-01"
    ev = {e["event_id"]: e for e in client.get("/api/events").json()}
    assert ev["C-01"]["custom"] is True and "E-01" in ev


def test_custom_run_in_flight_does_not_break_events_or_numbering(client, cfg, monkeypatch):
    """While a custom event runs, its input file C-nn.input.json sits next to the finished traces. v2 runs take a minute,
    so the window is long: /api/events used to answer 500 (the input is not a Trace) and a second POST crashed on int('01.input')."""
    import subprocess as sp

    cfg.custom_dir.mkdir(parents=True, exist_ok=True)
    done = json.loads((ROOT / "traces/examples/E-05.json").read_text())
    done.update(event_id="C-01", text="finished earlier")
    (cfg.custom_dir / "C-01.json").write_text(json.dumps(done))
    (cfg.custom_dir / "C-02.input.json").write_text(
        json.dumps([{"event_id": "C-02", "text": "still running"}])
    )  # in flight

    r = client.get("/api/events")
    assert r.status_code == 200
    assert [e["event_id"] for e in r.json() if e.get("custom")] == ["C-01"]  # the input file is not an event

    def fake_run(cmd, **kw):  # a second submission while C-02 is still in flight must NOT reuse C-02: it takes C-03
        ev = json.loads(Path(cmd[-1]).read_text())[0]
        assert ev["event_id"] == "C-03"
        done.update(event_id=ev["event_id"], text=ev["text"])
        (cfg.custom_dir / f"{ev['event_id']}.json").write_text(json.dumps(done))
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("api.app.subprocess.run", fake_run)
    r = client.post("/api/custom", json={"text": "A second message arrives while the first is running."})
    assert r.status_code == 200 and r.json()["event_id"] == "C-03"
    assert (cfg.custom_dir / "C-02.input.json").exists()  # the run in flight was not disturbed


def test_stream_tails_run_and_custom_streams_together(tmp_path):
    a, b = tmp_path / "run.ndjson", tmp_path / "custom.ndjson"
    a.write_text("")
    b.write_text("")

    def write_both():
        a.write_text(json.dumps({"type": "event_received", "payload": {"event_id": "E-01"}}) + "\n")
        b.write_text(json.dumps({"type": "event_received", "payload": {"event_id": "C-01"}}) + "\n")

    got = _collect(lambda: [a, b], from_start=False, writer=write_both, n=2)
    assert sorted(json.loads(m["data"])["event_id"] for m in got) == ["C-01", "E-01"]


def test_custom_follow_up_appends_operator_details(client, cfg, monkeypatch):
    import subprocess as sp

    seen = {}

    def fake_run(cmd, **kw):
        ev = json.loads(Path(cmd[-1]).read_text())[0]
        seen.update(ev)
        src = json.loads((ROOT / "traces/examples/E-02.json").read_text())
        src.update(event_id=ev["event_id"], text=ev["text"], source=ev["source"])
        cfg.custom_dir.mkdir(parents=True, exist_ok=True)
        (cfg.custom_dir / f"{ev['event_id']}.json").write_text(json.dumps(src))
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("api.app.subprocess.run", fake_run)
    assert client.post("/api/custom", json={"parent_id": "E-02"}).status_code == 422  # details required
    assert client.post("/api/custom", json={"parent_id": "E-99", "details": "SH-0190 slipped"}).status_code == 404
    r = client.post("/api/custom", json={"parent_id": "E-02", "details": "It is shipment SH-0190, now due Mar 19."})
    assert r.status_code == 200 and r.json()["parent_id"] == "E-02"
    assert (
        seen["source"] == "follow-up to E-02" and "Follow-up from the operator: It is shipment SH-0190" in seen["text"]
    )
    ev = {e["event_id"]: e for e in client.get("/api/events").json()}
    assert ev["C-01"]["parent_id"] == "E-02"


def test_run_defaults_to_the_scored_server_mode(client, monkeypatch):
    import api.app as appmod

    started = []
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda cmd, **kw: started.append(cmd) or FakeProc())
    r = client.post("/api/run", params={"all": True})  # no mode: feed events always go to the scored server
    assert r.status_code == 202 and r.json()["mode"] == "server"
    assert started[0][started[0].index("--mode") + 1] == "server"
