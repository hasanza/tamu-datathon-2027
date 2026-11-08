"""live.py: partial (--event) runs merge into runs/live; full runs start fresh. Offline, no server, no LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from control_tower import live, run


def _row(eid: str, n: int) -> str:
    return json.dumps({"event_id": eid, "tool": "t", "n": n})


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(live, "REPO_ROOT", tmp_path)
    (tmp_path / "runs/live").mkdir(parents=True)
    (tmp_path / "traces/live").mkdir(parents=True)
    (tmp_path / "traces/live/E-01.json").write_text("{}")
    return tmp_path


class FakePopen:
    argv: list[str] = []

    def __init__(self, argv, **kw):
        FakePopen.argv = [str(x) for x in argv]
        out = Path(argv[argv.index("--out") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "action_log.jsonl").write_text(_row("E-08", 9) + "\n")

    def terminate(self):
        pass

    def wait(self, timeout=None):
        pass


class _Resp:
    status_code = 200


def test_partial_server_run_merges(repo, monkeypatch):
    old = [_row("E-01", 1), _row("E-08", 2), _row("E-01", 3)]
    (repo / "runs/live/action_log.jsonl").write_text("\n".join(old) + "\n")
    monkeypatch.setattr(live.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(live.httpx, "get", lambda *a, **k: _Resp())
    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        return 0

    monkeypatch.setattr(run, "main", fake_main)
    assert live.main(["--mode", "server", "--event", "E-08"]) == 0
    assert (repo / "traces/live/E-01.json").exists()
    assert (repo / "runs/live/action_log.jsonl").read_text().splitlines() == [old[0], old[2], _row("E-08", 9)]
    assert not (repo / "runs/live/partial").exists()
    out = FakePopen.argv[FakePopen.argv.index("--out") + 1]
    assert out.startswith(str(repo / "runs/live/partial") + "/")
    assert "--overwrite" in FakePopen.argv  # fresh partial dir only
    a = seen["argv"]
    assert a[a.index("--out") + 1] == "runs/live" and a[a.index("--traces-dir") + 1] == "traces/live"


def test_partial_creates_missing_log(repo, monkeypatch):
    monkeypatch.setattr(live.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(live.httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(run, "main", lambda argv: 0)
    live.main(["--mode", "server", "--event", "E-08"])
    assert (repo / "runs/live/action_log.jsonl").read_text() == _row("E-08", 9) + "\n"


def test_full_run_starts_fresh(repo, monkeypatch):
    (repo / "runs/live/action_log.jsonl").write_text(_row("E-01", 1) + "\n")
    monkeypatch.setattr(live.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(live.httpx, "get", lambda *a, **k: _Resp())
    monkeypatch.setattr(run, "main", lambda argv: 0)
    live.main(["--mode", "server"])
    assert not (repo / "traces/live").exists()
    i = FakePopen.argv.index("--out")
    assert FakePopen.argv[i + 1] == str(repo / "runs/live") and "--overwrite" in FakePopen.argv


def test_dry_partial_passes_action_log(repo, monkeypatch):
    (repo / "runs/live/action_log.jsonl").write_text(_row("E-01", 1) + "\n")
    seen = {}

    def fake_main(argv):
        seen["argv"] = argv
        Path(argv[argv.index("--action-log") + 1]).write_text(_row("E-08", 5) + "\n")
        return 0

    monkeypatch.setattr(run, "main", fake_main)
    live.main(["--event", "E-08"])
    assert "--dry-run" in seen["argv"]
    assert (repo / "runs/live/action_log.jsonl").read_text().splitlines() == [_row("E-01", 1), _row("E-08", 5)]
    assert (repo / "traces/live/E-01.json").exists()


def test_models_merge():
    a = {
        "models": [{"provider": "g", "model": "m", "calls": 2, "input_tokens": 1, "output_tokens": 1, "cost_usd": 0.5}],
        "total_cost_usd": 0.5,
    }
    m = live._merge_models(a, a)
    assert m["models"][0]["calls"] == 4 and m["total_cost_usd"] == 1.0


def test_run_action_log_flag_honoured(tmp_path, monkeypatch):
    captured = {}

    class Boom(Exception):
        pass

    def fake_twin(path):
        captured["p"] = path
        raise Boom

    monkeypatch.setattr(run, "TwinExecutor", fake_twin)
    monkeypatch.setattr(run, "REPO_ROOT", tmp_path)
    target = tmp_path / "x" / "log.jsonl"
    with pytest.raises(Boom):
        run.main(["--event", "E-01", "--dry-run", "--out", str(tmp_path / "o"), "--action-log", str(target)])
    assert captured["p"] == target
