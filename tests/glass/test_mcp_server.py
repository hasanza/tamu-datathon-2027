"""Offline tests for the MCP wrapper: an in-process Enterprise behind httpx.MockTransport (no sockets)."""

import json
import sys
from pathlib import Path

import httpx
import pytest

KIT = Path(__file__).resolve().parents[2] / "hack_the_highway"
sys.path.insert(0, str(KIT))
from enterprise import TOOLS, Enterprise, ToolError  # noqa: E402

from control_tower.mcp import server  # noqa: E402


@pytest.fixture(scope="module")
def ent():
    return Enterprise(str(KIT / "data"))


@pytest.fixture(autouse=True)
def fake_server(ent):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path == "/tools":
            return httpx.Response(
                200, json=[{"tool": k, "desc": v["desc"], "args": v["args"]} for k, v in TOOLS.items()]
            )
        body = json.loads(req.content)
        try:
            return httpx.Response(200, json=ent.call(body["event_id"], body["tool"], body["args"]))
        except ToolError as e:
            return httpx.Response(400, json={"error": str(e)})

    server.set_transport(httpx.MockTransport(handler))
    yield
    server.set_transport(None)


def test_get_schedule_returns_server_json():
    r = server.enterprise_get_schedule("T-1", "P_TX", "2027-03-09")
    assert r["http_status"] == 200 and r["free_slots"] == 2 and len(r["orders"]) == 3


def test_loaner_availability():
    r = server.enterprise_loaner_availability("T-1", "D27")
    assert r == {"dealer_id": "D27", "available": 1, "http_status": 200}


def test_act_write_then_error_text_is_verbatim():
    ok = server.enterprise_act("T-2", "quality.hold_lot", {"lot_id": "LOT-0001"})
    assert ok == {"ok": True, "http_status": 200}
    bad = server.enterprise_act("T-2", "quality.hold_lot", {"lot_id": "LOT-9999"})
    assert bad == {"error": "unknown lot_id", "http_status": 400}


def test_act_without_args_defaults_to_empty_object():
    assert server.enterprise_act("T-3", "escalate")["error"] == "reason must be a non-empty string"


def test_non_string_ids_are_not_sent():
    r = server.act(["E-01"], "escalate", {"reason": "x"})  # type: ignore[arg-type]
    assert r["http_status"] == 0 and "not sent" in r["error"]


def test_list_tools():
    r = server.enterprise_list_tools()
    assert r["http_status"] == 200 and {t["tool"] for t in r["tools"]} == set(TOOLS)


def test_unreachable_server_is_data_not_exception():
    def boom(req):
        raise httpx.ConnectError("refused")

    server.set_transport(httpx.MockTransport(boom))
    assert server.enterprise_act("T-1", "escalate", {"reason": "x"})["http_status"] == 0


def test_registered_tool_names():
    import asyncio

    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {
        "enterprise_act",
        "enterprise_get_schedule",
        "enterprise_loaner_availability",
        "enterprise_list_tools",
    }
