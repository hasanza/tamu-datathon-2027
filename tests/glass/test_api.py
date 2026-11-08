"""Offline tests for the FastAPI skeleton: example traces + temp run dir, no server, no network."""

import asyncio
import json
import os
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


def test_stream_passes_event_incoming_through(cfg):
    # the runner announces every event about a second before it is received: the feed shows an "Incoming event..." row
    cfg.stream_file.write_text(
        json.dumps({"type": "event_incoming", "event_id": "E-07", "payload": {}})
        + "\n"
        + json.dumps({"type": "event_received", "event_id": "E-07", "payload": {"source": "ops chat"}})
        + "\n"
    )
    got = _collect(cfg.stream_file, from_start=True, n=2)
    assert [m["event"] for m in got] == ["event_incoming", "event_received"]
    assert json.loads(got[0]["data"]) == {"event_id": "E-07"}


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


def _seed_live_run(monkeypatch):
    """A finished full run under the (isolated) ROOT: traces for E-01 and E-08, and their action-log rows."""
    import api.app as appmod

    root = appmod.ROOT
    (root / "traces" / "live").mkdir(parents=True, exist_ok=True)
    (root / "runs" / "live").mkdir(parents=True, exist_ok=True)
    for eid in ("E-01", "E-08"):
        (root / "traces" / "live" / f"{eid}.json").write_text("{}")
    log = root / "runs" / "live" / "action_log.jsonl"
    log.write_text('{"event_id": "E-01"}\n{"event_id": "E-08"}\n')
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda cmd, **kw: FakeProc(0))
    return root, log


def test_single_event_run_keeps_the_other_events(client, monkeypatch):
    root, log = _seed_live_run(monkeypatch)
    assert client.post("/api/run", params={"event_id": "E-01"}).status_code == 202
    assert not (root / "traces" / "live" / "E-01.json").exists()  # only the re-run event is cleared
    assert (root / "traces" / "live" / "E-08.json").exists()
    assert '"E-08"' in log.read_text()  # live.py replaces the re-run event's rows itself


def test_full_run_still_clears_traces_and_log(client, monkeypatch):
    root, log = _seed_live_run(monkeypatch)
    assert client.post("/api/run", params={"all": True}).status_code == 202
    assert list((root / "traces" / "live").glob("E-*.json")) == []
    assert log.read_text() == ""


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
    assert r.status_code == 200 and r.json() == {
        "running": False,
        "mode": None,
        "exit_code": None,
        "started": None,
        "state": None,
        "message": None,
    }
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
        assert cmd[cmd.index("--custom") - 1] == "control_tower.live"
        ev = json.loads(Path(cmd[cmd.index("--custom") + 1]).read_text())[0]
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
        ev = json.loads(Path(cmd[cmd.index("--custom") + 1]).read_text())[0]
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
        ev = json.loads(Path(cmd[cmd.index("--custom") + 1]).read_text())[0]
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


def test_custom_subprocess_gets_the_dirs_the_api_reads(client, cfg, monkeypatch):
    """The pipeline must write where the API reads, not rely on matching defaults (they disagreed once with temp dirs)."""
    import subprocess as sp

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        ev = json.loads(Path(cmd[cmd.index("--custom") + 1]).read_text())[0]
        src = json.loads((ROOT / "traces/examples/E-05.json").read_text())
        src.update(event_id=ev["event_id"], text=ev["text"])
        cfg.custom_dir.mkdir(parents=True, exist_ok=True)
        (cfg.custom_dir / f"{ev['event_id']}.json").write_text(json.dumps(src))
        return sp.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("api.app.subprocess.run", fake_run)
    assert client.post("/api/custom", json={"text": "The Greensboro line is down on Wednesday."}).status_code == 200
    cmd = seen["cmd"]
    assert cmd[cmd.index("--run-dir") + 1] == str(cfg.custom_run_dir)
    assert cmd[cmd.index("--traces-dir") + 1] == str(cfg.custom_dir)


class ExitedProc:
    def __init__(self, code):
        self.returncode = code

    def poll(self):
        return self.returncode


@pytest.mark.parametrize(
    ("code", "stderr", "state", "message"),
    [
        (0, "", "done", None),
        (
            2,
            "warning noise\nABORTED: LLM provider unavailable on 2 consecutive events (429); 13 of 15 events not run\n",
            "aborted",
            "ABORTED: LLM provider unavailable on 2 consecutive events (429); 13 of 15 events not run",
        ),
        (
            2,
            "enterprise server failed to start on port 8123\n",
            "aborted",
            "enterprise server failed to start on port 8123",
        ),
        (1, "Traceback ...\nValueError: boom\n", "failed", "ValueError: boom"),
    ],
)
def test_run_status_names_how_a_run_ended(client, monkeypatch, code, stderr, state, message):
    """Exit 2 is the pipeline giving up on purpose: show it as 'aborted' with the line that says why (CORE #79)."""
    import api.app as appmod

    monkeypatch.setattr(appmod.subprocess, "Popen", lambda cmd, **kw: ExitedProc(code))
    assert client.post("/api/run", params={"all": True}).status_code == 202
    # the API wrote its stderr capture file under the (temp) run dir it switched to; the fake child "writes" to it
    run_stderr = next(Path(appmod.ROOT).rglob("run.stderr"))
    run_stderr.write_text(stderr)
    s = client.get("/api/run/status").json()
    assert (s["exit_code"], s["state"], s["message"], s["running"]) == (code, state, message, False)


