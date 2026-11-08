# Runbook v2: how to run the control tower

For GLASS to fold into `README.md` (CORE does not edit it). Numbers marked TODO are filled after the final run.

## Prerequisites
`uv sync`, a Gemini key in `.env` (`GEMINI_API_KEY`). There is **no cache and no replay mode**: every LLM response is live, every run
calls the models. The action log is stable because tools compute the arguments and validators check them, not because anything is stored.

## Start a fresh enterprise server, then run
```bash
uv run python hack_the_highway/enterprise_server.py --data hack_the_highway/data \
  --events hack_the_highway/data/events.json --out runs/dev --port 8000 --overwrite
uv run python -m control_tower.run --all --out runs/dev --server http://127.0.0.1:8000          # sequential (default)
uv run python -m control_tower.run --all --out runs/dev --server http://127.0.0.1:8000 --parallel 4
uv run python eval/replay_grader.py runs/dev/action_log.jsonl --traces traces/dev
```
A re-run on a used server aborts safely (the freshness check finds a changed world, escalates, writes nothing): restart the server.

| Flag | Meaning |
|---|---|
| (none) / `--parallel 1` | **Sequential**: events one after another. This is the mode of the final run and what the identity check uses. |
| `--parallel N` (N up to 8) | **Parallel**: N events at once. Each event has its own context and its own world on the enterprise server; the MCP client is serialised by a lock, the twin is locked. Traces are written per event, the summary table is printed in event order, `orchestration.mode` is `parallel`. The per-event action sets are the same as sequential. |
| `--executor mcp` (default) | Writes go through an MCP client (`python -m control_tower.mcp.server` over stdio). |
| `--executor http` | The same server code called in-process, no MCP protocol (tests, comparison). |
| `--dry-run` | The in-process twin plays the enterprise: no server needed. LLM calls are still live. |
| `--event E-03` (repeatable) / `--all` | Which events. |
| `--provider P --model M`, `--audit-model M` | Override the model of every agent / the auditor for this run. |
| `--no-audit`, `--no-explain` | Skip the auditor or the explanation LLM calls (cheaper experiments only). |

## Judge-supplied events
A custom event (UI "Add event" -> `POST /api/custom` -> `python -m control_tower.live --custom <file>`) is handled exactly like a feed event:
the same four agents and the same MCP client, but against a PRIVATE instance of the organisers' server that `live.py` starts for that
one event (`enterprise_server.py --events <file> --out runs/custom/sandbox/<event_id> --port <free> --overwrite`) and stops afterwards.
The organisers' server only accepts event ids it was started with, so the scored server cannot take these events; each custom event (and each
follow-up) gets a fresh server and a fresh world. The sandbox action log is `runs/custom/sandbox/<event_id>/action_log.jsonl` and is **never
submitted**; the scored log is only `runs/live` / `runs/dev`. Traces go to `traces/custom/<id>.json` with `orchestration.target = "sandbox"`
(`scored` for feed events, `dry` for `--dry-run`); the stream is `runs/custom/events.ndjson`. The in-process twin is used only for the
pre-flight rehearsal, `--dry-run`, and the grader/oracle.
`live.py --custom` also takes `--run-dir` (default `runs/custom`; the sandbox, stream and models land under it) and `--traces-dir`
(default `traces/custom`); `run.py` takes `--traces-dir` (default `traces/<name of --out>`).

## LLM provider outages
`complete_json` retries transient provider errors (HTTP 429/500/502/503/504, timeouts, connection errors, RESOURCE_EXHAUSTED, UNAVAILABLE,
DEADLINE_EXCEEDED, "overloaded") up to `CT_LLM_RETRIES` (default 5) provider calls with sleeps 2, 4, 8, 16 s (`CT_LLM_BACKOFF_S` sets the base)
plus up to 1 s jitter, or the delay the provider asks for (capped at 60 s). 400/401/403/404 and bad keys fail at once. `attempts` counts every provider call.
If the coordinator itself cannot get an answer, the event is **failed** (`orchestration.provider_failure = true`): no `escalate` is sent, nothing is
written, and the summary says to re-run it. After 2 consecutive such events the run aborts (loud `ABORTED:` line on stderr, exit code 2, no further
events started); `live.py` passes the exit code on.

`live.py` (the UI's "Run feed") starts its own server on a free port and forwards `--parallel`; `POST /api/run?parallel=4` does the same.

## Models per agent: `agents.toml`
One section per agent (`coordinator`, `supply_chain_planner`, `dealer_network`, `customer_care_quality`, `auditor`) with `provider`, `model`,
`max_turns`. Override without editing the file: `CT_MODEL_<AGENT_ID_UPPER>=provider/model` (a bare model keeps the provider), e.g.
```bash
CT_MODEL_COORDINATOR=anthropic/claude-sonnet-5-5 CT_MODEL_AUDITOR=gemini/gemini-3.8-flash \
  uv run python -m control_tower.run --event E-11 --dry-run --out runs/dry
```

## Verification tools
```bash
uv run python eval/run_identity.py --k 3                           # K full runs on fresh servers; diff across runs and vs traces/final; exit 1 on any diff
uv run python eval/run_identity.py --k 2 --events E-01 E-02 E-05   # a cheaper subset
PYTHONPATH=. uv run python eval/auditor_bench.py                    # planted mistakes vs the auditor -> eval/reports/auditor_bench.md
PYTHONPATH=. uv run python eval/paraphrase_bench.py --models gemini/gemini-3.8-flash gemini/gemini-3.5-flash-lite   # -> eval/reports/paraphrase_bench.md
uv run pytest                                                      # offline, includes tests/unit/test_escalation_suite.py (PLAN_V2 4.1)
```
Outputs: `runs/<name>/` (action_log.jsonl, events.ndjson, models.json), `traces/<name>/E-xx.json`. `runs/identity` is not committed.

## Cost and time (TODO after the final run)
- One sequential run of 15 events: TODO LLM calls, TODO USD, TODO minutes. A parallel run (N=4): TODO minutes.
- Auditor bench: TODO USD. Paraphrase bench (90 rewrites x 2 models): TODO USD.
