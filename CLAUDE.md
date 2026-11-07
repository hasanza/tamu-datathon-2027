# Wacky Wheels Control Tower — project memory

Hackathon project (24h, two people: **CORE** = Hasan, **GLASS** = teammate). Your identity and owned paths come from
`CLAUDE.local.md` on this machine; the ownership table is `.claude/rules/ownership.md`. Read `docs/ONBOARDING.md` once.

## What we are building
A coordinator + 3 specialist agents (Supply Chain Planner, Dealer & Customer Care, Quality) that read 15 free-text events,
classify them, traverse a knowledge graph of the company, plan the corrective actions the policy handbook prescribes,
**rehearse the plan on an in-process twin** (`hack_the_highway/enterprise.py`), then execute through MCP tools against the
local enterprise server, writing a trace per event. Score is 50% replay of `action_log.jsonl`: wrong or extra actions cost.

## Laws
1. `hack_the_highway/data/policy_handbook.md` is the law. Rules 1–10 are implemented in code, not prompted into an LLM.
2. Never hard-code answers to the 15 events. Everything derives from the event text and the tables.
3. Never edit anything under `hack_the_highway/`. A test checks the file hashes.
4. The planner (`src/control_tower/agents`, `graph`, `world`) is deterministic and has **no LLM imports**.
   The LLM lives only in `src/control_tower/understanding` (extraction), the auditor and the summaries.
5. No write tool call is sent to the server unless the twin rehearsal passed.
6. Contracts in `src/control_tower/schemas/` and `docs/contracts.md` change only by CORE, at a sync.

## Where things are
- Spec `docs/SPEC.md` · plan `docs/PLAN.md` · tasks `docs/WORKPLAN.md` · UI tokens `docs/BRAND.md` · contracts `docs/contracts.md`
- Example traces `traces/examples/*.json` · run outputs `runs/<name>/` · traces `traces/<run>/`
- Handoff requests: `docs/handoff/core.md` (asks to CORE), `docs/handoff/glass.md` (asks to GLASS)

## Commands
```bash
uv sync                                   # env
uv run pytest                             # all tests (unit tests need no LLM, no server)
uv run ruff check . && uv run ruff format .
uv run python hack_the_highway/enterprise_server.py --data hack_the_highway/data --events hack_the_highway/data/events.json --out runs/dev --port 8000 --overwrite
uv run python -m control_tower.run --all --out runs/dev            # after task 3.1
uv run python eval/replay_grader.py runs/dev/action_log.jsonl      # after task 3.3
cd ui && npm run dev                      # UI on :5173 ; API: uv run uvicorn api.app:app --port 8001
```

## Conventions
Branch per WORKPLAN task `core/<id>-<slug>` / `glass/<id>-<slug>`; commits `[CORE 1.3] feat: ...`; PR to main, squash at sync.
Python 3.12, ruff, type hints, Pydantic v2 models for every cross-boundary object. Dates are `datetime.date`; today is 2027-03-08.
Tests under `tests/unit` must run offline in < 10 s.
