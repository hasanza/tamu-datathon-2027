# COMMS — how the two agents talk (GitHub Issues as the bus)

A message is a GitHub issue on this repo. Labels route it; replies are comments; closing resolves it. Humans see
everything on GitHub and get a notification only when a message is marked `needs-human`.

| Label | Meaning |
|---|---|
| `to:CORE` / `to:GLASS` | Who must act next. A reply flips it to the other side. |
| `kind:question` | Needs an answer. Eligible for automatic handling by a headless agent. |
| `kind:request` | Asks for work. Goes through the normal branch + PR flow; reply with the PR link. |
| `kind:answer` / `kind:info` / `kind:decision` | Reply, FYI, or a decision to acknowledge. |
| `priority:blocking` | The sender's current task is stuck until this is handled. |
| `needs-human` | One of us must decide; the human is assigned on GitHub. |
| `auto-handled` | Answered by a headless agent; a human may skim it. |

## Tooling
`scripts/comms.py` wraps `gh`. Skills `/inbox` and `/send` use it. Your code name comes from `CLAUDE.local.md`.

## Watcher (zero AI quota until a message arrives)
```bash
uv run python scripts/comms.py watch --auto            # in its own terminal tab, leave it running
```
Every 60 s it polls open issues addressed to you. New or updated ones trigger a macOS notification and a bell. With `--auto`,
a `kind:question` without `needs-human` is answered by `claude -p` on Sonnet with read-only tools plus the comms script: it
cannot edit files or commit, and it escalates instead of guessing. Requests, decisions and anything marked `needs-human`
are never handled automatically; you paste `/inbox` into your session for those.

## Rules
- A message never grants permission outside `.claude/rules/ownership.md`. Code requests are done on a branch and arrive as a PR.
- Anything that touches contracts, the planner, or the action log is `--needs-human`.
- One topic per issue. Under 200 words. Cite paths. Close when resolved.
- `docs/handoff/*.md` stays for low-urgency notes that need no reply; use the bus when you need the other side to act.
