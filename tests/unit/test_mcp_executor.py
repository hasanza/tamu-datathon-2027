"""McpExecutor against a real enterprise server subprocess (skips cleanly if no local port can be opened)."""

import json
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from control_tower.data.loader import DATA_DIR, KIT_DIR
from control_tower.world.executor import McpExecutor


def _free_port() -> int:
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]
    except OSError:
        pytest.skip("cannot open a local port")


@pytest.fixture
def server(tmp_path):
    port = _free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            str(KIT_DIR / "enterprise_server.py"),
            "--data",
            str(DATA_DIR),
            "--events",
            str(DATA_DIR / "events.json"),
            "--out",
            str(tmp_path),
            "--port",
            str(port),
            "--overwrite",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
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
    yield url, tmp_path / "action_log.jsonl"
    proc.kill()
    proc.wait()


def test_mcp_executor_reads_and_writes(server, world):
    url, log = server
    co = next(iter(world.customer_orders.values()))
    with McpExecutor(url) as ex:
        assert {"enterprise_act", "enterprise_get_schedule"} <= set(ex.tools)
        assert ex.transport == "mcp/stdio"
        sched = ex.call("E-01", "mes.get_schedule", {"plant_id": "P_TX", "date": "2027-03-09"})
        assert sched.ok and sched.response
        w = ex.call(
            "E-01",
            "dealer.notify",
            {"dealer_id": co.dealer_id, "customer_order_ids": [co.id], "message": "test notice"},
        )
        assert w.ok, w.error
        bad = ex.call(
            "E-01", "dealer.notify", {"dealer_id": "D-NOPE", "customer_order_ids": [co.id], "message": "test notice"}
        )
        assert not bad.ok and bad.error
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    assert [(r["tool"], r["ok"]) for r in rows if r["tool"] == "dealer.notify"] == [
        ("dealer.notify", True),
        ("dealer.notify", False),
    ]
    assert any(r["tool"] == "mes.get_schedule" for r in rows)
