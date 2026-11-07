"""What the LLM + resolver produce for one incident inside one event."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["supplier_delay", "plant_outage", "quality_hold", "noise", "unconfirmed"]
EventCategory = Literal["supplier_delay", "plant_outage", "quality_hold", "noise", "unconfirmed", "compound"]
ResolutionMethod = Literal["exact", "alias", "name", "fuzzy", "llm", "data_snap", "unresolved"]
EntityType = Literal["plant", "part", "supplier", "shipment", "lot", "model", "dealer", "date"]


class ResolutionStep(BaseModel):
    """One mention in the text and how it became an id (or did not)."""

    mention: str
    entity_type: EntityType
    candidates: list[str] = Field(default_factory=list)
    chosen: str | None = None
    method: ResolutionMethod
    note: str | None = None


class Ambiguity(BaseModel):
    field: str
    issue: str
    options: list[str] = Field(default_factory=list)
    blocking: bool = False


class IncidentSpec(BaseModel):
    """A single incident; a compound event yields several. Ids are resolved, dates are ISO working days."""

    incident_id: str = Field(description="<event_id>#<n>, e.g. E-01#1")
    event_id: str
    category: Category
    confidence: float = Field(ge=0, le=1)

    plant_id: str | None = None
    part_id: str | None = None
    supplier_id: str | None = None
    shipment_id: str | None = None
    lot_id: str | None = None

    orig_eta: date | None = None
    new_eta: date | None = None
    outage_start: date | None = None
    outage_end: date | None = None
    build_window_start: date | None = None
    build_window_end: date | None = None

    raw_mentions: dict[str, str] = Field(default_factory=dict, description="field -> text as written")
    resolution_steps: list[ResolutionStep] = Field(default_factory=list)
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    reason: str = Field(description="One sentence: why this category / why actionable or not")
