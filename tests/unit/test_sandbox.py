"""Option B: judge events run on a private sandbox enterprise server through MCP; traces say which enterprise they hit."""

from __future__ import annotations

import json
import socket
import sys

import httpx
import pytest

from control_tower import live, run
from control_tower.data.loader import KIT_DIR
from control_tower.llm import adapter
from control_tower.schemas.trace import Orchestration
from tests.unit.test_coordinator import NOISE, T, ev, register, rig  # noqa: F401

EVENT = {
    "event_id": "C-77",
    "received_at": "2027-03-08T09:00:00",
    "source": "ops chat",
    "text": "Lexington loses power.",
}


class FakeProc:
    def terminate(self): ...
    def wait(self, timeout=None): ...


def test_custom_spawns_private_server_and_runs_mcp_sandbox(monkeypatch, tmp_path):
    f = tmp_path / "ev.json"
    f.write_text(json.dumps([EVENT]))
    popen, mains = [], []
    monkeypatch.setattr(live.subprocess, "Popen", lambda cmd, **k: popen.append(cmd) or FakeProc())
    monkeypatch.setattr(live.httpx, "get", lambda *a, **k: httpx.Response(200))
    monkeypatch.setattr(run, "main", lambda argv: mains.append(argv) or 0)
    assert live.main(["--custom", str(f)]) == 0
    cmd = popen[0]
    assert cmd[1].endswith("enterprise_server.py")
    assert cmd[cmd.index("--events") + 1] == str(f.resolve())
    assert cmd[cmd.index("--out") + 1].endswith("runs/custom/sandbox/C-77")
    assert "--overwrite" in cmd and int(cmd[cmd.index("--port") + 1]) > 0
    argv = mains[0]
    assert argv[argv.index("--server") + 1].startswith("http://127.0.0.1:")
    assert argv[argv.index("--executor") + 1] == "mcp" and "--sandbox" in argv and "--dry-run" not in argv
    assert argv[argv.index("--traces-dir") + 1] == "traces/custom"
    assert argv[argv.index("--out") + 1] == "runs/custom" and argv[argv.index("--events-file") + 1] == str(f)


def test_second_custom_event_gets_its_own_server_and_dir(monkeypatch, tmp_path):
    popen = []
    monkeypatch.setattr(live.subprocess, "Popen", lambda cmd, **k: popen.append(cmd) or FakeProc())
    monkeypatch.setattr(live.httpx, "get", lambda *a, **k: httpx.Response(200))
    monkeypatch.setattr(run, "main", lambda argv: 0)
    for eid in ("C-01", "C-02"):
        f = tmp_path / f"{eid}.json"
        f.write_text(json.dumps([{**EVENT, "event_id": eid}]))
        live.main(["--custom", str(f)])
    outs = [c[c.index("--out") + 1] for c in popen]
    assert outs[0].endswith("sandbox/C-01") and outs[1].endswith("sandbox/C-02")


@pytest.mark.parametrize(("flags", "target"), [([], "scored"), (["--sandbox"], "sandbox"), (["--dry-run"], "dry")])
def test_trace_target_from_flags(monkeypatch, tmp_path, flags, target):
    seen = {}

    class Stub:
        mode = "sequential"

        def __init__(self, *a, **k):
            seen.update(k)

        def handle(self, event):
            raise AssertionError("no events")

    f = tmp_path / "ev.json"
    f.write_text("[]")
    monkeypatch.setattr(run, "Coordinator", Stub)
    monkeypatch.setattr(run, "McpExecutor", lambda url: type("E", (), {"name": "mcp"})())
    run.main(["--all", "--events-file", str(f), "--out", str(tmp_path / "o"), *flags])
    assert seen["target"] == target


def test_orchestration_target_default():
    assert Orchestration().target == "scored"
    assert Orchestration(target="dry").target == "dry"


def test_coordinator_stamps_target(rig):  # noqa: F811
    rig.script([register(NOISE), T("drop_noise", {"incident_id": "E-05#1", "reason": "brochure"}), T("finish", {})])
    assert rig.run(ev("E-05"), rig.coordinator(target="sandbox")).orchestration.target == "sandbox"


def test_one_event_server_accepts_its_id_and_rejects_feed_ids(tmp_path):
    f = tmp_path / "ev.json"
    f.write_text(json.dumps([EVENT]))
    import subprocess
    import time

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    p = subprocess.Popen(
        [sys.executable, str(KIT_DIR / "enterprise_server.py"), "--data", str(KIT_DIR / "data"), "--events", str(f),
         "--out", str(tmp_path / "o"), "--port", str(port), "--overwrite"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )  # fmt: skip
    try:
        url = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(f"{url}/events", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.05)
        body = {"tool": "mes.get_schedule", "args": {"plant_id": "P-LEX", "date": "2027-03-09"}}
        assert httpx.post(f"{url}/act", json={"event_id": "E-01", **body}).status_code == 404
        assert httpx.post(f"{url}/act", json={"event_id": "C-77", **body}).status_code != 404
    finally:
        p.terminate()
        p.wait(timeout=5)


class Down:
    """A provider that rejects every call with a non-transient error (no sleeping)."""

    name = "fake"
    calls = 0

    def generate_json(self, *a, **k):
        Down.calls += 1
        e = RuntimeError("401 API key not valid")
        e.code = 401  # type: ignore[attr-defined]
        raise e


def test_provider_outage_fails_the_event_and_sends_nothing(rig):  # noqa: F811
    adapter.register_backend("fake", Down())
    t = rig.run(ev("E-11"))
    assert t.status == "failed" and t.orchestration.provider_failure
    assert t.actions == [] and t.orchestration.escalations == [] and rig.log.read_text() == ""
    assert "LLM provider unavailable" in t.summary and "nothing executed; re-run this event" in t.decision_reason


def test_two_provider_failures_abort_the_run(monkeypatch, tmp_path, capsys):
    from control_tower.orchestration import coordinator_tools as ct
    from control_tower.orchestration import runtime
    from control_tower.orchestration.config import AgentConfig

    adapter.register_backend("fake", Down())
    cfg = lambda _id: AgentConfig(provider="fake", model="m", max_turns=4)  # noqa: E731
    monkeypatch.setattr(runtime, "agent_config", cfg)
    monkeypatch.setattr(ct, "agent_config", cfg)
    f = tmp_path / "ev.json"
    f.write_text(json.dumps([ev(f"E-{i:02d}") for i in range(1, 16)]))
    rc = run.main(
        [
            "--all",
            "--dry-run",
            "--events-file",
            str(f),
            "--out",
            str(tmp_path / "o"),
            "--traces-dir",
            str(tmp_path / "t"),
        ]
    )
    assert rc == 2
    assert sorted(p.name for p in (tmp_path / "t").glob("*.json")) == ["E-01.json", "E-02.json"]
    assert "ABORTED: LLM provider unavailable on 2 consecutive events" in capsys.readouterr().err
