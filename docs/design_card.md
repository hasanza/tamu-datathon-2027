# Wacky Wheels Control Tower: design card (v2)

*Hack the Highway · event-driven multi-agent operations control tower.*
**Status: DRAFT for v2.** Architecture, guardrails and limits are written from `docs/PLAN_V2.md` §2, §4, §5 and are re-checked against the code at the v2 final run.
Every number is a `TODO(v2 final run)` until that run exists. The v1 baseline (tag `final-run-2`, branch `main`) is kept in §6 for comparison.

## 1. What it does
Reads 15 free-text operational events, decides what each one is, finds everything it touches in a knowledge graph of the company, plans the corrective actions
the policy handbook prescribes, **rehearses the plan on a digital twin**, then executes it through an **MCP client** against the local enterprise server.
Every event gets a trace: the understanding, the graph paths, every agent turn, tool call and hand-off, the rehearsal, the executed actions, the world diff and the reason it acted or did not.

**Agents reason and orchestrate; tools compute; the twin proves; MCP executes.**

## 2. Architecture
```
event ─▶ COORDINATOR (LLM agent, hub) ──delegate──▶ SUPPLY CHAIN PLANNER      (LLM agent)
         understand · resolve · gate     ──────────▶ DEALER NETWORK            (LLM agent)
         delegate · validate · execute   ──────────▶ CUSTOMER CARE & QUALITY  (LLM agent)
         explain · escalate to a human         each agent calls plain-code tools (graph, planners, composers)
              │
              └─▶ validators (handbook as code) ─▶ twin rehearsal ─▶ auditor (2nd model) ─▶ MCP client ─▶ enterprise server
```
Hub and spoke: specialists never call each other; every hand-off goes through the coordinator, is validated and is recorded.
Each specialist runs once per incident for incident work and once per event for event-wide work, so a compound event yields one `dealer.notify` per dealer and one shared loaner pool.

| Agent | Owns (enterprise tools) | Graph traversal it performs |
|---|---|---|
| Coordinator | `escalate` | entity and date resolution against the tables |
| Supply Chain Planner | `mes.get_schedule` (read), `mes.reschedule`, `mes.transfer` | Shipment/Plant → Production order; slot reasoning |
| Dealer Network | `dealer.notify`, `dealer.stop_sale` | Production order → Customer order → Dealer; Vehicle → Dealer |
| Customer Care & Quality | `quality.hold_lot`, `crm.loaner_availability` (read), `crm.assign_loaner`, `crm.notify_customer` | Lot → Vehicle → Owner; Customer order → Customer |

## 3. LLM versus code
| Step | Who |
|---|---|
| Reading the event, deciding the category, splitting a compound message, gating, choosing what to delegate, explaining | **LLM agents** (a bounded reason-act loop over structured JSON; each turn is recorded with its reasoning) |
| Name → id (aliases, tables, fuzzy, closed-set tie-break), relative dates from 2027-03-08, snapping to real ETAs and lot windows | code (tools) |
| Graph traversal, affected sets, slot planning, loaner ranking, notice and stop-sale composition | code (tools) |
| Handbook rules 1–10 as **validators**, twin rehearsal, failed-call handling, execution order | code |
| Independent pre-commit audit | **LLM**, a second model in a separate context |

The agents choose which tool to call and why; the numbers that change the world (ids, dates, quantities) come from tools and are checked by validators. There is no cache: every LLM response is live.

## 4. Guardrails
- **Validators V1–V8** recompute the expected plan from the resolved incident through the graph: affected set exact, earliest feasible slots, exactly one notice per dealer with exactly its orders, loaners in priority order and never beyond the pool, quality hold and stop-sale exactly the affected vehicles, nothing outside the affected set, no write tool for noise or unconfirmed events. V7 (three action kinds) is a warning, not a blocker.
- **Correction rounds:** a failed validator sends the plan back to the specialist as a correction task; after two failed rounds that incident is escalated with the findings. There is no silent fallback to a plan written by code.
- **Escalation to a human** (one `escalate` per incident, saying what would make it actionable) for: an unconfirmed report; an unresolved id or date, or confidence below 0.7; a "noise" item that names a real record; a plan that still fails after two rounds; a failed twin rehearsal or a blocking auditor concern; a failed write; a server that is not fresh. A confirmed incident is never escalated because of a nickname or an odd date phrase.
- **Twin first:** nothing is sent unless the whole event rehearsed cleanly on an in-process copy of the world, then passed the auditor.
- **MCP execution is phased over the whole event** (moves, notices, loaner reads and loaners, holds, stop-sales, owner contacts), so a partial failure is safe. A server rejection is `failed`; an MCP timeout or exception is `unknown` and stops the event. Neither is retried: dependent writes are marked `skipped`, exactly one `escalate` lists done, failed and skipped, and the summary and counterfactual come from successful calls only. A failed read aborts before any write.
- **Sandbox:** custom events and follow-ups run on the twin only; nothing reaches the real server or the action log.

## 5. Explainability and the UI
The **Orchestration** tab shows four swimlanes with every Thought, Tool call (badged MCP, twin, graph or code), Message between agents and Decision, live while a run is in progress, with turns, tool calls, LLM calls, cost and correction rounds per event. Alongside: graph path per event, actions with rehearsal, transport and result, an audit trail, an escalation inbox with "add details and re-run", and a Sequential or Parallel run toggle.

## 6. Evaluation
Filled in from the v2 final run (`TODO(v2 final run)` marks every figure):
- **Replay and oracle:** three full sequential runs on fresh servers produce identical action logs; independent grader TODO/15; auditor bench TODO; parallel run grader TODO/15.
- **Paraphrase robustness** (inputs regenerated live): TODO/90.
- **Escalation tests:** one per circumstance plus a must-not-escalate test on nickname-heavy rewrites: TODO.
- **Efficiency:** TODO LLM calls and TODO USD per full run; TODO minutes sequential, TODO minutes parallel.
- **Models cited** (`runs/final/models.json`, `agents.toml`): TODO, one row per agent and for the auditor (calls, tokens in and out, cost).
- **v1 baseline for comparison** (tag `final-run-2`, deterministic specialists): 15/15 clean, 797 tool calls, 0 failed, 40 LLM calls, $0.0498, about 90 s; paraphrase bench 88/90 and 89/90.

## 7. What we would improve
- **Agent reliability:** the agents run on Flash-class models chosen per agent in `agents.toml`. Validators and correction rounds contain mistakes, but a stronger model for the coordinator, few-shot tool-use examples and per-agent evaluation would cut correction rounds and cost.
- **Cost and latency:** a full run is many LLM turns and takes minutes; parallel mode helps because events are independent worlds, but a shared tool-result cache across events (never of model output) and batching reads would help more.
- **Latent cases our data never triggers:** an order that cannot be placed at any plant gets no dealer notice, and a confirmed incident with zero affected orders adds one escalation. Both should become explicit, tested paths.
- **Resolution upstream of the validators:** a wrong id from entity resolution passes the validators by construction; the auditor is the only second look. A second independent resolution pass for high-impact incidents (a whole plant or a lot of hundreds of vehicles) would close this.
- **Human in the loop:** escalations are advisory today; approving, editing and re-running with the operator's details already works in the sandbox, but a real approval path to the live systems needs authentication and an audit trail.
- **Offline mode:** a local model for the understanding step so the tower runs with no network.
