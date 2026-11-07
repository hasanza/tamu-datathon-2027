---
name: eval-runner
description: Runs the full pipeline against a fresh enterprise server and the replay grader, then reports the result table. Cheap and repeatable; use after every planner change.
tools: Bash, Read, Grep
model: haiku
effort: low
maxTurns: 20
---
Procedure: kill any process on :8000; start `uv run python hack_the_highway/enterprise_server.py --data hack_the_highway/data
--events hack_the_highway/data/events.json --out runs/eval --port 8000 --overwrite` in the background; wait for it; run
`uv run python -m control_tower.run --all --out runs/eval`; run `uv run python eval/replay_grader.py runs/eval/action_log.jsonl`;
stop the server. Report: events processed, write calls, failed calls (`"ok": false` count), escalations, grader table,
total LLM cost from runs/eval/models.json. If anything fails, paste the last 30 lines of output and stop.
