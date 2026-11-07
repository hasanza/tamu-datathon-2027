"""Closed-set entity tie-break. When the alias tables cannot resolve a mention ("Alamo City", "multimedia processor"),
ask the model to choose ONE entity from our own list, or none. It can never invent an id: the answer is checked against
the list. Used only as a fallback, logged in the trace, and penalised in the confidence."""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, Field

from control_tower.data.loader import World
from control_tower.llm.adapter import LLMError, complete_json
from control_tower.schemas.trace import LLMCall

SYSTEM = (
    "You match a name written in an operational message at a car maker to exactly one entry of a closed list, or to "
    "none. Choose an entry only if the name clearly and unambiguously refers to it (a nickname, abbreviation, synonym "
    "or description of it). If it could refer to several entries, or to none, answer null. Never guess."
)


class Pick(BaseModel):
    choice: str | None = Field(description="The id of the matching entry, or null")
    confidence: float = Field(ge=0, le=1)
    why: str = Field(description="One short sentence")


def make_tiebreak(
    world: World, calls: list[LLMCall], *, provider: str | None = None, model: str | None = None
) -> Callable[[str, str, str], tuple[str | None, float, str]]:
    catalogue = {
        "plant": {p.plant_id: f"{p.name}, {p.city}" for p in world.plants.values()},
        "part": {p.part_id: f"{p.name} ({p.category})" for p in world.parts.values()},
        "supplier": {s.supplier_id: f"{s.name}, {s.city}" for s in world.suppliers.values()},
    }

    def tiebreak(etype: str, mention: str, context: str) -> tuple[str | None, float, str]:
        entries = "\n".join(f"- {k}: {v}" for k, v in catalogue[etype].items())
        user = f"Message:\n{context}\n\nName to match ({etype}): {mention!r}\n\nList of {etype}s:\n{entries}"
        try:
            out, call = complete_json(Pick, SYSTEM, user, "resolve", provider=provider, model=model)
        except LLMError:
            return None, 0.0, "model unavailable"
        calls.append(call)
        if out.choice not in catalogue[etype]:
            return None, 0.0, out.why
        return out.choice, out.confidence, out.why

    return tiebreak
