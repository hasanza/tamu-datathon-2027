"""Tool registry for the agents (docs/PLAN_V2.md §3.1).

A tool is a function ``(ctx, args: ArgsModel) -> dict`` registered with ``@tool(name, owner, kind, description)``.
The args model is read from the type hint of the second parameter and doubles as the validator and the JSON schema
shown to the model. Agents reason; tools compute.
"""

from __future__ import annotations

import dataclasses
import json
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel

from control_tower.data.loader import World
from control_tower.schemas.trace import Transport

ToolKind = Literal["graph", "code", "mcp-read", "control"]
# How each kind of tool reaches its result; recorded on the AgentStep (and on Actions by the executor).
KIND_TRANSPORT: dict[str, Transport] = {
    "graph": "in-process",
    "code": "in-process",
    "control": "in-process",
    "mcp-read": "mcp/stdio",
}


@dataclass
class ToolContext:
    """Everything a tool may touch. `store` holds full results the prompt only sees in summary."""

    world: World
    graph: Any = None
    executor: Any = None
    event_id: str = ""
    store: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    owner: frozenset[str]
    kind: ToolKind
    description: str
    args_model: type[BaseModel]
    fn: Callable[[ToolContext, Any], dict[str, Any]]

    @property
    def args_schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema()

    @property
    def transport(self) -> Transport:
        return KIND_TRANSPORT[self.kind]


REGISTRY: dict[str, ToolSpec] = {}


def tool(name: str, owner: set[str], kind: ToolKind, description: str):
    def deco(fn: Callable[[ToolContext, Any], dict[str, Any]]):
        hints = typing.get_type_hints(fn)
        params = [p for p in hints if p != "return"]
        args_model = hints[params[1]] if len(params) > 1 else None
        if not (isinstance(args_model, type) and issubclass(args_model, BaseModel)):
            raise TypeError(f"tool {name}: second parameter must be annotated with a pydantic model")
        if name in REGISTRY:
            raise ValueError(f"duplicate tool {name}")
        REGISTRY[name] = ToolSpec(name, frozenset(owner), kind, description, args_model, fn)
        return fn

    return deco


def tools_for(agent_id: str) -> list[ToolSpec]:
    return [t for t in REGISTRY.values() if agent_id in t.owner]


def render_tools(specs: list[ToolSpec]) -> str:
    """Text for the system prompt: one block per tool with its kind, purpose and full args JSON schema."""
    return "\n".join(
        f"- {t.name}  [{t.kind}]\n    {t.description}\n    args schema: {compact_json(t.args_schema)}" for t in specs
    )


def jsonable(obj: Any) -> Any:
    """Plain JSON-safe copy (dataclasses, pydantic models, dates, sets)."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, set | frozenset):
        return [jsonable(v) for v in sorted(obj)]
    if isinstance(obj, list | tuple):
        return [jsonable(v) for v in obj]
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def compact(value: Any, store: dict[str, Any], prefix: str, *, limit: int = 20, sample: int = 5) -> Any:
    """Shrink a tool result for the prompt: lists longer than `limit` become
    ``{count, sample, stored_key}`` and the full list goes to ``store[stored_key]``.
    `prefix` must be unique per tool call; the key adds the field path and element index so siblings never collide."""
    if isinstance(value, list):
        if len(value) > limit:
            store[prefix] = value
            return {
                "count": len(value),
                "sample": [compact(v, store, f"{prefix}[{i}]") for i, v in enumerate(value[:sample])],
                "stored_key": prefix,
            }
        return [compact(v, store, f"{prefix}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, dict):
        return {k: compact(v, store, f"{prefix}.{k}") for k, v in value.items()}
    return value


def compact_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), default=str, ensure_ascii=False)


# --- sample tools (stream B adds the real ones) -----------------------------------------------------------------


class EchoArgs(BaseModel):
    text: str


@tool("echo", {"coordinator"}, "code", "Return the given text unchanged (smoke test for the loop).")
def echo(ctx: ToolContext, args: EchoArgs) -> dict[str, Any]:
    return {"text": args.text}


class LookupArgs(BaseModel):
    record_id: str


_TABLES = (
    ("plant", "plants"),
    ("part", "parts"),
    ("supplier", "suppliers"),
    ("dealer", "dealers"),
    ("production_order", "production_orders"),
    ("customer_order", "customer_orders"),
    ("customer", "customers"),
    ("lot", "lots"),
    ("shipment", "shipments"),
    ("vehicle", "vehicles"),
)


@tool(
    "lookup_record",
    {"coordinator", "supply_chain_planner", "dealer_network", "customer_care_quality"},
    "graph",
    "Look up one record by id (plant, part, supplier, dealer, PO, customer order, lot, shipment, VIN) in the tables.",
)
def lookup_record(ctx: ToolContext, args: LookupArgs) -> dict[str, Any]:
    for kind, attr in _TABLES:
        row = getattr(ctx.world, attr).get(args.record_id)
        if row is not None:
            return {"found": True, "type": kind, "record": jsonable(row)}
    return {"found": False, "record_id": args.record_id}
