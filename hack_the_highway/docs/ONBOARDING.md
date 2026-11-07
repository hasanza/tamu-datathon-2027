# ONBOARDING — how we work (read once, both of us)

This is the operating manual for the two of us and for our Claude Code assistants. CORE = Hasan. GLASS = teammate.
Read in this order: `ONBOARDING.md` (this) → `SPEC.md` → `PLAN.md` → `WORKPLAN.md` (your tasks) → `BRAND.md` (GLASS) → `CONCEPTS.md` (when you have a quiet moment).

## 1. Machine setup (15 minutes)

```bash
git clone <repo-url> datathon2027 && cd datathon2027/hack_the_highway
uv sync                       # Python 3.12 env + deps (pyproject pins)
cd ui && npm install && cd .. # GLASS only, after the shell exists
cp .env.example .env          # fill LLM_PROVIDER / GEMINI_API_KEY (CORE only; GLASS leaves it empty)
uv run python enterprise_server.py --data data --events data/events.json --out runs/dev --port 8000 --overwrite
```

Ports: enterprise server 8000 · FastAPI 8001 · Vite 5173. Never commit `.env`, `runs/`, `traces/` (except `traces/examples/`).
Never edit anything under `data/`, `enterprise.py`, `enterprise_server.py`.

## 2. Tell your assistant who you are

Create `hack_the_highway/CLAUDE.local.md` (gitignored, one per machine). GLASS's version:

```markdown
# Local identity
You are assisting **GLASS** on the Hack the Highway project.
- Read docs/ONBOARDING.md, CLAUDE.md, docs/WORKPLAN.md and docs/contracts.md before any work.
- Only edit paths owned by GLASS (see .claude/rules/ownership.md). For anything else, write a request
  in docs/handoff/core.md and stop.
- Default model: sonnet. Keep sessions to one WORKPLAN task. Start each task by restating its acceptance line.
- Follow the git conventions in docs/ONBOARDING.md §4 (branch per task, commit prefix `[GLASS <task-id>]`).
- UI work follows docs/BRAND.md tokens exactly. Never invent colors.
- Never touch data/, enterprise*.py, .env, or the contracts.
```

CORE's version is identical with CORE/GLASS swapped, `docs/handoff/glass.md`, and default model fable.

### First prompt to paste into Claude Code (GLASS, day one)

```
Read docs/ONBOARDING.md, then CLAUDE.md, docs/WORKPLAN.md and docs/contracts.md. Confirm which code name you are
assisting and which paths you own. Then list my tasks for Phase 0 and Phase 1 from WORKPLAN.md with their acceptance
criteria and dependencies, tell me which one to start, and propose the branch name. Do not write any code yet.
```

### First prompt for every later task

```
Task <id> from docs/WORKPLAN.md. Acceptance: "<paste the acceptance cell>". Relevant files: <paths>.
Create branch <prefix>/<id>-<slug> from main, implement only this task, run the checks in ONBOARDING §5,
then show me the diff summary and the commit message before committing.
```

## 3. Ownership and handoffs

- Ownership table: `WORKPLAN.md` §0 and `.claude/rules/ownership.md`. If you need a change in the other person's area,
  append to `docs/handoff/<core|glass>.md`:
  ```
  ## <time> <your code name> → <their code name>  [task <id>]
  Need: <one sentence>  Why: <one sentence>  Blocking: yes/no  Suggested shape: <snippet or path>
  ```
  The other person answers in the same file or at the next sync. Blocking requests get a Slack/WhatsApp ping.
- Contracts (`src/control_tower/schemas/`, `docs/contracts.md`, `traces/examples/`) change only by CORE, only at a sync,
  with a one-line entry in `docs/contracts.md` → "Changelog".

## 4. Git conventions

- **`main` is always runnable.** `uv run pytest -q` and `cd ui && npm run build` must pass before anything merges.
- **One branch per WORKPLAN task** (our "soft milestones"): `core/1.3-traversals`, `glass/2.7-graph-view`.
  Phase-level tags on `main` when a phase closes: `phase-0` … `phase-5`, and `final` after the clean run.
