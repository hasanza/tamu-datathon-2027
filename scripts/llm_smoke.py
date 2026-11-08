"""Task 0.1 smoke test: one structured call against the configured provider, on a synthetic sentence.

Never uses one of the 15 real events (see .claude/rules/llm.md).
"""

import sys
from datetime import date

from pydantic import BaseModel

from control_tower.llm.adapter import LEDGER, complete_json


class Probe(BaseModel):
    kind: str
    plant_name: str | None
    part_name: str | None
    start: date | None
    end: date | None
    confident: bool


def main() -> None:
    provider = sys.argv[1] if len(sys.argv) > 1 else None
    model = sys.argv[2] if len(sys.argv) > 2 else None
    system = (
        "You extract operational facts from short messages at a car maker. Today is Monday 2027-03-08. "
        "'next <weekday>' means that weekday of next week. Answer only with the JSON object."
    )
    user = (
        "Heads up: the Greensboro line will be down for maintenance from next Tuesday through "
        "next Wednesday; brake kits for it are unaffected."
    )
    out, call = complete_json(Probe, system, user, "extract", provider=provider, model=model)
    print(out.model_dump_json(indent=2))
    print(f"{call.provider}/{call.model}: {call.input_tokens} in, {call.output_tokens} out, ${call.cost_usd}")
    print("ledger total $", LEDGER.total_cost_usd)


if __name__ == "__main__":
    main()
