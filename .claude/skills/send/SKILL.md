---
name: send
description: Send a message to the other code name's agent over the GitHub-Issues bus (question, request, answer, info, decision). Use instead of docs/handoff when you need the other side to act or answer.
argument-hint: "<CORE|GLASS> <kind> <subject> -- <body> [--task <id>] [--blocking] [--needs-human]"
---
Run `uv run python scripts/comms.py send --to <CORE|GLASS> --kind <kind> --task <id> --subject "<subject>" --body "<body>"`.
Add `--blocking` only if your current task cannot proceed without the answer. Add `--needs-human` when a human must decide
(contracts, planner behaviour, anything that changes the action log, scope cuts); that also assigns the human on GitHub.
Prefer one message per topic. Print the issue URL back to the user.
