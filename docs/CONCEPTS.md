# CONCEPTS — the ideas this project stands on, mapped to our build

A primer for the team. Each section: the idea in plain words → how we use it here → one pitfall.

## 1. Agents vs workflows
An **LLM workflow** is code that calls a model at fixed points (classify here, summarize there). An **agent** lets the model
decide which tool to call next in a loop. Workflows are predictable and cheap; agents are flexible and expensive.
Anthropic's guidance ("Building effective agents") is: start with the simplest thing that works, add autonomy only where
the task is genuinely open-ended.
- **Here**: the tower is mostly a workflow with agentic flavour. The LLM decides *what happened*; code decides *what to do*.
  Specialists are LLM-supervised code: the model narrates and can veto, the planner computes.
- **Pitfall**: letting the LLM pick action arguments (ids, dates) by itself — that is where wrong/extra actions come from.

## 2. Multi-agent orchestration patterns
- **Orchestrator–workers**: a coordinator breaks a task into parts and dispatches to specialists; it owns shared state and the final answer. (Ours.)
- **Router**: classify, then send to one handler. (Our triage step.)
- **Pipeline / prompt chaining**: fixed stages with validation gates between them. (Understand → validate → plan → rehearse → execute.)
- **Evaluator–optimizer**: one model produces, another critiques. (Our LLM auditor before commit.)
- **Parallel fan-out / voting**: run independent workers and merge. (Could paraphrase the event N ways and vote on category if accuracy needs a boost.)
- **Shared state** is the hard part: in a compound event both incidents draw from the same slots and loaner pools, so the coordinator owns a single `WorldState` and specialists mutate it in order.
- **Pitfall**: more agents ≠ better. Judges want clear responsibilities, not chatter. Four agents, each with a one-line job.

## 3. Tool use and structured outputs
The model emits a JSON object (a "tool call" or a schema-constrained answer); your code runs it and returns the result.
Structured outputs (`output_config.format` with a JSON schema / Pydantic model) make the model's answer parse-safe.
- **Here**: `IncidentSpec` is a Pydantic model; extraction returns it directly. Tool execution goes through MCP (below).
- **Pitfall**: trusting the schema-valid answer as *true*. Schema validity ≠ correctness; we re-validate against the data.

## 4. MCP — Model Context Protocol
A standard for connecting models to tools and data. Three roles: **host** (the app that runs the model, e.g. Claude Code or
our orchestrator), **client** (one connection inside the host), **server** (exposes `tools`, `resources`, `prompts`).
Transports: **stdio** (server is a subprocess; simplest for local) or **HTTP** (remote). Tools are described with JSON
schemas; the host lists them, the model picks, the host calls the server, the server returns content.
- **Here**: `control_tower/mcp/server.py` is an MCP server with two tool families: `enterprise_*` (thin wrappers over `POST /act`
  and the read tools) and `graph_*` (impact traversal with paths). Our executor is the MCP client. The same server is
  registered in `.mcp.json`, so Claude Code can call the identical tools while you develop — one server, two hosts.
- **Why judges care**: "MCP-style tool execution" is a rubric line; a real MCP server with typed tools is a concrete answer.
- **Pitfall**: exposing every table as a tool. Expose intents (`graph_impact_of_shipment`), not raw SQL.

## 5. Ontology and knowledge graph
An **ontology** is the schema: what kinds of things exist and how they relate (Shipment →of_part→ Part; Model →uses_part→ Part…).
A **knowledge graph** is the data loaded into that schema. Traversal answers "what does this touch?" by following typed edges,
and the **path** is the explanation.
- **Here**: `networkx.MultiDiGraph` with typed nodes/edges built from the CSVs. Traversals return paths, not just ids, so every
  action cites Shipment → Part → Model → PO → CO → Dealer. Export as Mermaid (diagram) + GraphML (data) for the submission.
- **Pitfall**: building a graph but then querying pandas. Make the traversal the only way specialists find records.

## 6. Entity resolution and temporal grounding
Humans write "the Texas plant", "harness B", "Volt". Resolution order: exact id → alias table → canonical names → fuzzy match
→ LLM tie-break → escalate. Relative dates ("next Friday", "last Monday") resolve against an anchor (today = Mon 2027-03-08)
using a stated convention, then **snap to the data**: a shipment date must be a real ETA; a lot window must match a real lot.
- **Pitfall**: letting the model silently "fix" a date. Mismatch is information; it lowers confidence.

## 7. Guardrails, validation, and human-in-the-loop
Layers: schema validation → data validation → policy invariants (≥3 action kinds, one notice per dealer, nothing unaffected)
→ **rehearsal on a twin** → LLM audit → execute → runtime error capture. Human-in-the-loop = `escalate` with a precise question,
used for rumors, low confidence, failed rehearsal, or runtime failure.
- **Pitfall**: escalating too much. Clean, specific events must flow straight through.

## 8. Digital twin / simulation before action
If you can run the real system's logic locally, you can test a plan before committing it. Our twin is the organizers' own
`Enterprise` class; same validation code the server uses. It turns "we hope the calls succeed" into "we know they do".

## 9. Observability: traces and audit trails
A **trace** is the structured record of one event's journey: inputs, model outputs (with tokens/cost), resolutions, paths,
plan, rehearsal result, executed actions and results, final summary. The **audit trail** is the world's before/after diff.
- **Here**: `traces/<event_id>.json`; UI reads traces + `action_log.jsonl`. Cite model ids and token totals per run.

## 10. Evaluation
You cannot improve what you cannot measure. Build the grader early: an **oracle** (expected actions from the rules) and a
**replay grader** (re-run the log on a fresh twin, diff). Then a **robustness bench**: paraphrased events to measure
extraction accuracy. Evals also protect you from late-night regressions.

## 11. Model selection and cost
Small models (Haiku 5.5: $0.10/$0.50 per MTok) are excellent at constrained extraction with a good schema and examples;
bigger models (Sonnet 5.5) are the fallback when confidence is low. Use caching for the stable prompt prefix (alias table,
handbook) and log `usage` on every call. Efficiency is a rubric line: cite the models and the total spend.

## 12. Agent-first development (how we build it)
The same ideas apply to *us*: a planning model (Fable) in plan mode, cheaper implementers (Sonnet), a cheap eval runner (Haiku),
an adversarial reviewer (Opus / Codex), project memory (`CLAUDE.md`, `.claude/rules`), reusable procedures (`.claude/skills`),
and our own MCP server plugged into the IDE. See PLAN.md §9.

## Reading list
- Anthropic, "Building effective agents" — patterns in §2.
- Model Context Protocol docs: modelcontextprotocol.io (architecture, tools, transports); Python SDK `mcp` (FastMCP).
- Claude Code docs: sub-agents, skills, MCP, hooks, memory (code.claude.com/docs).
- Claude API: structured outputs, tool use, prompt caching (platform.claude.com/docs).
