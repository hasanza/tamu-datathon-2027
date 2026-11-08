# WORKPLAN — two people, 24 hours

Code names (used in every task, commit message, branch and in each person's `CLAUDE.local.md` so the assistants know whose work is whose):

**CORE = you** (Claude Max, Fable; main session + Opus/Sonnet subagents). Owns the pipeline that produces the action log.
**GLASS = teammate** (Claude Pro; Claude Code with Sonnet, limited usage per 5-hour window). Owns the glass: UI, API, MCP wrapper, docs, video.

Ownership is enforced three ways: `.claude/rules/ownership.md` (path → owner, loaded by both), `CODEOWNERS`, and a gitignored
`CLAUDE.local.md` on each machine stating `You are assisting CORE` or `You are assisting GLASS` with the rule
"only edit paths owned by your person; for anything else, write a request in docs/handoff/<to>.md".

## 0. Principles for the split

1. **Split along a frozen interface, not along "backend/frontend".** The contract is three JSON schemas
   (`IncidentSpec`, `Action`, `Trace`) plus the FastAPI endpoints. CORE owns the schemas and freezes them by hour 1.
   GLASS builds the whole UI against example trace files, never against CORE's unfinished code. Integration is a config change.
2. **Sensitivity decides ownership.** Anything that changes `action_log.jsonl` (resolver, planners, coordinator, twin,
   execution) is **Critical** and is CORE's. UI, MCP wrapper, docs, evaluation tooling, video are Medium/Low and are GLASS's.
3. **AI budget is a resource.** GLASS's Pro plan will hit limits during long codegen sessions. So: CORE pre-generates
   skeletons with Max (whole files, typed, compiling) and hands them over; GLASS integrates, styles, tests, and reviews
   with short focused prompts. GLASS keeps a running request list in `docs/handoff/core.md`. GLASS also does the
   human-judgement work that needs little AI: design card, video, README. GLASS has no ChatGPT, so no Codex.
4. **Sync every 2 hours, 5 minutes, demo not status.** Each person shows one thing that runs.
5. **Two branches, merge to `main` at every sync**: `core/*` (CORE) and `glass/*` (GLASS). Contracts live in `src/control_tower/schemas/`
   and `docs/contracts.md`; only CORE edits them, GLASS requests changes in the sync.
6. **Both do the trace audit** (task 4.7): read every event's trace against the handbook rules, and also step through one
   event by hand (server + curl + the twin) so each of you can explain the whole flow to the judges.

### Path ownership (mirror of `.claude/rules/ownership.md`, which wins on any conflict)

| Owner | Paths |
|---|---|
| CORE | `src/control_tower/**` except `mcp/`, `eval/oracle.py`, `eval/replay_grader.py`, `eval/paraphrase_bench.py`, `tests/**` except `tests/glass/`, `scripts/`, `CLAUDE.md`, `.claude/`, `docs/SPEC.md`, `docs/PLAN.md`, `docs/contracts.md`, `pyproject.toml` |
| GLASS | `ui/`, `api/`, `src/control_tower/mcp/`, `tests/glass/`, `eval/reports/`, `docs/BRAND.md`, `docs/design_card.md`, `docs/server-notes.md`, `README.md`, `media/` |
| shared (sync only) | `.mcp.json`, `traces/examples/`, `docs/WORKPLAN.md`, `docs/ONBOARDING.md`, `.gitignore` |
| nobody | `hack_the_highway/**` (organizers' kit, hash-checked by a test), `.env` |

See `ONBOARDING.md` for machine setup, assistant identity, git conventions and definition of done.

## 0.0 Status (updated 2026-11-08, branch `v2`)

**Checkpoint 2026-11-08 (tag `v2-checkpoint-1`; `v2` frozen, all further work on branch `v3`).** v2 is functionally complete and verified live:
four LLM agents (coordinator hub + Supply Chain Planner, Dealer Network, Customer Care & Quality; `agents.toml`), ReAct tool loops,
handbook validators with correct-then-escalate, phased execution through the real MCP client (`mcp/stdio`), no caching, parallel mode
(`--parallel N`, UI toggle), provider retry/backoff with run-level abort, contract 0.2.2 (`AgentStep.task`, `Orchestration.target`,
`provider_failure`). Judge events run on a PRIVATE copy of the organisers' server through the same MCP client (`live.py --custom`;
`runs/custom/sandbox/<id>/`); the in-process twin remains only for the pre-flight rehearsal, `--dry-run` and the grader; no "twin" in
anything judges see. Full live run through the UI: 15/15 grader clean, 766 writes, 0 failed calls, 230 LLM calls, 0 retries, $0.90;
Codex cold audit recomputed all 15 events from the CSVs with zero deviations. UI: Orchestration Flow view (two-row stage nodes, animated,
Detailed timeline toggle), scrollable inbox 1.8:1 with Activity, Scored/Sandbox badges, run-status alerts. Fixtures: `traces/examples/v2/`
(E-01, E-02, E-03, E-05, E-11, C-18 at 0.2.2). Known UX hazard: "Run this event" from the UI starts a fresh scored server with
`--overwrite` and wipes `runs/live` + `traces/live` (a single-event run destroyed the full-run artefacts once) — fix on v3.
Remaining for v3: three-run identity verification (`eval/run_identity.py --k 3`), one live parallel run, final run (tag `v2-final-1`),
merge into `main`; GLASS: README/design-card wording sweep, demo video; GLASS needs his own Gemini key before running live.

**v2 in progress** (`docs/PLAN_V2.md`): four real agents (coordinator + Supply Chain Planner + Dealer Network + Customer Care & Quality) on top of the
v1 code (now tools and validators), execution through a real MCP client, no caching, failed-call handling, graph path for every event, Orchestration UI.
All PRs target `v2`; `main` stays the v1 submission (tag `final-run-2`) until v2 is verified (PLAN_V2 §9).

### v1 status (2026-11-07 night)

CORE has the whole pipeline working end to end: 15/15 events on the live organizers' server, 797 calls, 0 failed, independent grader 15/15 clean
(`eval/replay_grader.py`). Remaining CORE work: auditor + LLM summaries (4.1, 4.2), paraphrase bench (4.4), policy decisions (SPEC §7 A2), UI shell (0.4),
the final run (5.4). GLASS: everything UI/API/docs; real traces are in `traces/snapshot/`.

## 0.1 Standing answers (so nobody has to ask twice)

- **Failed read calls**: the server logs any failing call as `ok:false`, read or write. We treat every failed call as counted
  against efficiency, whatever the grader does. The twin rehearsal validates arguments before any call, so reads never fail either.
- **`.mcp.json` shows "failed"** until task 1.5 lands. Expected.
- **Example traces are fixtures**, not ground truth: `E-12.json` is deliberately truncated (4 of 14 dealers, says so in its summary).
  The UI always treats `trace.actions` as the complete list; real traces replace the fixtures at task 3.2.
- **Final run artifacts** live in `runs/final/` (action log, models.json) and `traces/final/` (traces); both are tracked.

## 1. Frozen contracts (CORE writes by H1)

```
IncidentSpec  {incident_id, event_id, category, confidence, plant_id?, part_id?, supplier_id?, shipment_id?, lot_id?,
               orig_eta?, new_eta?, outage_start?, outage_end?, build_window_start?, build_window_end?,
               raw_mentions{...}, resolution_steps[{mention, candidates[], chosen, method}], ambiguities[], reason}
Action        {seq, incident_id, agent, tool, args, justification, path_ids[], rehearsal:{ok, error?}, result?:{ok, error?, response?}}
GraphPath     {nodes[{id,type,label}], edges[{from,to,type}]}
Trace         {event_id, received_at, source, text, status: queued|processing|done|escalated|noise|failed,
               classification{category, confidence, reason}, incidents[IncidentSpec], paths{incident_id: GraphPath[]},
               agents[{agent, started, ended, steps[{t, kind, text, data?}]}], actions[Action],
               world_diff{moved_pos[], notified_dealers[], loaners[], held_lots[], stopped_vins[], contacted_customers[]},
               counterfactual{customers_affected, avg_slip_days, loaners_entitled, loaners_assigned, vehicles_pulled, owners_contacted},
               llm{calls[{model, purpose, input_tokens, output_tokens, cost_usd}], total_cost_usd},
               summary, decision_reason}

FastAPI       GET  /api/events                 -> events + status per event
              GET  /api/traces/{event_id}      -> Trace
              GET  /api/actions                -> parsed action_log.jsonl (+ ok flag)
              GET  /api/graph/{event_id}       -> merged GraphPath for the event (for the viz)
              GET  /api/kpis                   -> totals: events, actions, failed, escalations, cost, models
              POST /api/run?event_id=&all=     -> starts pipeline in background
              GET  /api/stream                 -> SSE: {type: event_received|agent_step|action|event_done, payload}
```

## 2. Task board

Legend — Sens: **C**ritical (changes the action log) / **H**igh / **M**edium / **L**ow. AI: heavy / light (how much codegen it needs).
Deps use task ids. Hours are elapsed hackathon time.

### Phase 0 — Foundations (H0–H1)

| ID | Owner | Task | Acceptance | Sens | AI | Deps |
|---|---|---|---|---|---|---|
| 0.1 ✅ `core/0.1-llm-adapter` | CORE | LLM access: use the existing **Gemini API key** first (free-tier quota is enough for ~40 calls/run); write the provider-agnostic `llm/adapter.py` (`complete_json(schema, system, user) -> dict + usage`) with Gemini and Anthropic backends; optionally add an Anthropic key (prepaid) later for Haiku 5.5 comparison | one structured JSON response from Gemini, tokens logged | H | light | — |
| 0.2 ✅ `core/0.2-phase0-scaffold` | CORE | `uv` project, deps (`anthropic mcp networkx pydantic fastapi uvicorn sse-starlette pytest ruff python-dotenv rapidfuzz`), `CLAUDE.md`, `.claude/agents` (architect, implementer, reviewer, data-detective, eval-runner), `.claude/skills` (run-events, grade, trace), `.claude/rules`, `.mcp.json` | `uv run pytest` passes an empty test; subagents listed in `/agents` | M | heavy | — |
| 0.3 ✅ `core/0.2-phase0-scaffold` | CORE | Contracts: Pydantic models for §1, JSON-schema export, `docs/contracts.md`, three example traces hand-written (`E-12` delay, `E-05` noise, `E-02` escalation) in `traces/examples/` | GLASS can render all three in the UI | H | heavy | — |
| 0.4 | GLASS | Frontend scaffold: Vite + React + TS + Tailwind v4 + shadcn/ui, theme tokens from `docs/BRAND.md` (Hitachi-inspired red/black/gray, Noto Sans), app shell (top bar, left feed, center tabs, right rail), mock loader reading `traces/examples/*.json` | `npm run dev` shows shell with 3 example events | M | heavy (CORE pre-generates the shell with Max; GLASS wires and styles) | 0.3 |
| 0.5 | GLASS | Run `hack_the_highway/enterprise_server.py` (see ONBOARDING §1); exercise `/events`, `/tools`, `/act` with curl incl. failure cases; write `docs/server-notes.md` | notes cover every tool's error text | L | light | — |

### Phase 1 — Core data + graph + twin / UI skeleton (H1–H5)

| ID | Owner | Task | Acceptance | Sens | AI | Deps |
|---|---|---|---|---|---|---|
| 1.1 ✅ `core/1.1-1.4-graph-planners-twin` | CORE | CSV loader → typed records; calendar helpers (idx↔date, next working day) | unit tests | C | light | 0.2 |
| 1.2 ✅ `core/1.1-1.4-graph-planners-twin` | CORE | Knowledge graph (`networkx.MultiDiGraph`, typed nodes/edges per SPEC FR-2); `export_graphml()`, `export_mermaid_ontology()` | node/edge counts logged; GraphML opens in Gephi/yEd | H | heavy | 1.1 |
| 1.3 ✅ `core/1.1-1.4-graph-planners-twin` | CORE | Traversals returning paths: `impact_supplier_delay(plant, part, d1, d2)`, `impact_outage(plant, d1, d2)`, `impact_lot(part, plant, d1, d2)`, `cos_for_pos`, `vehicles_for_lot` | tests reproduce SPEC §6 magnitudes | C | heavy | 1.2 |
| 1.4 ✅ `core/1.1-1.4-graph-planners-twin` | CORE | Twin: wrap `enterprise.Enterprise`, `rehearse(event_id, actions) -> per-action ok/error`, invariants (≥3 kinds, one notify per dealer, no ids outside impact set) | rehearsal of a hand-written plan passes/fails correctly | C | light | 1.1 |
| 1.5 | GLASS | MCP server (FastMCP, stdio): `enterprise_act(event_id, tool, args)`, `enterprise_get_schedule`, `enterprise_loaner_availability`, `enterprise_list_tools`; register in `.mcp.json`; verify from Claude Code `/mcp` | tool call from Claude Code returns server JSON | M | light | 0.5 |
| 1.6 | GLASS | FastAPI skeleton serving §1 endpoints from files on disk (`traces/`, `runs/*/action_log.jsonl`), SSE endpoint that tails a `events.ndjson` pipe file; CORS for Vite | UI loads real example traces via API | M | heavy | 0.3 |
| 1.7 | GLASS | UI: Event Feed (source icon, category badge, confidence ring, status), Event Summary tab (summary, decision reason, incidents table) | renders 3 examples; keyboard nav | M | heavy | 0.4 |

### Phase 2 — Understanding + planners / graph & timeline views (H5–H10)

| ID | Owner | Task | Acceptance | Sens | AI | Deps |
|---|---|---|---|---|---|---|
| 2.1 ✅ `core/2.1-2.2-understanding` | CORE | Resolver: aliases → names → rapidfuzz → candidates; relative-date rules (anchor Mon 2027-03-08, "next X" = next week's X, "last X" = previous week's X); data snapping (ETA Mondays, lot windows, plant/model compat); confidence formula | tests on all 15 event texts' mentions | C | heavy | 1.2 |
| 2.2 ✅ `core/2.1-2.2-understanding` | CORE | Extraction via `llm/adapter.py` (Gemini Flash-class model; Haiku 5.5 if an Anthropic key exists) structured output → `IncidentSpec[]` with raw mentions + proposed dates; prompt includes alias table + rules summary (cached prefix) (v1 had a text-hash fixture cache; removed in v2, every LLM response is live) | 15/15 categories correct; dates agree with resolver | C | heavy | 0.1, 2.1 |
| 2.3 ✅ planner logic (tests green; wired by 3.1) | CORE | Supply Chain planner: affected POs → earliest feasible slot (SPEC §5, A1/A2 config flags) → reschedule/transfer actions with paths | E-11 yields 6 reschedules + 3 transfers; rehearsal passes | C | heavy | 1.3, 1.4 |
| 2.4 ✅ planner logic (tests green; wired by 3.1) | CORE | Dealer & Care planner: one notify per dealer, loaner priority within pool, templated messages | E-04 assigns exactly pool-limited loaners in priority order | C | heavy | 2.3 |
| 2.5 ✅ planner logic (tests green; wired by 3.1) | CORE | Quality planner: lot match, vehicle split, hold/stop_sale/notify_customer | E-03: 1 + 37 + 150 actions; rehearsal passes | C | light | 1.3 |
| 2.6 ✅ `core/2.1-2.2-understanding` | CORE | Oracle (`eval/oracle.py`): expected action set per incident straight from rules, independent code path from planners where possible | oracle == planner on 10 incidents | H | light | 2.3–2.5 |
| 2.7 | GLASS | Graph Path view: React Flow + ELK layout, typed node styles, collapsed group nodes ("110 vehicles · 37 dealers", expandable), path highlight on hover of an action | 3 example traces render clearly; 260-vehicle case stays readable | M | heavy | 1.7 |
| 2.8 | GLASS | Agents Timeline: swimlanes per agent, steps with kind icons (llm/graph/plan/rehearse/execute), click → detail drawer with raw data | — | M | heavy | 1.7 |
| 2.9 | GLASS | Actions & Audit tabs: actions table (tool, args, rehearsal ✔, result ✔/✖, justification, path link); world-diff before/after cards | — | M | heavy | 1.7 |
| 2.10 | GLASS | Ontology diagram page (Mermaid from `export_mermaid_ontology`, also PNG for submission) + "Download GraphML" | PNG in `docs/ontology.png` | L | light | 1.2 |

### Phase 3 — End to end (H10–H14)

| ID | Owner | Task | Acceptance | Sens | AI | Deps |
|---|---|---|---|---|---|---|
| 3.1 ✅ `core/2.1-2.2-understanding` | CORE | Coordinator: ingest → extract → resolve → gate (noise/unconfirmed/confidence) → dispatch → shared WorldState → rehearse → execute via MCP client → trace writer; emits SSE pipe events | one event runs end-to-end with a real server | C | heavy | 2.2–2.5, 1.5 |
| 3.2 ✅ `core/2.1-2.2-understanding` | CORE | Full 15-event run on a fresh server; inspect `action_log.jsonl`: zero `ok:false`, compound consistent | `grep '"ok": false' == 0` | C | light | 3.1 |
| 3.3 ✅ `core/2.1-2.2-understanding` | CORE | Replay grader: replay log on a fresh twin, diff final state vs oracle; report table | all 15 green or explained | H | light | 2.6, 3.2 |
| 3.4 | GLASS | Wire UI to live API: "Run feed" button → `POST /api/run?all=1`; SSE drives feed animation, agent steps, action rows in real time | live demo of 15 events arriving one by one | M | heavy | 1.6, 3.1 |
| 3.5 | GLASS | Escalation inbox (right rail): escalated events with reason, "what would make this actionable", acknowledge button (UI-only) | — | L | light | 1.7 |
| 3.6 | GLASS | KPI header: events processed, actions, failed calls, escalations, LLM cost, models used | — | L | light | 1.6 |

### Phase 4 — Guardrails, explainability, robustness (H14–H19)

| ID | Owner | Task | Acceptance | Sens | AI | Deps |
|---|---|---|---|---|---|---|
| 4.1 | CORE | LLM auditor (small model via adapter; larger model of the same provider if low confidence): plan summary vs handbook → agree/disagree + reason; disagree ⇒ escalate | no false disagreements on 10 real incidents | H | light | 3.1 |
| 4.2 | CORE | Summaries + decision reasons (LLM, cached); confidence threshold tuning | every trace has summary + reason | H | light | 3.1 |
| 4.3 | CORE | Counterfactual metrics (promised-date slips, loaners entitled/assigned, vehicles pulled, owners contacted) into trace + `/api/kpis` | numbers shown in UI | M | light | 3.1 |
| 4.4 | CORE | Paraphrase bench: the larger model generates ~6 rewordings × 15 events; run extraction + resolver; report category/entity/date accuracy | report in `eval/reports/` | M | light | 2.2 |
| 4.5 | GLASS | Blast-radius & counterfactual panel (Recharts: slips histogram, loaners entitled vs assigned, vehicles sold vs stock) | — | M | heavy | 4.3 |
| 4.6 | GLASS | Polish: loading/empty states, responsive, branding "Wacky Wheels Control Tower" in BRAND.md tokens, favicon, model-citation footer | looks like a product | L | light | all UI |
| 4.7 | both | **Trace audit**: each reads all 15 `traces/*.json` against the handbook rules (category right? ids affected? one notify per dealer? loaner order? nothing extra?) and files issues with event id + rule number; each also walks one event by hand (curl the server, run the twin) | issue list; both can narrate any event | H | none | 3.2 |

### Phase 5 — Submission (H19–H23)

| ID | Owner | Task | Acceptance | Sens | AI | Deps |
|---|---|---|---|---|---|---|
| 5.1 | GLASS | One-page design card (architecture, LLM vs code, guardrails, evaluation, improvements) | PDF | M | light | 4.x |
| 5.2 | GLASS | README: run instructions, model citation (exact model ids used in the final run + provider), token totals and cost, ontology diagram | — | M | light | 5.4 |
| 5.3 | GLASS | Demo video (3–4 min) / screenshots: events arriving, graph path, agents acting, audit trail, escalation | video file | M | none | 3.4, 4.6 |
| 5.4 | CORE | Final clean run: fresh server `--out runs/final --overwrite`, verify log, copy traces, freeze tag | `runs/final/action_log.jsonl` | C | none | all |
| 5.5 | CORE | Review pass: Opus reviewer subagent on resolver/planners/coordinator; fix only Critical findings | — | H | light | 5.4 |
| 5.6 | both | Dry-run of the demo and the "explain your run" conversation with judges | — | — | — | all |

Buffer: H23–H24.

## 3. Hour-by-hour per person

| Hour | CORE (you) | GLASS (teammate) |
|---|---|---|
| 0–1 | 0.1 key · 0.2 scaffold · 0.3 contracts + examples | 0.5 server notes · 0.4 wire the shell CORE generated |
| 1–3 | 1.1 loader · 1.2 graph | 0.4 shell · 1.5 MCP server |
| 3–5 | 1.3 traversals · 1.4 twin | 1.6 FastAPI skeleton · 1.7 feed + summary |
| 5–7 | 2.1 resolver · 2.2 extraction | 2.7 graph view |
| 7–10 | 2.3 supply planner · 2.4 care planner · 2.5 quality · 2.6 oracle | 2.8 timeline · 2.9 actions/audit · 2.10 ontology page |
| 10–12 | 3.1 coordinator | 3.5 inbox · 3.6 KPIs · prep 3.4 |
| 12–14 | 3.2 full run · 3.3 grader | 3.4 live wiring (needs 3.1) |
| 14–17 | 4.1 auditor · 4.2 summaries · 4.3 counterfactuals · 4.7 trace audit (1h) | 4.7 trace audit (1h) · 4.5 counterfactual panel |
| 17–19 | 4.4 paraphrase bench · fixes from 4.7 | 4.6 polish · start 5.1 |
| 19–21 | 5.5 review pass | 5.1 design card · 5.2 README |
| 21–23 | 5.4 final run + package | 5.3 video |
| 23–24 | 5.6 dry run | 5.6 dry run |

## 4. GLASS's AI-budget playbook (Pro plan, no other AI subscription)

- Work in **one focused Claude Code session per task**; the first prompt contains the task's acceptance line, the contract file, and `docs/BRAND.md` if it is UI.
- Keep `docs/handoff/core.md`: when a task needs a big generated file (a new React page, the FastAPI skeleton), write the request there; CORE generates it with Max in minutes and pushes it to `glass/*`.
- Stay on Sonnet (`/model sonnet`); avoid Opus. Use plan mode only for 2.7 (graph view).
- When the 5-hour window is exhausted, switch to no-AI tasks: 0.5, 4.7, 5.1, 5.3, or hand-styling.
- CORE's Max session is the shared heavy-codegen engine for both people; GLASS should never be blocked by quota for more than 15 minutes.

## 5. Sync agenda (every 2 hours, 5 minutes)

1. Each shows one thing running (not a status).
2. Contract change requests → CORE decides, edits schema + examples, GLASS updates types.
3. Merge both branches to `main`; run `uv run pytest` and `npm run build`.
4. Re-assign if anyone is >1 hour behind the table in §3: UI tasks are cut first (4.5, 4.6), never Critical tasks.

## 6. Resolved on 2026-11-07

1. GLASS knows React/TS; CORE still pre-generates the UI shell and big pages with Max to save GLASS's quota and time.
2. GLASS has only Claude Pro → playbook in §4.
3. Both do the trace audit (4.7) and both can present.
4. LLM key: start with the Gemini key via the provider-agnostic adapter; add an Anthropic key only if we want a Haiku 5.5 comparison.
5. Code names CORE / GLASS adopted everywhere.

## Phase 6 — v2 agentic (branch `v2`, spec `docs/PLAN_V2.md`)

| # | Owner | Task | Done when | Depends |
|---|---|---|---|---|
| 6.1 | CORE | Stream A: contracts v0.2.0, `agents.toml`, agent runtime, tool registry, `McpExecutor`, cache removal, tests | `uv run pytest` green; E-11 reaches the server through MCP | — |
| 6.2 | CORE | Stream B: specialist tools, coordinator rewrite, validators, correction/escalation, graph paths (Customer node, Event→MENTIONS), fixtures `traces/examples/v2/` | E-01, E-02, E-03, E-11 run live with 0 correction rounds | 6.1 |
| 6.3 | GLASS | Stream D: Orchestration view (lanes, thought/tool/message/decision cards, live), header strip, Sequential/Parallel toggle, About diagram, audit transport column | renders fixtures and a live run; typecheck+build | 6.1 (contracts) |
| 6.4 | CORE | Stream C: failed-call handling, `--parallel`, escalation test suite, benches, 3-run identity check | PLAN_V2 §9 all green | 6.2 |
| 6.5 | CORE | Final v2 run, tag `v2-final-1`; merge `v2` → `main` | grader 15/15, logs identical across 3 runs | 6.4 |
| 6.6 | GLASS | Design card, README, Q&A notes for v2; video/screenshots | numbers from `runs/final` of v2 | 6.5 |
