"""Task 1.4: the digital twin. Rehearse a plan on the organizers' own Enterprise class before any real call.

`from enterprise import Enterprise` is the same validation code the server runs, so a plan that passes here cannot
fail on the server (given the same starting world). Each rehearsal uses a fresh, uniquely named event state.
"""

from __future__ import annotations

import importlib
import sys
import threading
import uuid
from collections.abc import Iterable

from control_tower.data.loader import DATA_DIR, KIT_DIR
from control_tower.schemas.action import WRITE_TOOLS, Action, Rehearsal, ToolResult


def _enterprise_module():
    if str(KIT_DIR) not in sys.path:
        sys.path.insert(0, str(KIT_DIR))
    return importlib.import_module("enterprise")


class Twin:
    def __init__(self, data_dir: str | None = None) -> None:
        mod = _enterprise_module()
        self._tool_error = mod.ToolError
        self._ent = mod.Enterprise(str(data_dir or DATA_DIR))
        self._lock = threading.RLock()  # parallel events share one Twin: serialise access to the Enterprise object

    def rehearse(self, actions: Iterable[Action]) -> list[Rehearsal]:
        """Run the actions in order in a brand-new world. A failing step is reported; later steps still run."""
        key = f"rehearsal-{uuid.uuid4().hex}"
        results: list[Rehearsal] = []
        with self._lock:
            for a in actions:
                try:
                    self._ent.call(key, a.tool, a.args)
                    results.append(Rehearsal(ok=True))
                except self._tool_error as e:
                    results.append(Rehearsal(ok=False, error=str(e)))
        return results

    def execute(self, key: str, tool: str, args: dict) -> ToolResult:
        """One call in the world named `key` (used by the dry-run executor; the server has its own worlds)."""
        with self._lock:
            try:
                return ToolResult(ok=True, response=self._ent.call(key, tool, args))
            except self._tool_error as e:
                return ToolResult(ok=False, error=str(e))

    def state(self, key: str):
        return self._ent.state(key)


def check_invariants(
    actions: list[Action],
    *,
    allowed_po_ids: set[str],
    allowed_co_ids: set[str],
    real_incident: bool = True,
) -> list[str]:
    """Policy invariants independent of the planners. Returns human-readable violations (empty = ok)."""
    problems: list[str] = []
    writes = [a for a in actions if a.tool in WRITE_TOOLS]
    if real_incident and len({a.tool for a in writes}) < 3:
        problems.append(f"fewer than 3 kinds of write action ({sorted({a.tool for a in writes})}) - rule 9")
    notified = [a.args["dealer_id"] for a in actions if a.tool == "dealer.notify"]
    if len(notified) != len(set(notified)):
        problems.append("a dealer is notified more than once - rule 4")
    moved = [a.args["production_order_id"] for a in actions if a.tool in {"mes.reschedule", "mes.transfer"}]
    if len(moved) != len(set(moved)):
        problems.append("a production order is moved more than once")
    extra_po = set(moved) - allowed_po_ids
    if extra_po:
        problems.append(f"moves unaffected production orders: {sorted(extra_po)[:3]} - rule 10")
    listed = {c for a in actions if a.tool == "dealer.notify" for c in a.args["customer_order_ids"]}
    if listed - allowed_co_ids:
        problems.append(
            f"notifies customer orders that are not affected: {sorted(listed - allowed_co_ids)[:3]} - rule 4"
        )
    loaned = [a.args["customer_order_id"] for a in actions if a.tool == "crm.assign_loaner"]
    if len(loaned) != len(set(loaned)):
        problems.append("a customer order receives more than one loaner")
    if set(loaned) - allowed_co_ids:
        problems.append("a loaner is assigned to an unaffected customer order - rule 5")
    return problems