class LiveProc:
    """A subprocess that is running until the API signals its process group."""

    pid = 4242

    def __init__(self):
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        return self.returncode


def _start_run(client, monkeypatch, proc):
    import api.app as appmod

    monkeypatch.setattr(appmod.subprocess, "Popen", lambda cmd, **kw: proc)
    assert client.post("/api/run", params={"all": True}).status_code == 202


def test_cancel_stops_the_process_group_and_reports_cancelled(client, monkeypatch):
    import api.app as appmod

    proc = LiveProc()
    signalled = []

    def killpg(pgid, sig):
        signalled.append((pgid, sig))
        proc.returncode = -15  # SIGTERM: the child is gone

    monkeypatch.setattr(appmod.os, "getpgid", lambda pid: 9000 + pid)
    monkeypatch.setattr(appmod.os, "killpg", killpg)
    _start_run(client, monkeypatch, proc)
    assert client.get("/api/run/status").json()["running"] is True
    r = client.post("/api/run/cancel")
    assert r.status_code == 200
    assert signalled == [(9000 + proc.pid, appmod.signal.SIGTERM)]  # the group, so the enterprise server dies with it
    st = client.get("/api/run/status").json()
    assert st["running"] is False and st["state"] == "cancelled" and st["message"] is None


def test_cancel_without_a_run_is_refused(client):
    assert client.post("/api/run/cancel").status_code == 409


def _seed_everything(cfg):
    import api.app as appmod

    root = appmod.ROOT
    cfg.custom_dir.mkdir(parents=True, exist_ok=True)
    (cfg.custom_dir / "C-01.json").write_text("{}")
    (cfg.custom_dir / "C-02.json").write_text("{}")
    (cfg.custom_dir / "C-03.input.json").write_text("[]")  # in flight: not a finished judge event
    (cfg.custom_run_dir / "sandbox" / "C-01").mkdir(parents=True, exist_ok=True)
    (cfg.custom_run_dir / "events.ndjson").write_text("x\n")
    (root / "traces" / "live").mkdir(parents=True, exist_ok=True)
    (root / "traces" / "live" / "E-01.json").write_text("{}")
    (root / "runs" / "live").mkdir(parents=True, exist_ok=True)
    (root / "runs" / "live" / "action_log.jsonl").write_text('{"a": 1}\n{"a": 2}\n')
    return root


def test_reset_preview_counts_what_would_go(client, cfg):
    _seed_everything(cfg)
    assert client.get("/api/reset/preview").json() == {
        "judge_events": 2,
        "live_traces": 1,
        "live_log_rows": 2,
        "running": False,
    }


def test_reset_all_deletes_judge_events_and_the_live_run(client, cfg):
    root = _seed_everything(cfg)
    assert client.post("/api/reset", params={"scope": "all"}).status_code == 200
    assert list(cfg.custom_dir.glob("*.json")) == []  # including the *.input.json
    assert list(cfg.custom_run_dir.iterdir()) == []
    assert list((root / "traces" / "live").iterdir()) == []
    assert list((root / "runs" / "live").iterdir()) == []
    assert client.get("/api/reset/preview").json()["judge_events"] == 0


def test_plain_reset_keeps_the_files(client, cfg):
    root = _seed_everything(cfg)
    assert client.post("/api/reset").status_code == 200
    assert (cfg.custom_dir / "C-01.json").exists() and (root / "traces" / "live" / "E-01.json").exists()


def test_reset_all_is_refused_while_a_run_is_in_progress(client, cfg, monkeypatch):
    _start_run(client, monkeypatch, LiveProc())  # (a full run clears the live traces itself: seed after it started)
    root = _seed_everything(cfg)
    assert client.post("/api/reset", params={"scope": "all"}).status_code == 409
    assert (root / "traces" / "live" / "E-01.json").exists()  # nothing was deleted


def test_cancel_really_kills_the_child_the_runner_started(client, monkeypatch, tmp_path):
    """live.py starts the enterprise server as its child: Cancel must stop both (process group), within 5 s."""
    import subprocess as sp
    import time

    import api.app as appmod

    real_popen = sp.Popen
    pidfile = tmp_path / "child.pid"
    script = f"sleep 60 & echo $! > {pidfile}; wait"
    monkeypatch.setattr(appmod.subprocess, "Popen", lambda cmd, **kw: real_popen(["sh", "-c", script], **kw))
    assert client.post("/api/run", params={"all": True}).status_code == 202
    for _ in range(100):  # the shell writes the pid of its child
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.05)
    child = int(pidfile.read_text())
    t0 = time.time()
    assert client.post("/api/run/cancel").status_code == 200
    assert time.time() - t0 < 5
    for _ in range(100):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("the child of the runner is still alive after Cancel")
    assert client.get("/api/run/status").json()["state"] == "cancelled"
