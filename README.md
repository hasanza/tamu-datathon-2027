# Wacky Wheels Control Tower

Event-driven multi-agent operations control tower for the **Hack the Highway** datathon (Hitachi Digital Services).
One coordinator and three specialist agents read messy operational events, traverse a knowledge graph of the company,
rehearse every corrective action on a digital twin, and execute it through MCP tools against the mock enterprise server.

| Folder | What |
|---|---|
| `hack_the_highway/` | **Given by the organizers, never modified**: data tables, policy handbook, events, mock enterprise server, brief |
| `src/control_tower/` | Our pipeline: data loader, knowledge graph, understanding, agents, twin, MCP server, schemas |
| `api/` | FastAPI backend for the UI (traces, actions, graph, KPIs, live SSE stream) |
| `ui/` | React control-tower UI |
| `eval/` | Oracle, replay grader, paraphrase robustness bench |
| `docs/` | `SPEC.md` (what), `PLAN.md` (how), `WORKPLAN.md` (who/when), `ONBOARDING.md` (how we work), `BRAND.md`, `CONCEPTS.md`, `contracts.md` |
| `traces/examples/` | Hand-written example traces the UI is built against |

## Run the pipeline

```bash
# 1. a fresh enterprise server (the world restarts empty each time it starts)
uv run python hack_the_highway/enterprise_server.py --data hack_the_highway/data \
  --events hack_the_highway/data/events.json --out runs/dev --port 8000 --overwrite
# 2. all 15 events (needs GEMINI_API_KEY in .env, or replay from the cache as below)
uv run python -m control_tower.run --all --out runs/dev
# 3. grade the server's log on a fresh copy of the world against an independent oracle
uv run python eval/replay_grader.py runs/dev/action_log.jsonl --traces traces/dev
```

No server and no API key: replay the whole run from the committed LLM cache, with the in-process twin as the enterprise:

```bash
LLM_CACHE_DIR=cache/snapshot LLM_REPLAY_ONLY=1 uv run python -m control_tower.run --all --dry-run --out runs/dev
```

Real traces of the current pipeline are in `traces/snapshot/`.

## Setup

```bash
uv sync
uv run python hack_the_highway/enterprise_server.py --data hack_the_highway/data --events hack_the_highway/data/events.json --out runs/dev --port 8000 --overwrite
uv run pytest
```

Models: `gemini-3.5-flash-lite` for extraction, entity tie-break and summaries (about $0.019 per full run) and `gemini-3.8-flash` as the independent auditor (about $0.030). Models used, token totals and cost for the submitted run: see `runs/final/models.json` (written by the pipeline) and the design card.
