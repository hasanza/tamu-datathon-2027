"""The policy choices for the handbook's ambiguities (docs/SPEC.md §7). One object, committed with the final run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Policy:
    # A1: order in which affected POs claim scarce slots. "build_date_id" = (original build date, PO id).
    claim_order: Literal["build_date_id"] = "build_date_id"
    # A2: earliest day a TRANSFERRED order may land. "disruption_end" (default) = never earlier than the same-plant
    # restart day: valid under either reading of the handbook and never builds before the parts/plant are back.
    # "today" = the most literal reading ("on any day with a free slot"), which can land a Mar 30 build on Mar 8.
    transfer_min_day: Literal["today", "disruption_end"] = "disruption_end"
    # A3: tie-break among transfer plants on the same day = plant id ascending.
    # A7: True = at most one loaner per customer within one event; False = one per entitled customer order.
    one_loaner_per_customer: bool = False


DEFAULT_POLICY = Policy()
