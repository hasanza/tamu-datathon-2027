# Ownership (binding for both assistants)

Your person's code name is in `CLAUDE.local.md`. Edit only paths owned by that person. For anything else, append a
request to `docs/handoff/<other>.md` (format in `docs/ONBOARDING.md` §3) and stop.

| Owner | Paths |
|---|---|
| CORE | `src/control_tower/**` except `src/control_tower/mcp/`, `eval/oracle.py`, `eval/replay_grader.py`, `eval/paraphrase_bench.py`, `tests/**`, `CLAUDE.md`, `.claude/**`, `docs/SPEC.md`, `docs/PLAN.md`, `docs/contracts.md`, `pyproject.toml` |
| GLASS | `ui/**`, `api/**`, `src/control_tower/mcp/**`, `eval/reports/**`, `docs/BRAND.md`, `docs/design_card.md`, `docs/server-notes.md`, `README.md`, `media/**` |
| shared, sync only | `.mcp.json`, `traces/examples/**`, `docs/WORKPLAN.md`, `docs/ONBOARDING.md`, `.gitignore` |
| nobody | `hack_the_highway/**` (organizers' kit; a test checks hashes), `.env` |
