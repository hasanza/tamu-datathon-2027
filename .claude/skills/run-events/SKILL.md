---
name: run-events
description: Start a fresh enterprise server and run the pipeline on all 15 events (or one), then summarize the action log. Available after WORKPLAN task 3.1.
argument-hint: "[event_id] [--run <name>]"
---
1. Choose run name from args (default `dev`). Free port 8000 if needed.
2. Start `uv run python hack_the_highway/enterprise_server.py --data hack_the_highway/data --events hack_the_highway/data/events.json --out runs/<name> --port 8000 --overwrite` in the background and wait until `curl -s localhost:8000/events` answers.
3. Run `uv run python -m control_tower.run --all --out runs/<name>` or `--event <event_id>`.
4. Print a table per event: category, confidence, write calls, failed calls, escalated, LLM cost. Then `grep -c '"ok": false' runs/<name>/action_log.jsonl` (must be 0).
5. Stop the server.
