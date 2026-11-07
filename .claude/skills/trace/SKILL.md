---
name: trace
description: Pretty-print one event's trace (classification, incidents, graph paths, actions with rehearsal/result, summary) for a human audit against the handbook.
argument-hint: "<event_id> [run name]"
---
Read `traces/<run or dev>/<event_id>.json` (fall back to `traces/examples/<event_id>.json`). Validate it with
`uv run python -c "from control_tower.schemas import Trace; import sys,json; Trace.model_validate(json.load(open(sys.argv[1])))" <path>`.
Then print: event text; category + confidence + reason; each incident's resolved ids and dates with the resolution method;
each graph path as `A -[edge]-> B` lines; the actions table (seq, agent, tool, key args, rehearsal, result); summary and
decision reason. End with the handbook checklist: right category? only affected ids? one notify per dealer? loaner order?
nothing extra? ≥3 action kinds for a real incident?
