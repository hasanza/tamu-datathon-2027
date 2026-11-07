"""What the LLM is asked to return. It copies phrases as written; code does the resolving (resolve.py)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RawCategory = Literal["supplier_delay", "plant_outage", "quality_hold", "noise", "unconfirmed"]


class DateMention(BaseModel):
    text: str = Field(description="The date phrase exactly as written in the message, e.g. 'next Friday' or 'Mar 22'")
    iso: str | None = Field(
        default=None,
        description="Your best YYYY-MM-DD for that phrase using the stated today and week convention, or null",
    )


class RawIncident(BaseModel):
    category: RawCategory
    evidence: str = Field(description="Short verbatim quote from the message that this incident is based on")
    plant: str | None = Field(default=None, description="Plant as written (nickname, city, state or id)")
    part: str | None = Field(default=None, description="Part as written (nickname or id)")
    supplier: str | None = Field(default=None, description="Supplier as written (name, nickname or id)")
    shipment_id: str | None = Field(default=None, description="Shipment id such as SH-0182 if written")
    lot_id: str | None = Field(default=None, description="Lot id such as LOT-0191 if written")
    original_eta: DateMention | None = Field(default=None, description="supplier_delay: when the shipment was due")
    new_eta: DateMention | None = Field(default=None, description="supplier_delay: the new arrival date")
    outage_start: DateMention | None = Field(default=None, description="plant_outage: first day the plant is down")
    outage_end: DateMention | None = Field(default=None, description="plant_outage: last day the plant is down")
    build_window_start: DateMention | None = Field(default=None, description="quality_hold: first suspect build day")
    build_window_end: DateMention | None = Field(default=None, description="quality_hold: last suspect build day")
    reason: str = Field(description="One sentence: why you chose this category")
    confidence: float = Field(ge=0, le=1, description="How sure you are this category and these facts are right")


class ExtractionResult(BaseModel):
    incidents: list[RawIncident] = Field(
        description="One entry per distinct incident. A digest with several items yields several entries."
    )
