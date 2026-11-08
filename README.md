# Wacky Wheels Control Tower

An agentic operations control tower for the Hack the Highway datathon (Hitachi track).
Team: Hasan Raza and Muhammad Ibrahime. Model: Google **gemini-3.8-flash** for the four agents and the auditor.

Operational messages arrive as free text: a late shipment, a plant outage, a quality bulletin, a rumor, plain noise.
A **Coordinator Agent** reads each one, resolves it against a knowledge graph of the company, and hands the incidents to
three specialists, the **Supply Chain Agent**, the **Dealer Agent** and the **Customer & Quality Agent**. Each specialist
calls plain-code tools to compute exact arguments, the coordinator validates the plan against the policy handbook, checks
it on an in-process copy of the enterprise, has a second model audit it, and only then executes it through an **MCP client**
against the enterprise server. Every event ends with a summary of what was done or not done and why, a graph path,
the agents' full reasoning trace and an audit trail. Unclear reports are escalated to a person.

The one-page design card is `docs/design_card.pdf` (source `docs/design_card.md`). The ontology is `docs/ontology.png`
(`docs/ontology.mmd`).

## What is where

| Path | What it is |
|---|---|
| `hack_the_highway/` | The organizers' kit (data, handbook, events, enterprise server), untouched; a test checks its hashes |
| `src/control_tower/` | The pipeline: data loader, knowledge graph, understanding, the four agents and their tools, validators, MCP client, schemas |
| `api/`, `ui/` | The control tower: FastAPI backend and the React front end |
| `eval/` | Replay grader, oracle, identity runs, paraphrase and auditor benches |
| `traces/<run>/` | One JSON trace per event (summary, reasons, graph path, every agent step and tool call, audit) |
| `runs/<run>/` | `action_log.jsonl` and `models.json` (model calls, tokens, cost) of a run |
| `docs/` | Design card, ontology, contracts, plans, Q&A notes |

## Run it

```bash
uv sync                                  # Python 3.12 environment
cp .env.example .env                     # add GEMINI_API_KEY
uv run pytest                            # offline tests, no key needed

# full run of the 15 events against a fresh enterprise server (starts the server itself)
uv run python -m control_tower.live --mode server              # add --parallel 3 to handle three events at once
uv run python eval/replay_grader.py runs/live/action_log.jsonl --traces traces/live

# the control tower (API on :8001, UI on http://localhost:5173)
scripts/dev.sh
```

In the UI, press **Run feed** to watch the 15 events arrive and be handled live, or type your own event into
**Try your own event**: it runs on a private copy of the enterprise server through the same agents and MCP client, so the
scored action log is never touched. A short guided tutorial starts on the first visit.

## How the work is split

The model does what needs judgment: reading messy wording, deciding the category, spotting noise and rumor, choosing what
to delegate, reacting to a failed validation, explaining the outcome. Code does what must be exact: name to id, relative
dates from today (8 March 2027), graph traversal, affected sets, earliest feasible slots, loaner priority, the text of
every notice. Eight validators recompute the expected outcome from the graph; a failed check goes back to the specialist
for at most two correction rounds, then the incident is escalated. Nothing is written before the validators, the
pre-flight check and the auditor all pass. A rejected call is never retried: dependent writes are skipped and one
escalation lists what was done, what failed and what was skipped. No answer is hard-coded and nothing is cached: every
run calls the model live.

## Evaluation

The submitted run on a fresh server scores 15 of 15 on the replay grader: 879 tool calls over MCP, 0 failed calls,
235 model calls, 0.92 USD, 6.5 minutes with three events in parallel. A cold audit by a different model family recomputed all 15 events from the CSVs with zero deviations. On 90
paraphrased events (typos, formal email, nicknames, phone shorthand, digests) the coordinator understood 88, and the two
misses escalated rather than acted. See the design card for the full list.
