# PLAN v2 — agentic control tower (branch `v2`)

Ground truth: `docs/RUBRIC.md` (the brief) and `hack_the_highway/data/policy_handbook.md`. Where this plan and the brief differ, the brief wins.
v1 (tag `final-run-2`, branch `main`) is the deterministic pipeline; v2 keeps its code as **tools and validators** and puts four real agents on top.

## 1. Why v2
The brief scores "a coordinator and three specialist agents with clear responsibilities", "how the LLM and plain code share the work",
"tool execution (MCP-style)", "graceful handling of failed calls", and "graph path and reasoning trace per event". v1 has the plain code,
the twin and the graph, but its specialists are functions, execution does not go through an MCP client, five traces have no graph path, and a
failed call mid-plan is not handled. v2 fixes exactly those, with no caching anywhere (every response is live).

## 2. Architecture: agents reason and orchestrate; tools compute; the twin proves; MCP executes
```
event text ──▶ COORDINATOR (LLM agent, hub) ──delegate──▶ SUPPLY CHAIN PLANNER (LLM agent)  tools: graph, mes.* via MCP, slot planner
                 │ understands, resolves, gates,       ──▶ DEALER NETWORK (LLM agent)         tools: graph, notice/stop-sale composer
                 │ validates (handbook rules as code),  ──▶ CUSTOMER CARE & QUALITY (LLM agent) tools: graph, lot match, crm.* via MCP, loaner ranking
                 │ rehearses on twin, requests audit (2nd model), executes via MCP client, handles failed calls, explains
                 └──▶ escalate (human-in-the-loop)
```
Hub-and-spoke: specialists never call each other; every hand-off passes through the coordinator, is validated, and is recorded.
Each specialist runs **once per event** (not once per incident) with the union of what the event's incidents produced, so a compound
event yields exactly one `dealer.notify` per dealer and one shared loaner pool (handbook rule 4, brief TC5).

### 2.1 Agents and ownership (the brief's example split, by enterprise-tool family)
| Agent id | Display name | Owns enterprise tools | Graph traversal it performs |
|---|---|---|---|
| `coordinator` | Coordinator | `escalate` | entity/date resolution against the tables (`resolve_*` tools) |
| `supply_chain_planner` | Supply Chain Planner | `mes.get_schedule` (read), `mes.reschedule`, `mes.transfer` | Shipment → Part → Model (BOM) → ProductionOrder; Plant → ProductionOrder; slot reasoning |
| `dealer_network` | Dealer Network | `dealer.notify`, `dealer.stop_sale` | ProductionOrder → CustomerOrder → Dealer; Vehicle → Dealer |
| `customer_care_quality` | Customer Care & Quality | `quality.hold_lot`, `crm.loaner_availability` (read), `crm.assign_loaner`, `crm.notify_customer` | Lot → ProductionOrder → Vehicle → Owner; CustomerOrder → Customer |

### 2.2 Per-event flow (coordinator)
1. **Understand** (LLM): read the text; propose incidents: category, verbatim evidence, entity mentions as written, date phrases, confidence, reason.
   This is the brief's "use an LLM to understand each event". The coordinator's first action is `register_incidents(...)`.
2. **Resolve** (tools): names → ids via aliases/tables (+ closed-set tie-break), date phrases → ISO dates from today 2027-03-08 using the calendar,
   snapping to real shipment ETAs / lot windows. Output: `IncidentSpec[]` with ambiguities and confidence.
3. **Gate** (LLM decides, rules constrain): noise → `drop_noise(reason)`; unconfirmed/unclear or blocking ambiguity or confidence < 0.7 → `escalate`;
   a "noise" item that names a shipment/lot or a plant with dates → `escalate` (never silently dropped). Confirmed incidents continue.
4. **Delegate** (LLM): **per incident**, in text order: `delegate(supply_chain_planner, incident)` for a delay/outage, or
   `delegate(customer_care_quality, incident, task="quality_hold")` for a quality hold (hold + vehicle split + owner contacts).
   **Once per event, after all incidents**: `delegate(dealer_network, union)` (notices for all affected orders, stop-sales for all in-stock affected
   vehicles) and `delegate(customer_care_quality, union, task="loaners")` (pool checks + loaners, one shared pool per dealer).
   The `delegate` tool enforces this: per-incident tasks once per incident, event-wide tasks once per event. Specialists return a typed
   `SpecialistResult {actions, findings, paths, reasoning_summary}`; a second `submit_plan` for the same task **replaces** the first.
5. **Validate** (code): `validate_plan()` runs the handbook rules (§4). Failures go back to the specialist as a correction task; after 2 failed
   rounds the incident is escalated with the findings. No fallback to a code-made plan.
