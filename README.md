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

## Run

```bash
uv sync
uv run python hack_the_highway/enterprise_server.py --data hack_the_highway/data --events hack_the_highway/data/events.json --out runs/dev --port 8000 --overwrite
uv run pytest
```

Models used, token totals and cost for the submitted run: see `runs/final/models.json` (written by the pipeline) and the design card.
