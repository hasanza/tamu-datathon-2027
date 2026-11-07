"""The policy choices for the handbook's ambiguities (docs/SPEC.md §7). One object, committed with the final run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Policy:
    # A1: order in which affected POs claim scarce slots. "build_date_id" = (original build date, PO id).
    claim_order: Literal["build_date_id"] = "build_date_id"
    # A2: earliest day a TRANSFERRED order may land. "today" (default) = the literal reading of handbook rule 3
    # ("on any day with a free slot", earliest feasible slot); an independent second opinion rated it ~80% likely.
    # "disruption_end" = never earlier than the same-plant restart day (safer for parts, but later than the literal rule).
    transfer_min_day: Literal["today", "disruption_end"] = "today"
    # A3: tie-break among transfer plants on the same day = plant id ascending.
    # A7: True = at most one loaner per customer within one event; False = one per entitled customer order.
    one_loaner_per_customer: bool = False


DEFAULT_POLICY = Policy()
