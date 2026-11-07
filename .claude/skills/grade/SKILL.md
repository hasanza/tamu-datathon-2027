---
name: grade
description: Replay a run's action_log.jsonl on a fresh twin and diff against the deterministic oracle. Available after WORKPLAN task 3.3.
argument-hint: "[run name]"
---
Run `uv run python eval/replay_grader.py runs/<name>/action_log.jsonl --report eval/reports/<name>.md` and show the per-event
table (expected vs actual moved POs, notified dealers, loaners, held lots, stopped VINs, contacted customers, extra actions).
Highlight every mismatch with the SPEC §7 ambiguity it might stem from.