- **Commits**: `[<CODENAME> <task-id>] <type>: <what>`; types `feat|fix|test|docs|chore|ui`. Example:
  `[GLASS 1.7] ui: event feed with category badges and confidence ring`. Body optional; mention a handoff id if relevant.
- **Merging**: open a PR to `main` (even if nobody reviews it; the PR diff is what the Opus reviewer subagent reads).
  Squash-merge at the 2-hour sync. Rebase your branch on `main` before opening the PR; resolve conflicts on your side.
  Never force-push `main`.
- **Small and often**: commit every 30–45 minutes on your branch; push at least at every sync so the other person can pull.
- **Do not commit**: `.env`, `runs/`, `traces/*.json` except `traces/examples/`, `node_modules`, `.venv`, LLM cache files.
- Remote: private GitHub repo under CORE's account, GLASS added as collaborator (`gh repo create --private`, `gh api` invite).

## 5. Definition of done (per task)

1. Acceptance line in WORKPLAN is demonstrably true (say how you checked).
2. `uv run ruff check . && uv run pytest -q` green (CORE); `npm run lint && npm run build` green (GLASS).
3. No edits outside your owned paths. No secrets. No changes to `data/` or the organizers' files.
4. Commit message follows §4; PR opened; WORKPLAN row updated with ✅ and the branch name.
5. If the task produced something the other person consumes (schema, endpoint, component), one line in the handoff file.

## 6. Rhythm

- Sync every 2 hours, 5 minutes, demo not status (WORKPLAN §5). Merge, tag if a phase closed, re-plan if >1h behind.
- Hour 12 is the integration checkpoint: UI on real API on real traces. Everything after is additive.
- Hour 19: feature freeze for anything that touches the action log. Only fixes from the trace audit after that.
- Hour 21: record the demo video from a clean run **before** final polish, so a working video exists whatever happens.

## 7. Things we also plan for

| Topic | Decision |
|---|---|
| Secrets | Only CORE's machine holds `GEMINI_API_KEY`. GLASS runs the UI from `traces/examples/` and later from traces CORE commits to a `traces-final/` folder for the demo. |
| LLM cache | Extractions cached by text hash in `cache/llm/*.json` (gitignored except the final run's cache, committed so the demo can run with `--replay-llm` and no network). |
| Demo machine | CORE's laptop runs server + API + UI; GLASS's laptop is the fallback with the committed cache. Both rehearse 5.6. |
| Determinism | Planner config (A1–A3 in SPEC §7) lives in one `policy.toml`; the final run's config is committed and cited in the design card. |
| Issue tracking | No external tracker. Bugs go as rows at the bottom of `WORKPLAN.md` → "Issues" with owner and task id. |
| Reviews | Opus `reviewer` subagent on every `core/*` PR touching planners/resolver/coordinator; GLASS self-reviews UI PRs with Sonnet. |
| Data integrity | A test asserts the SHA-256 of every file in `data/` matches the originals, so nobody edits the world by accident. |
| Logging | Python `logging` to `runs/<run>/pipeline.log`; the SSE stream is derived from the same events, not a second source. |
| Model citation | The adapter writes `runs/<run>/models.json` (provider, model id, calls, tokens, cost); README and design card quote it. |
| Submission packaging | `make package` → `submission/` with action_log.jsonl, traces/, ontology.png + graph.graphml, design_card.pdf, README, video link, source zip. |
| Fallbacks | If Gemini quota fails live: switch provider by env var or run `--replay-llm`. If the UI breaks: FastAPI serves a static `/report/<event_id>` HTML from the trace. |
| Judges' Q&A | Each person can walk any event end to end (trace audit 4.7). Keep `docs/qa-notes.md` with the five hardest questions and our answers (slot ordering, transfer rule, date convention, LLM vs code, why no failed calls). |
