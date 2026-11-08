"""One tool call: planned, rehearsed, executed."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Tool = Literal[
    "mes.get_schedule",
    "mes.reschedule",
    "mes.transfer",
    "dealer.notify",
    "dealer.stop_sale",
    "crm.loaner_availability",
    "crm.assign_loaner",
    "crm.notify_customer",
    "quality.hold_lot",
    "escalate",
]
Agent = Literal[
    "coordinator",
    "supply_chain",
    "dealer_care",
    "quality",
    "supply_chain_planner",
    "dealer_network",
    "customer_care_quality",
]
Transport = Literal["mcp/stdio", "twin", "in-process"]
WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "mes.reschedule",
        "mes.transfer",
        "dealer.notify",
        "dealer.stop_sale",
        "crm.assign_loaner",
        "crm.notify_customer",
        "quality.hold_lot",
    }
)


class Rehearsal(BaseModel):
    ok: bool
    error: str | None = None


class ToolResult(BaseModel):
    ok: bool
    error: str | None = None
    response: dict[str, Any] | None = None


class Action(BaseModel):
    seq: int
    incident_id: str | None = Field(default=None, description="None for event-level actions such as escalate")
    agent: Agent
    tool: Tool
    args: dict[str, Any]
    justification: str = Field(description="Which handbook rule and which affected record(s)")
    path_ids: list[str] = Field(default_factory=list, description="Graph node ids on the justifying path")
    rehearsal: Rehearsal | None = None
    result: ToolResult | None = None
    transport: Transport | None = Field(default=None, description="How the call reached the enterprise (v0.2.0)")

    @property
    def writes(self) -> bool:
        return self.tool in WRITE_TOOLS
