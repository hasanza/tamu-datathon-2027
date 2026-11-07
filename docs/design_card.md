# Wacky Wheels Control Tower — design card

*Hack the Highway · event-driven multi-agent operations control tower. Numbers below come from the final clean run
(`runs/final/`, `traces/final/`, tag `final-run-1`) and the replay grader.*

## 1. What it does
Reads 15 free-text events, decides what each one is, finds everything it touches in a knowledge graph of the company,
plans the corrective actions the policy handbook prescribes, **rehearses the plan on a digital twin**, then executes it
through MCP tools against the local enterprise server. Every event gets a trace: classification, extracted incidents,
graph paths, agent timeline, rehearsal, executed actions, world diff, summary and the reason it acted or did not.

**Principle: the LLM decides what happened; code decides what to do; a twin proves it works; then we act.**

## 2. Architecture
```
event ─▶ Coordinator ──▶ Supply Chain Planner ─┐
         (understand,     Dealer & Customer Care ├─▶ plan ─▶ twin rehearsal ─▶ audit ─▶ MCP ─▶ enterprise server
          gate, split)    Quality ───────────────┘             (zero failed)    (2nd LLM)          └▶ action_log.jsonl
                              ▲ typed knowledge graph (networkx): 12 node types, ~27k edges
```
| Agent | Job | Must not |
|---|---|---|
| Coordinator | triage, split compound messages, resolve entities and dates, gate on confidence, own the shared world state, rehearse, audit, execute, summarise | compute impact |
| Supply Chain Planner | supplier-delay / plant-outage impact → earliest feasible slot → reschedule or transfer | touch dealers or customers |
| Dealer & Customer Care | one notice per dealer, loaners by priority within the pool, owner contact | move orders |
| Quality | match the lot, split sold from in-stock, hold lot and stop sale | notify customers directly |

## 3. LLM vs code
| Step | Who |
|---|---|
| Category, incident splitting, entity mentions, confidence, ambiguities | **LLM** (structured output, schema-validated) |
| Name → id (aliases, names, fuzzy), relative dates from 2027-03-08, snapping to real ETAs and lot windows | code |
| Graph traversal, affected sets, slot planning, loaner priority, vehicle split | code, no LLM imports |
| Rehearsal, invariants, failed-call handling | code (organizers' own `Enterprise` class as the twin) |
| Independent pre-commit audit, summaries, escalation wording | **LLM**, a different model from the extractor |

Handbook rules 1–10 are implemented in code, not prompted. The LLM never chooses an id, a date or an action argument.

## 4. Guardrails
- **Twin first:** no write call reaches the server unless the whole plan rehearsed cleanly on an in-process copy of the world, and the live world still matches the baseline the plan was computed from.
- **Data snapping:** dates must land on a real shipment ETA or lot window; a mismatch lowers confidence rather than being silently fixed. Below the 0.7 gate the event escalates.
- **Noise** → zero write calls with a stated reason. **Unconfirmed** → exactly one `escalate`, zero writes.
- **Invariants:** one notify per dealer, nothing outside the impact set, ≥3 action kinds for a real incident, no loaner call when a pool is empty.
- **Auditor:** a second model reads the original message, the interpretation and a plan digest; only a `blocking` concern stops execution (the event escalates instead), `note` concerns go to the trace.
- **Runtime failure:** captured, never retried blindly, event marked failed and escalated.

## 5. Policy decisions on ambiguous points (one `Policy` object, committed with the run)
Affected orders claim slots in (original build date, PO id) order; a transferred order may land on the earliest free slot from today (literal reading of rule 3; E-09 has 2 and E-11 has 3 transfers, all landing Mar 8); transfer ties go to the lower plant id; loaners are assigned per entitled customer order within each dealer's pool.

## 6. Evaluation (final run)
- **15/15 events clean** on a fresh organizers' server: 10 acted, 3 noise, 2 escalated; **797 tool calls, 0 failed**; the independent replay grader (replays the log on a fresh twin and diffs against an oracle written from the rules) agrees on all 15; the auditor raised 0 blocking disagreements. The whole run took 87 s with live LLM calls.
- **Paraphrase robustness:** 90 rewrites (15 events × 6 styles — typos, formal email, disclaimer footer, nicknames, phone shorthand, digest with an unrelated item): **88/90 (98%)** for `gemini-3.8-flash`, **89/90 (99%)** for `gemini-3.5-flash-lite`; the misses are over-escalations on nickname-heavy rewrites (entities and dates right, but flagged for a human). See `eval/reports/paraphrase_bench.md`.
- **Efficiency:** 40 LLM calls for all 15 events, **$0.0498** per full run; none per action (a quality hold is up to 188 calls made by code).
- **Models cited** (`runs/final/models.json`):

  | Model | Role | Calls | Tokens in / out | Cost |
  |---|---|---|---|---|
  | `gemini-3.5-flash-lite` (Google) | extraction, entity tie-break, summaries | 30 | 16,715 / 4,981 | $0.0175 |
  | `gemini-3.8-flash` (Google) | independent auditor | 10 | 13,426 / 5,947 | $0.0324 |

- **Reproducible without a key:** `LLM_CACHE_DIR=cache/final LLM_REPLAY_ONLY=1 uv run python -m control_tower.run --all --dry-run` regenerates the identical action log from the committed cache.

## 7. Explainability and the UI
Control-tower UI over the trace files: live event feed with category and confidence, graph path per event (grouped nodes for large sets), agent timeline, actions table with rehearsal and result per call, audit trail of what changed, escalation inbox and KPIs. A FastAPI layer serves traces, the action log and a live server-sent-events stream of a running pipeline.

## 8. Known limits and next steps
- Slot ordering and the transfer-day reading are policy choices the brief leaves open; both are one config line and the grader shows the effect.
- Names that match no alias and no table row lower confidence and escalate rather than guess; on heavy-nickname rewrites that sometimes over-escalates (1–2 of 90 in the bench), which is the safe direction.
- Next: a local model for offline extraction, a wider paraphrase bench, per-customer loaner caps behind a flag.
