# Contracts (frozen by CORE; changes only at a sync, logged below)

Source of truth: `src/control_tower/schemas/` (Pydantic v2). JSON Schema exports for the UI: `docs/schemas/*.schema.json`
(regenerate with `uv run python scripts/export_schemas.py`). Fixtures: `traces/examples/E-12.json` (supplier delay, done),
`traces/examples/E-05.json` (noise), `traces/examples/E-02.json` (unconfirmed → escalated). `tests/unit/test_contracts.py` keeps them valid.

## Objects

| Object | Purpose | Produced by | Consumed by |
|---|---|---|---|
| `IncidentSpec` | One incident inside one event: category, confidence, resolved ids, ISO dates, raw mentions, resolution steps, ambiguities, reason | LLM extraction + resolver (coordinator) | specialists, UI "Incidents" table, auditor |
| `Action` | One tool call with agent, args, justification, path node ids, rehearsal result, execution result; `.writes` property | specialists (plan), twin (rehearsal), executor (result) | UI actions table, grader, action log |
| `GraphPath` | Nodes (typed, optional `group`/`count` for collapsed sets) + edges (`from`/`to`/`type`) | graph traversals | UI graph view, design card |
| `AgentRun` / `AgentStep` | Per-agent timeline; step kinds `llm, graph, plan, rehearse, audit, execute, gate, note` | all agents | UI timeline, SSE stream |
| `WorldDiff` | What changed: moved POs, notified dealers, loaners, held lots, stopped VINs, contacted customers | coordinator after execution | UI audit tab, grader |
| `Counterfactual` | Business impact numbers | coordinator | UI blast-radius panel |
| `LLMUsage` | Every model call with tokens and cost | adapter | KPI header, README citation |
| `Trace` | Everything above for one event + `status`, `summary`, `decision_reason` | coordinator → `traces/<run>/<event_id>.json` | API, UI, judges |

## Rules of the road
- Event ids are `E-01`…`E-15`; incident ids are `<event_id>#<n>` starting at 1.
- Dates are ISO `YYYY-MM-DD`, always working days inside 2027-02-22..2027-04-02; timestamps are ISO without timezone.
- `status`: `queued` → `processing` → one of `done` (acted), `escalated` (escalate only), `noise` (nothing), `failed` (runtime error, also escalated).
- A `noise` or `escalated` trace has no write actions. A `done` trace has ≥3 distinct write tools and every write action has `rehearsal.ok == true`.
- Collapsed graph nodes use ids `grp:<kind>:<incident_id>` and carry `group` + `count`; the UI renders them as expandable.
- SSE event types (`GET /api/stream`): `event_received`, `agent_step`, `action`, `event_done`; payloads are the matching objects above plus `event_id`.
- FastAPI endpoints: `GET /api/events`, `GET /api/traces/{event_id}`, `GET /api/actions`, `GET /api/graph/{event_id}`, `GET /api/kpis`, `POST /api/run?event_id=&all=`, `GET /api/stream`.

## Changelog
- 2026-11-07 v0.1.0 — initial contracts (task 0.3).
