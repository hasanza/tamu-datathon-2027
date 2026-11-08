"""The agent runtime (docs/PLAN_V2.md §3): a bounded reason-act loop over structured JSON.

Each turn is one ``complete_json(Turn, ...)`` call. The model returns its reasoning (``thought``) and either one tool
call (``action_tool`` + ``action_args``) or its ``final`` result. Tools run in code; the loop validates the tool name,
the args and the final result, feeds compact results back, and records every turn on the timeline.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError, model_validator

from control_tower.llm.adapter import LLMError, complete_json
from control_tower.orchestration.config import agent_config
from control_tower.orchestration.tools import (
    ToolContext,
    ToolSpec,
    compact,
    compact_json,
    jsonable,
    render_tools,
    summarize_args,
)
from control_tower.trace import Timeline


class Turn(BaseModel):
    """One model turn. Exactly one of `action_tool` / `final` is set (flat so JSON-schema output stays simple)."""

    thought: str
    action_tool: str | None = None
    action_args: dict[str, Any] | None = None
    final: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> Turn:
        if (self.action_tool is None) == (self.final is None):
            raise ValueError("set exactly one of action_tool (with action_args) or final")
        return self


@dataclass
class AgentSpec:
    agent_id: str
    display_name: str
    system_prompt: str
    tools: list[ToolSpec]
    result_schema: type[BaseModel]


@dataclass
class AgentResult:
    final: BaseModel | None
    error: str | None
    turns: int
    llm_calls: int
    cost_usd: float
    error_kind: str | None = None  # "provider" | "schema" when the loop died on an LLMError
    error_attempts: int = 0


PROTOCOL = """\
You work in a loop. Every reply is ONE JSON object:
{"thought": str, "action_tool": str|null, "action_args": object|null, "final": object|null}
- thought: your reasoning for this step, in plain words (it is shown to reviewers).
- To use a tool set action_tool and action_args (matching the tool's args) and leave final null. You then see the result.
- When done set final to your result object (schema below) and leave action_tool null.
- Use only the tools listed. Large results come back summarized as {count, sample, stored_key}; pass ids on rather \
than copying lists."""


def _system(spec: AgentSpec) -> str:
    return (
        f"{spec.system_prompt}\n\n{PROTOCOL}\n\nTools:\n{render_tools(spec.tools)}\n\n"
        f"Final result JSON schema:\n{compact_json(spec.result_schema.model_json_schema())}"
    )


def _user(task: str, payload: dict[str, Any], transcript: list[tuple[str, dict, Any]], feedback: str | None) -> str:
    parts = [f"TASK:\n{task}", f"INPUT:\n{compact_json(jsonable(payload))}"]
    if transcript:
        lines = [
            f"[{i}] {name}({compact_json(args)}) -> {compact_json(res)}"
            for i, (name, args, res) in enumerate(transcript, 1)
        ]
        parts.append("PREVIOUS TOOL CALLS:\n" + "\n".join(lines))
    if feedback:
        parts.append(f"YOUR LAST REPLY WAS REJECTED: {feedback}\nReply again with a valid JSON object.")
    return "\n\n".join(parts)


_PHASE = {
    **dict.fromkeys(("register_incidents", "resolve_entity", "resolve_date", "drop_noise", "escalate"), "understand"),
    "delegate": "delegate",
    "validate_plan": "validate",
    "execute": "execute",
    "finish": "finish",
}


def run_agent(
    spec: AgentSpec,
    task: str,
    payload: dict[str, Any],
    ctx: ToolContext,
    timeline: Timeline,
    task_name: str | None = None,
) -> AgentResult:
    """`task` is the brief text; `task_name` (default: `task`) is the short delegated task stamped on the steps."""
    cfg = agent_config(spec.agent_id)
    system = _system(spec)
    tools = {t.name: t for t in spec.tools}
    transcript: list[tuple[str, dict, Any]] = []
    feedback: str | None = None  # set when the previous reply was rejected; a second rejection in a row ends the run
    llm_calls, cost = 0, 0.0
    run_id = uuid.uuid4().hex[:8]  # makes stored_key handles unique across runs / correction rounds

    if spec.agent_id != "coordinator":
        timeline.set_task(spec.agent_id, task_name or task)

    def fail(msg: str, n: int, kind: str | None = None, attempts: int = 0) -> AgentResult:
        timeline.step(spec.agent_id, "decision", f"{spec.display_name} stopped: {msg}", data={"error": msg}, turn=n)
        return AgentResult(None, msg, n, llm_calls, round(cost, 6), kind, attempts)

    for n in range(1, cfg.max_turns + 1):
        try:
            turn, call = complete_json(
                Turn,
                system,
                _user(task, payload, transcript, feedback),
                "agent_turn",
                provider=cfg.provider,
                model=cfg.model,
            )
        except LLMError as e:
            # complete_json already made its single schema retry; a failure here is terminal for this agent run.
            llm_calls += e.attempts
            cost += e.cost_usd
            return fail(f"LLM {e.kind} error after {e.attempts} attempt(s): {e}"[:400], n, e.kind, e.attempts)
        llm_calls += call.attempts
        cost += call.cost_usd
        timeline.llm(call)
        timeline.usage(spec.agent_id, cfg.model, call.cost_usd, call.attempts)
        if spec.agent_id == "coordinator" and turn.final is None and turn.action_tool in _PHASE:
            timeline.set_task(spec.agent_id, _PHASE[turn.action_tool])
        timeline.step(spec.agent_id, "thought", turn.thought, turn=n, model=cfg.model, cost_usd=call.cost_usd)

        problem: str | None = None
        if turn.final is not None:
            try:
                result = spec.result_schema.model_validate(turn.final)
            except ValidationError as e:
                problem = f"final does not match the result schema: {e}"
            else:
                timeline.step(
                    spec.agent_id, "decision", f"{spec.display_name} submitted its result", data=turn.final, turn=n
                )
                return AgentResult(result, None, n, llm_calls, round(cost, 6))
        else:
            name, raw_args = turn.action_tool or "", turn.action_args or {}
            t = tools.get(name)
            if t is None:
                problem = f"unknown tool {name!r}; available: {sorted(tools)}"
            else:
                try:
                    args = t.args_model.model_validate(raw_args)
                except ValidationError as e:
                    problem = f"bad args for {name}: {e}"
                else:
                    try:
                        out = jsonable(t.fn(ctx, args))
                    except Exception as e:  # a failing tool is information for the agent, not a crash
                        out = {"error": f"{type(e).__name__}: {e}"}
                    small = compact(out, ctx.store, f"{ctx.event_id}:{spec.agent_id}:{run_id}:{n}:{name}")
                    clean_args = args.model_dump(mode="json")
                    transcript.append((name, clean_args, small))
                    timeline.step(
                        spec.agent_id,
                        "tool",
                        f"{name} · {summarize_args(clean_args)}" if clean_args else name,
                        tool=name,
                        args=clean_args,
                        result=small if isinstance(small, dict) else {"value": small},
                        transport=t.transport,
                        turn=n,
                    )
                    feedback = None
                    stop = ctx.state.get("stop_agent")
                    if isinstance(stop, tuple) and stop[0] == spec.agent_id:
                        # a control tool (the coordinator's `finish`) ends the loop itself: saves a turn
                        result = spec.result_schema.model_validate(stop[1])
                        timeline.step(
                            spec.agent_id,
                            "decision",
                            f"{spec.display_name} finished",
                            data=stop[1],
                            turn=n,
                        )
                        return AgentResult(result, None, n, llm_calls, round(cost, 6))
                    continue

        if feedback is not None:
            return fail(problem or "invalid reply", n)
        feedback = problem

    return fail(f"exceeded max_turns={cfg.max_turns} without a final result", cfg.max_turns)