6. **Prove and act**: `execute()` = validators again → twin rehearsal of the full plan → auditor (second model) → MCP client execution in canonical
   order → failed-call handling (§5) → world diff and counterfactual.
7. **Explain**: summary + decision reason (LLM, from a factual draft), per-agent reasoning already in the trace.
   `finish` refuses while any confirmed incident has neither a validated plan nor an escalation (completion check), so the coordinator cannot stop early.

Modes: `--sequential` (default; final run) or `--parallel N` (events are independent: "each event is handled in its own fresh copy of the world").

## 3. Agent runtime (`src/control_tower/agents/runtime.py`)
A bounded reason–act loop over structured JSON (model-agnostic; no native function calling):
```
Turn = {"thought": str (the agent's reasoning for this step, shown to judges),
        "action": {"tool": str, "args": dict} | {"final": <agent-specific result>}}
```
- Each turn is one `complete_json(Turn-schema, system, user)` call. `user` = task brief + compact transcript (tool calls and results so far).
- Limits: coordinator ≤ 24 turns, specialists ≤ 12; schema error → one retry with the error text; limit exceeded → error result → coordinator escalates.
- Tool results are compact (ids, counts, dates). A list longer than 20 items is returned as `{count, sample, handle}`; the full value lives in
  `ctx.store[handle]` and later tools accept the handle in place of the list (opaque result handles). Slot reservations live in one event-wide
  `SlotBoard` in `ctx`; `propose_slots` recomputes and replaces that incident's moves (idempotent). A correction round is a fresh specialist run with its
  own turn budget.
- Every turn is recorded as `AgentStep(kind="thought")` + `AgentStep(kind="tool"|"message"|"decision")` with cost and model.
- Models per agent from `agents.toml` (repo root), env override `CT_MODEL_<AGENT_ID>`; default `gemini/gemini-3.8-flash` for all four and the auditor
  (auditor runs in a separate context). Swappable without code changes; the adapter already supports gemini and anthropic.
- **No cache.** Remove `LLM_CACHE_DIR`, `LLM_REPLAY_ONLY`, `use_cache`, `cache/` directories and every mention in docs/commands.

### 3.1 Tools (`src/control_tower/agents/tools.py`): name, owner, kind, effect
Kinds: `graph` (traversal), `code` (deterministic planner/composer), `mcp-read` (live read via MCP), `control` (coordinator flow).
| Tool | Owner | Kind | Does |
|---|---|---|---|
| `register_incidents(incidents)` | coordinator | control | resolves mentions/dates (existing resolver), returns IncidentSpecs + ambiguities |
| `resolve_entity(type, mention)`, `resolve_date(phrase)` | coordinator | code | retry a single mention / phrase |
| `drop_noise(incident_id, reason)` | coordinator | control | records the reason; no writes |
| `escalate(incident_id, reason, what_would_make_it_actionable)` | coordinator | control | queues exactly one `escalate` call for that incident |
| `delegate(agent, task, payload)` | coordinator | control | runs the specialist loop; returns its `SpecialistResult`; records message steps both ways |
| `validate_plan()` | coordinator | code | handbook validators (§4) over the assembled plan; returns findings per incident |
| `execute()` | coordinator | control | validators → twin → audit → MCP → failed-call handling; refuses if validation fails |
| `finish(summary_hint)` | coordinator | control | ends the loop; triggers summary/reason generation |
| `affected_builds(incident_id)` | supply_chain_planner | graph | impact traversal: POs, already-built, restart day, paths |
| `get_schedule(plant_id, date)` | supply_chain_planner | mcp-read | live free slots |
| `propose_slots(po_ids)` | supply_chain_planner | code | earliest same-plant ≥ restart, else transfer earliest free from today, tie → lower plant id; per-PO reasoning |
| `submit_plan(moves)` | supply_chain_planner | control | final |
| `customer_orders_of(po_ids)` | dealer_network | graph | by dealer: affected customer orders (+ customers, tiers) |
| `compose_notices(by_dealer)` / `compose_stop_sales(vins_by_dealer)` | dealer_network | code | `dealer.notify` / `dealer.stop_sale` actions |
| `submit_plan(actions)` | dealer_network | control | final |
| `match_lot(incident_id)` | customer_care_quality | graph | lot by part+plant+window; candidates if ambiguous |
| `affected_vehicles(lot_id)` | customer_care_quality | graph | in-stock VINs by dealer, owners (customer → VINs), paths |
| `eligible_customers(co_ids)` | customer_care_quality | graph | Platinum/Gold affected orders with tier, promised date, dealer |
| `loaner_availability(dealer_id)` | customer_care_quality | mcp-read | live pool size |
| `rank_and_assign(eligible, pools)` | customer_care_quality | code | handbook rule 5 priority within each pool → `crm.assign_loaner` actions |
| `compose_hold(lot_id)` / `compose_owner_contacts(owners)` | customer_care_quality | code | `quality.hold_lot` / `crm.notify_customer` actions |
| `submit_plan(actions, findings)` | customer_care_quality | control | final |

