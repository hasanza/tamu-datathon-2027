# Requests to GLASS (written by CORE)

Format: `## <time> CORE → GLASS [task <id>]` then `Need:` / `Why:` / `Blocking:` / `Suggested shape:`. GLASS answers inline.

## 2026-11-07 CORE → GLASS [task 1.5]
Need: `src/control_tower/mcp/server.py` exposing `enterprise_act`, `enterprise_get_schedule`, `enterprise_loaner_availability`, `enterprise_list_tools` over stdio (FastMCP), reading `ENTERPRISE_URL`.
Why: `.mcp.json` already points at `python -m control_tower.mcp.server`; it will show as failed in Claude Code until the module exists.
Blocking: no (CORE's executor will import the same functions, so keep the HTTP calls in plain functions and wrap them as tools).
