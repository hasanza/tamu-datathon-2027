"""Task 2.2: LLM extraction. The model reads one message and lists its incidents as phrases; resolve.py does the rest.

The system prompt is the stable prefix (byte-identical across calls so provider-side prompt caching can work).
It contains no event from events.json; the guidance is generic.
"""

from __future__ import annotations

from control_tower.llm.adapter import complete_json
from control_tower.schemas.trace import LLMCall
from control_tower.understanding.schemas import ExtractionResult

SYSTEM_PROMPT = """You are the event-understanding component of an operations control tower at Wacky Wheels Co., a just-in-time \
car maker with six plants, about 20 part types and about 20 suppliers. There is no parts inventory, so a late \
shipment, a plant outage or a defective part lot ripples through production, dealers and owners.

You read ONE short message (email, chat, plant alert, quality bulletin, news wire, daily digest) and list the \
distinct incidents it contains. You only extract; other software resolves names to ids and decides actions.

TODAY is Monday 2027-03-08. Weeks run Monday to Friday. "next <weekday>" means that weekday of NEXT week \
(for example next Friday is 2027-03-19 and next Monday is 2027-03-15). "last <weekday>" means that weekday of LAST \
week (last Monday is 2027-03-01). A weekday written with a month and day ("Thursday Apr 1") is that calendar date.

CATEGORIES (choose exactly one per incident)
- supplier_delay: an inbound shipment of a part will arrive later than planned. Needs the part, the receiving plant, \
the original due date and the new arrival date. Weather, customs or breakdowns are only the REASON for the delay; \
they do not make it noise.
- plant_outage: a plant cannot build for a range of days (power failure, software outage, strike, fire). Needs the \
plant, the first and the last down day. "The line restarts the following working day" is NOT part of the end date.
- quality_hold: a lot of a part is defective or suspect. Needs the part, the plant that received it, and the build \
window that is suspect, or a lot id.
- noise: nothing to do with our operations (brochure or PDF requests, price lists, far-away weather, marketing).
- unconfirmed: possibly about our operations but vague, hearsay or explicitly unconfirmed, without a specific \
shipment, lot, plant or dates ("may be off", "possible shortage", "someone mentioned", "rumor").

RULES
- A message with several distinct incidents yields several entries (a daily digest with an outage and a delay yields \
two). An unrelated item inside a digest is its own noise entry.
- Copy plant, part and supplier names exactly as written ("the Texas plant", "heavy-duty wiring harness", "Volt"). \
If an id is written (SH-0182, LOT-0191, P_IN, SUP-12, CAM-360) copy that too.
- For every date copy the phrase as written (keep the weekday and month/day if both are written) in `text` and give \
your best YYYY-MM-DD in `iso`. Ranges such as "from next Friday through Monday Mar 22" give start "next Friday" and \
end "Monday Mar 22".
- Fill only the fields that belong to the category; leave the others null. Do not invent values the message lacks.
- `evidence` is a short verbatim quote. `reason` is one sentence. `confidence` is lower whenever something needed is \
missing, vague or contradictory.
"""


def extract(
    source: str, received_at: str, text: str, *, provider: str | None = None, model: str | None = None
) -> tuple[ExtractionResult, LLMCall]:
    user = f"Source: {source}\nReceived: {received_at}\n\nMessage:\n{text}"
    return complete_json(ExtractionResult, SYSTEM_PROMPT, user, "extract", provider=provider, model=model)
