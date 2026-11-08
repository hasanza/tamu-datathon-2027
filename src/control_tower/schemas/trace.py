"""The per-event trace: the single artifact the UI, the grader and the judges read."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from control_tower.schemas.action import Action
from control_tower.schemas.incident import EventCategory, IncidentSpec

NodeType = Literal[
    "Supplier",
    "Part",
    "Model",
    "Plant",
    "Shipment",
    "ProductionOrder",
    "CustomerOrder",
    "Customer",
    "Dealer",
    "Lot",
    "Vehicle",
    "Day",
    "Event",
]
EdgeType = Literal[
    "SUPPLIES",
    "OF_PART",
    "TO_PLANT",
    "FROM",
    "USES_PART",
    "BUILDS_MODEL",
    "AT_PLANT",
    "OF_MODEL",
    "ON_DAY",
    "FULFILLED_BY",
    "SOLD_BY",
    "FOR",
    "BUILT_BY",
    "AT_DEALER",
    "OWNED_BY",
    "MENTIONS",
]
StepKind = Literal[
    "llm", "graph", "plan", "rehearse", "audit", "execute", "gate", "note", "thought", "tool", "message", "decision"
]
Transport = Literal["mcp/stdio", "twin", "in-process"]
AgentId = Literal[
    "coordinator",
    "supply_chain",
    "dealer_care",
    "quality",
    "supply_chain_planner",
    "dealer_network",
    "customer_care_quality",
]
Status = Literal["queued", "processing", "done", "escalated", "noise", "failed"]


class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str
    group: str | None = Field(
        default=None, description="Set when the node stands for a collapsed set, e.g. '110 vehicles'"
    )
    count: int | None = None


class GraphEdge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    from_: str = Field(alias="from")
    to: str
    type: EdgeType


class GraphPath(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class AgentStep(BaseModel):
    t: datetime
    kind: StepKind
    text: str
    data: dict[str, Any] | None = None
    # v0.2.0 (all optional): agent turns, tool calls and hand-offs
    turn: int | None = None
    tool: str | None = None
    args: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    to_agent: str | None = None
    from_agent: str | None = None
    transport: Transport | None = None
    model: str | None = None
    cost_usd: float | None = None
    # v0.2.1: stage grouping for the UI (specialists: delegated task; coordinator: phase; message: delegated task)
    task: str | None = None


class AgentRun(BaseModel):
    agent: AgentId
    started: datetime
    ended: datetime | None = None
    model: str | None = None
    llm_calls: int = 0
    cost_usd: float = 0.0
    steps: list[AgentStep] = Field(default_factory=list)


class Classification(BaseModel):
    category: EventCategory
    confidence: float = Field(ge=0, le=1)
    reason: str


class MovedPO(BaseModel):
    production_order_id: str
    kind: Literal["reschedule", "transfer"]
    from_plant: str
    from_date: date
    to_plant: str
    to_date: date


class NotifiedDealer(BaseModel):
    dealer_id: str
    customer_order_ids: list[str]


class WorldDiff(BaseModel):
    moved_pos: list[MovedPO] = Field(default_factory=list)
    notified_dealers: list[NotifiedDealer] = Field(default_factory=list)
    loaners: list[str] = Field(default_factory=list, description="customer_order_ids that received a loaner")
    held_lots: list[str] = Field(default_factory=list)
    stopped_vins: list[str] = Field(default_factory=list)
    contacted_customers: list[str] = Field(default_factory=list)


class Counterfactual(BaseModel):
    customers_affected: int = 0
    avg_slip_days: float | None = None
    loaners_entitled: int = 0
    loaners_assigned: int = 0
    vehicles_pulled: int = 0
    owners_contacted: int = 0


class LLMCall(BaseModel):
    provider: str
    model: str
    purpose: Literal["extract", "audit", "summarize", "resolve", "paraphrase", "agent_turn"]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    cached: bool = False
    attempts: int = 1  # provider calls behind this record (2 when the schema retry fired)


class LLMUsage(BaseModel):
    calls: list[LLMCall] = Field(default_factory=list)
    total_cost_usd: float = 0.0


class Escalation(BaseModel):
    incident_id: str
    reason: str


class Orchestration(BaseModel):
    mode: Literal["sequential", "parallel"] = "sequential"
    correction_rounds: int = 0
    escalations: list[Escalation] = Field(default_factory=list)
    mcp_transport: str | None = None


class Trace(BaseModel):
    pipeline_version: str = "0.2.1"
    event_id: str
    received_at: datetime
    source: str
    text: str
    status: Status
    classification: Classification
    incidents: list[IncidentSpec] = Field(default_factory=list)
    paths: dict[str, list[GraphPath]] = Field(default_factory=dict, description="incident_id -> paths")
    agents: list[AgentRun] = Field(default_factory=list)
    orchestration: Orchestration | None = None
    actions: list[Action] = Field(default_factory=list)
    world_diff: WorldDiff = Field(default_factory=WorldDiff)
    counterfactual: Counterfactual | None = None
    llm: LLMUsage = Field(default_factory=LLMUsage)
    summary: str
    decision_reason: str
