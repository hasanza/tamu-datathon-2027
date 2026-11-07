"""Task 4.2: business-friendly summary and decision reason for every event (the 'reasoning module').

The model rewrites a factual draft; it may not add facts. The deterministic draft stays as the fallback and as the
source of every number, so the explanation can never be more confident than the data."""

from __future__ import annotations

from pydantic import BaseModel, Field

from control_tower.llm.adapter import LLMError, complete_json
from control_tower.schemas.trace import LLMCall

SYSTEM = (
    "You write the audit-ready explanation of what a supply-chain control tower did with one operational message, for an "
    "operations manager. You get the original message, the final status, a factual draft summary and the draft reason. "
    "Rewrite them clearly and concisely. Use ONLY facts and numbers present in the input; never add, round differently "
    "or infer anything. Mention handbook rule numbers when explaining why it acted or did not act. No markdown, no lists.\n"
    "- summary: 2 to 4 sentences: what happened, what was done, with the key numbers.\n"
    "- decision_reason: 1 to 3 sentences: why it acted, or why it deliberately did not (noise: no write tools, rule 7; "
    "unconfirmed or unclear: escalate with no operational change, rule 8; real incident: rules that drove the actions)."
)


class Explanation(BaseModel):
    summary: str = Field(min_length=20)
    decision_reason: str = Field(min_length=20)


def explain(
    source: str,
    text: str,
    status: str,
    draft_summary: str,
    draft_reason: str,
    calls: list[LLMCall],
    *,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str, str]:
    user = (
        f"Source: {source}\nStatus: {status}\n\nORIGINAL MESSAGE:\n{text}\n\nDRAFT SUMMARY:\n{draft_summary}\n\n"
        f"DRAFT REASON:\n{draft_reason}"
    )
    try:
        out, call = complete_json(Explanation, SYSTEM, user, "summarize", provider=provider, model=model)
    except LLMError:
        return draft_summary, draft_reason
    calls.append(call)
    return out.summary.strip(), out.decision_reason.strip()