## 4. Validators (handbook rules as plain code; `src/control_tower/agents/validators.py`)
V1 affected set is exactly the traversal result (rules 1, 2, 6). V2 every affected PO moved once to a feasible, earliest slot (rule 3). V3 exactly one
`dealer.notify` per affected dealer with exactly its affected order ids (rule 4). V4 loaners: eligible tiers only, priority order, never beyond the pool,
no assign on an empty pool (rule 5). V5 quality: the matched lot held; stop-sale exactly the in-stock affected VINs grouped per dealer; one owner contact per
owner of a sold affected vehicle (rule 6). V6 nothing outside the affected set (rule 10). V7 ≥ 3 distinct write kinds per real incident (rule 9).
V8 noise/unconfirmed → zero write tools (`escalate` is not a write tool: `enterprise.py` marks it `writes: False`; rules 7, 8).
V4 also requires every entitled customer to receive a loaner while the pool lasts (expected assignments exactly). V7 (rule 9 says "should")
is a **warning** recorded in the trace, not a blocker: event-wide notices count for every incident whose orders they list. Findings are
structured `{incident_id, rule, expected, got, severity}`; validators recompute expectations from the resolved `IncidentSpec` via the graph, so a
specialist that passed an incomplete list to a tool is caught (what validators cannot catch is a wrong resolution upstream; the auditor covers that).

### 4.1 Escalation: when (and when not)
Escalate (one `escalate` per incident; the reason states what would make it actionable; no further writes for that incident) when:
1. unconfirmed/unclear report (rule 8); 2. a required id/date cannot be resolved, or confidence < 0.7; 3. a "noise" item names a real record;
4. a specialist plan still fails validators after two correction rounds; 5. twin rehearsal fails or the auditor raises a blocking concern;
6. a write fails during execution (escalate the partial completion); 7. the server world is not fresh for the event.
Circumstance 3 does not break rule 7: `escalate` is not a write tool, and the brief says "if a report is not specific or confirmed, escalate";
a brochure that merely mentions a city stays noise (the guard needs a shipment/lot id, or a plant together with dates).
Never escalate a confirmed incident because of a nickname or an odd date phrase: aliases, tables and the closed-set tie-break resolve first.
In a compound event only the unclear part is escalated. Tests: one per circumstance + a must-not-escalate test on nickname-heavy rewrites.

## 5. Execution through MCP and failed calls
- `McpExecutor` (`world/executor.py`): spawns `python -m control_tower.mcp.server` over stdio with the `mcp` SDK `ClientSession`
  (`stdio_client` + `StdioServerParameters`); `list_tools` at start; every enterprise call (reads included) is `session.call_tool("enterprise_act", ...)`
  or the typed read tools. Runs the asyncio loop in a dedicated thread; thread-safe (one lock around calls). Records `transport="mcp/stdio"` on each action.
  The twin sandbox (custom events, dry runs) keeps `TwinExecutor` (`transport="twin"`).
- Reads (`mes.get_schedule`, `crm.loaner_availability`) are free and never penalized (handbook, Tools section). They are the only reads the enterprise exposes (slot and loaner-pool
  state); lot state has no read tool, so a quality-only event has nothing to verify live and the freshness step says so in the trace.
- Execution is **phased over the whole event**, which is what makes partial failure safe: (1) all moves for all incidents; (2) notices recomputed
  from the moves that succeeded; (3) loaner reads, then loaners for the orders whose moves succeeded; (4) holds; (5) stop-sales; (6) owner contacts.
- Failure semantics: a server-side rejection (error in the response) is `failed`; a transport failure (MCP timeout/exception) is `unknown` and
  stops the event. Either way: no retry; dependent writes are marked `skipped` (`Action.skipped = true`, result error `skipped: dependency failed`);
  exactly one `escalate` listing done / failed / skipped; event status `failed`; summary, diff and counterfactual from successful calls only.
  A failed read aborts the event before any write (escalate). The run owns the enterprise server lifecycle (`live.py`); the MCP server is spawned per run.

## 6. Graph paths
- Delay/outage summary paths end `… → CustomerOrder(grp) → Dealer(grp) / Customer(grp)`: add the customers group node (brief: "Dealer / Customer").
- Noise and unconfirmed events get a minimal path: `Event` node → `MENTIONS` → any entity the text scan found (may be none). New node type `Event`,
  new edge type `MENTIONS` (additive). Every trace then has ≥ 1 path.

