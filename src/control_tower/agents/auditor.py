"""Task 4.1: the independent audit channel. A second model reads the ORIGINAL message, the understanding that was derived
from it, and a digest of the plan, and checks both against the handbook. The planner is deterministic code; this channel
exists to catch what code cannot: a misread message (wrong plant, wrong part) or a plan that violates the rules' intent.

Only a concern marked `blocking` stops execution (the plan is escalated instead). `note` concerns are recorded in the
trace. The auditor never proposes actions and never edits the plan.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from control_tower.data.loader import KIT_DIR, World
from control_tower.llm.adapter import LLMError, complete_json
from control_tower.schemas.trace import LLMCall


def _rules() -> str:
    text = (KIT_DIR / "data" / "policy_handbook.md").read_text()
    return text[text.index("## Rules") : text.index("## Tools")].strip()


SYSTEM = (
    "You are an independent auditor for an operations control tower at a car maker. Another system read ONE message, "
    "interpreted it as incidents, and planned corrective actions. You see the original message, the interpretation, and "
    "a digest of the plan. Decide whether the interpretation faithfully matches the message and whether the plan "
    "follows the policy rules below.\n\n" + _rules() + "\n\nGUIDANCE\n"
    "- Today is Monday 2027-03-08. 'next <weekday>' means that weekday of NEXT week; 'last <weekday>' of LAST week. "
    "Calendar: last week Mon 03-01 Tue 03-02 Wed 03-03 Thu 03-04 Fri 03-05; this week Mon 03-08 Tue 03-09 Wed 03-10 "
    "Thu 03-11 Fri 03-12; next week Mon 03-15 Tue 03-16 Wed 03-17 Thu 03-18 Fri 03-19; the week after Mon 03-22 Tue 03-23 "
    "Wed 03-24 Thu 03-25 Fri 03-26; then Mon 03-29 Tue 03-30 Wed 03-31 Thu 04-01 Fri 04-02. Compare every date in the "
    "interpretation with the message using this calendar; a date that does not match what the message says is blocking.\n"
    "- Check the interpretation against the message: right plant, part, supplier, shipment or lot, and dates. A nickname "
    "or abbreviation resolved to an entity is fine if it is clearly that entity.\n"
    "- Which exact day an order lands on is a scheduling policy choice. Do NOT flag a landing date or plant unless "
    "capacity or the plant-builds-model rule is broken or an unaffected order is moved.\n"
    "- Mark a concern `blocking` only when acting would be wrong: a misread message, an unaffected record touched, a "
    "missing mandatory action, or a rule violation. Anything else is a `note`. If everything is consistent, agree with no "
    "concerns. Never invent problems."
)


class AuditConcern(BaseModel):
    rule: str = Field(description="Rule number or 'interpretation'")
    issue: str
    severity: Literal["blocking", "note"]


class AuditVerdict(BaseModel):
    agree: bool
    concerns: list[AuditConcern] = Field(default_factory=list)
    summary: str = Field(description="One sentence")


def plan_digest(world: World, plans: list[Any], care: list[Any], escalations: list[str]) -> str:
    """Compact, factual description of the plan: counts and the key ids, never the full action list."""
    lines: list[str] = []
    for p in plans:
        s = p.spec
        head = f"INCIDENT {s.incident_id}: {s.category} (confidence {s.confidence:.2f}), plant {s.plant_id}"
        if s.category == "supplier_delay":
            head += f", part {s.part_id}, supplier {s.supplier_id}, shipment {s.shipment_id}, due {s.orig_eta}, now {s.new_eta}"
        elif s.category == "plant_outage":
            head += f", down {s.outage_start} to {s.outage_end} inclusive"
        else:
            lot = world.lots[s.lot_id]
            head += f", part {lot.part_id}, supplier {lot.supplier_id}, lot {lot.lot_id} built {lot.first_build_date}..{lot.last_build_date}"
        lines.append(head)
        if p.moves:
            moves = "; ".join(
                f"{m.po.id} {m.po.model} {m.po.build_date:%m-%d}->{m.kind} {m.to_plant} {m.to_date:%m-%d}"
                for m in p.moves[:14]
            )
            lines.append(
                f"  moved {len(p.moves)} production orders ({sum(m.kind == 'transfer' for m in p.moves)} transfers): {moves}"
                + (" ..." if len(p.moves) > 14 else "")
            )
        if s.category == "quality_hold":
            lines.append(
                f"  hold lot {s.lot_id}; stop sale of {p.stopped} unsold vehicles at {p.unsold_dealers} dealers; contact {p.owners} owners of sold vehicles"
            )
    if care:
        notices = [a for a in care if a.tool == "dealer.notify"]
        loaners = [a for a in care if a.tool == "crm.assign_loaner"]
        cos = {c for a in notices for c in a.args["customer_order_ids"]}
        dealers = {a.args["dealer_id"] for a in notices}
        entitled = [
            world.customer_orders[c]
            for c in cos
            if world.customers[world.customer_orders[c].customer_id].tier in {"Platinum", "Gold"}
        ]
        short = {}
        for c in entitled:
            short[c.dealer_id] = short.get(c.dealer_id, 0) + 1
        pools_short = {d: (n, world.loaner_pool[d]) for d, n in short.items() if n > world.loaner_pool[d]}
        lines.append(
            f"CARE: {len(cos)} affected customer orders at {len(dealers)} dealers; {len(notices)} dealer notices (one per dealer: {len(notices) == len(dealers)}); "
            f"{len(entitled)} Platinum/Gold entitled; {len(loaners)} loaners assigned; dealers where entitled customers exceed the pool (entitled, pool): {pools_short or 'none'}"
        )
    from collections import Counter

    kinds = Counter(a.tool for a in [*(x for p in plans for x in p.actions), *care])
    if kinds:
        lines.append("ACTION KINDS PLANNED: " + ", ".join(f"{k} x{v}" for k, v in sorted(kinds.items())))
    if escalations:
        lines.append("ESCALATED (not acted on): " + " | ".join(e[:240] for e in escalations))
    return "\n".join(lines)


def audit(
    source: str, text: str, digest: str, calls: list[LLMCall], *, provider: str | None = None, model: str | None = None
) -> AuditVerdict | None:
    user = f"Source: {source}\n\nORIGINAL MESSAGE:\n{text}\n\nINTERPRETATION AND PLAN:\n{digest}"
    try:
        verdict, call = complete_json(AuditVerdict, SYSTEM, user, "audit", provider=provider, model=model)
    except LLMError:
        return None
    calls.append(call)
    return verdict
