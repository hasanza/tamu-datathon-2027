# Ownership (binding for both assistants)

Your person's code name is in `CLAUDE.local.md`. Edit only paths owned by that person. For anything else, append a
request to `docs/handoff/<other>.md` (format in `docs/ONBOARDING.md` §3) and stop.

| Owner | Paths |
|---|---|
| CORE | `src/control_tower/**` except `src/control_tower/mcp/` (so `trace.py`, `run.py`, `llm/`, `schemas/` are CORE's), `eval/oracle.py`, `eval/replay_grader.py`, `eval/paraphrase_bench.py`, `tests/**` except `tests/glass/`, `scripts/**`, `CLAUDE.md`, `.claude/**`, `docs/SPEC.md`, `docs/PLAN.md`, `docs/contracts.md`, `pyproject.toml` (GLASS may add dependencies via a handoff line) |
| GLASS | `ui/**`, `api/**`, `src/control_tower/mcp/**`, `tests/glass/**` (tests for mcp/ and api/), `eval/reports/**`, `docs/BRAND.md`, `docs/design_card.md`, `docs/server-notes.md`, `README.md`, `media/**` |
| shared, sync only | `.mcp.json`, `traces/examples/**`, `docs/WORKPLAN.md`, `docs/ONBOARDING.md`, `.gitignore` |
| nobody | `hack_the_highway/**` (organizers' kit; a test checks hashes), `.env` |

Precedence: this file wins over any other table (WORKPLAN mirrors it). Python tests for GLASS code live in `tests/glass/`; `uv run pytest` runs both trees.