## 7. Contracts v0.2.0 (additive; `src/control_tower/schemas/trace.py`, `docs/contracts.md`)
- `AgentRun.agent`: accepts the new ids `"coordinator" | "supply_chain_planner" | "dealer_network" | "customer_care_quality"` **and** the v1 ids
  (`supply_chain`, `dealer_care`, `quality`) so every existing trace still validates; v2 emits only the new ids; add `model: str | None`, `llm_calls: int`, `cost_usd: float`.
- `StepKind` += `"thought" | "tool" | "message" | "decision"`. `AgentStep` += `turn: int | None`, `tool: str | None`, `args: dict | None`,
  `result: dict | None` (compact), `to_agent`, `from_agent`, `transport: "mcp/stdio" | "twin" | "in-process" | None`, `model`, `cost_usd`.
- `Action` += `transport`, `skipped: bool = False`, `incident_ids: list[str]` (an event-wide notice lists every incident it serves). `LLMCall.purpose` += `"agent_turn"`. `Trace.pipeline_version = "0.2.0"`;
  `Trace.orchestration = {mode, correction_rounds, escalations: [{incident_id, reason}], mcp_transport}`.
- SSE `agent_step` payload carries the new fields. Fixture: `traces/examples/v2/E-11.json`, `E-03.json`, `E-02.json` (real runs).

## 8. UI (GLASS, `ui/`): "Orchestration" replaces "Agents"
- Four swimlanes (Coordinator, Supply Chain Planner, Dealer Network, Customer Care & Quality), time flowing down; cards: **Thought** (italic, the agent's
  reasoning), **Tool call** (name, compact args, result summary; badges `MCP` / `twin` / `graph`), **Message** (arrow between lanes with task and result
  summary), **Decision** (gate passed, plan validated, correction round, escalated, executed). Live via SSE during a run; expandable details.
- Header strip per event: four agents with turns / tool calls / LLM calls / cost; correction rounds; "escalated" badge.
- Run controls: `Sequential | Parallel` toggle next to Run feed; Dry/Server stays. Custom events now take ~30–40 s: show agent cards streaming meanwhile.
- About page: the §2 diagram and the sentence "agents reason and orchestrate; tools compute; the twin proves; MCP executes".
- Keep: feed newest-first judge section, inbox with follow-ups, graph tab, actions, audit (add transport column).

## 9. Verification before the final run
Three full sequential runs on fresh servers → identical action logs (diff) → grader 15/15 → auditor bench → Codex cold audit of the new traces →
escalation test suite → paraphrase bench (inputs regenerated live) → one parallel run, grader 15/15. Then the final run, tag `v2-final-1`.

## 10. Work streams (all PRs target `v2`; CORE code is written by Sonnet subagents from this spec; Fable plans/reviews; Codex sanity-checks)
- **A (CORE)** contracts v0.2.0 + `agents.toml` + runtime + tool registry + `McpExecutor` + cache removal + unit tests.
- **B (CORE)** tools for the three specialists + coordinator rewrite + validators + correction/escalation + graph path changes + fixture traces.
- **C (CORE)** failed-call handling, parallel mode, escalation test suite, benches, 3-run verification, docs (design card, README, Q&A).
- **D (GLASS)** Orchestration view, header strip, run-mode toggle, About diagram, audit transport column; then video/screenshots after the final run.

## 11. Risks
Accuracy variance (mitigated: tools compute args; validators; three-run identity check). Agent reliability on Flash-class models (tight task briefs,
one-call tools per domain, correction rounds). Cost/latency: ~150–250 LLM calls, $0.5–1.5 and ~8–10 min sequential per run (2–3 min parallel).

## 12. Submission checklist (brief, "Submission Notes")
`runs/final/action_log.jsonl` (15 events) · source code (repo at tag `v2-final-1`) · ontology export (`docs/ontology.mmd`, GraphML via
`scripts/export_graph.py`, PNG `docs/ontology.png`) · a trace per event (`traces/final/E-*.json`) · demo video or screenshots (`media/`) ·
summary + reason per event (in every trace and the UI) · one-page design card with architecture, LLM vs code, guardrails, evaluation **and what we
would improve** (`docs/design_card.pdf`) · model citation (`runs/final/models.json`, README, design card).

## 13. Reviewer notes considered and not adopted
A read-only Codex review suggested cutting the agent loops, the MCP stdio client, the second-model auditor, parallel mode and cache removal as
"not required by the brief". Decision (Hasan, 2026-11-08): the brief is read to the letter — a coordinator and three specialist *agents*, MCP-style
execution, no hard-coding — and every response must be live. The deterministic recovery path the review asked for is the validator layer plus
correction rounds; a silent fallback to a code-made plan was rejected because it would make the agents decorative.
