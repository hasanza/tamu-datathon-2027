"""McpExecutor edge cases: outcome semantics, close(), startup timeout, result parsing."""

import socket
import subprocess
import sys
import threading
import time
import urllib.request

import pytest

from control_tower.data.loader import DATA_DIR, KIT_DIR
from control_tower.schemas.action import ToolResult
from control_tower.world.executor import McpExecutor


@pytest.fixture
def server(tmp_path):
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
    except OSError:
        pytest.skip("cannot open a local port")
    cmd = [sys.executable, str(KIT_DIR / "enterprise_server.py"), "--data", str(DATA_DIR)]
    cmd += ["--events", str(DATA_DIR / "events.json"), "--out", str(tmp_path), "--port", str(port), "--overwrite"]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{url}/events", timeout=1).read()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.skip("enterprise server did not start")
    yield url
    proc.kill()
    proc.wait()


def test_outcome_defaults_from_ok():
    assert ToolResult(ok=True).outcome == "ok"
    assert ToolResult(ok=False, error="x").outcome == "failed"
    assert ToolResult(ok=False, outcome="unknown").outcome == "unknown"


def test_rejection_is_failed_and_closed_is_unknown(server):
    ex = McpExecutor(server)
    bad = ex.call("E-01", "dealer.notify", {"dealer_id": "D-NOPE", "customer_order_ids": ["x"], "message": "m"})
    assert not bad.ok and bad.outcome == "failed" and bad.http_status == 400
    ex.close()
    ex.close()  # idempotent
    after = ex.call("E-01", "mes.get_schedule", {"plant_id": "P_TX", "date": "2027-03-09"})
    assert not after.ok and after.outcome == "unknown" and "closed" in after.error
    assert not ex._thread.is_alive() and ex._loop.is_closed()


def test_unreachable_enterprise_is_unknown():
    with McpExecutor("http://127.0.0.1:1") as ex:  # nothing listens: the write outcome cannot be known
        r = ex.call("E-01", "mes.get_schedule", {"plant_id": "P_TX", "date": "2027-03-09"})
    assert not r.ok and r.outcome == "unknown" and r.http_status == 0


def test_startup_timeout_does_not_leak():
    with pytest.raises(RuntimeError):
        McpExecutor("http://127.0.0.1:1", startup_timeout=0.01)
    assert not [t for t in threading.enumerate() if t.name == "mcp-client" and t.is_alive()]


class _Text:
    def __init__(self, text):
        self.text = text


class _Res:
    def __init__(self, content=(), structured=None, is_error=False):
        self.content = list(content)
        self.structured_content = structured
        self.is_error = is_error


def test_parse_snake_case_fields():
    p = McpExecutor._parse
    assert p(_Res(structured={"a": 1, "http_status": 200})) == {"a": 1, "http_status": 200}
    assert p(_Res(structured={"result": {"a": 1, "http_status": 200}}))["a"] == 1
    assert p(_Res(content=[_Text('{"b": 2, "http_status": 200}')]))["b"] == 2
    for res in (_Res(content=[_Text('{"x": 1}')], is_error=True), _Res(structured={"x": 1}, is_error=True)):
        out = p(res)
        assert "error" in out and out["http_status"] == 0
    assert "non-JSON" in p(_Res(content=[_Text("boom")]))["error"]
