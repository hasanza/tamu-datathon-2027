import { useState } from "react";
import { Bot, ChevronDown, ChevronRight, Cpu, FlaskConical, GitBranch, ListTodo, MessageSquareText, Play, ShieldCheck, StickyNote } from "lucide-react";
import type { AgentRun, AgentStep, StepKind, Trace } from "../api/types";
import { Chip, Empty, Mono, Panel } from "../components/ui/primitives";
import { clock, durationMs, offsetMs } from "../lib/format";
import { AGENT_META, STEP_META } from "../lib/meta";

const STEP_ICON: Record<StepKind, typeof Bot> = {
  llm: Cpu,
  graph: GitBranch,
  plan: ListTodo,
  rehearse: FlaskConical,
  audit: ShieldCheck,
  execute: Play,
  gate: MessageSquareText,
  note: StickyNote,
};

function Step({ step, start, last }: { step: AgentStep; start: string; last: boolean }) {
  const [open, setOpen] = useState(false);
  const m = STEP_META[step.kind];
  const Icon = STEP_ICON[step.kind];
  const hasData = !!step.data && Object.keys(step.data).length > 0;
  return (
    <li className="relative flex gap-3 pb-3">
      {!last && <span className="absolute left-[13px] top-7 h-[calc(100%-1.25rem)] w-px bg-line" aria-hidden />}
      <span
        className="relative z-10 flex h-[27px] w-[27px] shrink-0 items-center justify-center rounded-full border bg-surface"
        style={{ borderColor: m.color, color: m.color }}
        aria-hidden
      >
        <Icon size={13} />
      </span>
      <div className="min-w-0 flex-1 pt-0.5">
        <div className="flex flex-wrap items-center gap-2">
          <Chip color={m.color}>{m.label}</Chip>
          <Mono className="text-tx3">
            {clock(step.t)} {offsetMs(start, step.t)}
          </Mono>
          {hasData && (
            <button
              onClick={() => setOpen(!open)}
              aria-expanded={open}
              className="ml-auto inline-flex items-center gap-0.5 text-[11px] text-tx3 hover:text-tx"
            >
              {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />} details
            </button>
          )}
        </div>
        <p className="mt-1 break-words text-[13px] text-tx2">{step.text}</p>
        {open && hasData && (
          <pre className="mono mt-1.5 max-h-60 overflow-auto rounded-md border border-line bg-bg p-2 text-[11px] text-tx2">
            {JSON.stringify(step.data, null, 2)}
          </pre>
        )}
      </div>
    </li>
  );
}

function AgentCard({ run }: { run: AgentRun }) {
  const m = AGENT_META[run.agent];
  const counts = run.steps.reduce<Record<string, number>>((a, s) => ({ ...a, [s.kind]: (a[s.kind] ?? 0) + 1 }), {});
  return (
    <Panel
      title={
        <span className="flex flex-wrap items-baseline gap-2">
          {m.label}
          <span className="text-[11px] font-normal text-tx3">{m.blurb}</span>
        </span>
      }
      action={
        <span className="mono whitespace-nowrap text-[11px] text-tx3">
          {run.steps.length} steps · {durationMs(run.started, run.ended)}
        </span>
      }
    >
      <div className="mb-3 flex flex-wrap gap-1">
        {Object.entries(counts).map(([k, n]) => (
          <Chip key={k} color={STEP_META[k as StepKind].color}>
            {STEP_META[k as StepKind].label} {n}
          </Chip>
        ))}
      </div>
      {run.steps.length === 0 ? (
        <p className="text-xs text-tx3">This agent had nothing to do for this event.</p>
      ) : (
        <ol>
          {run.steps.map((s, i) => (
            <Step key={i} step={s} start={run.started} last={i === run.steps.length - 1} />
          ))}
        </ol>
      )}
    </Panel>
  );
}

export function AgentsTab({ trace }: { trace: Trace }) {
  if (trace.agents.length === 0) return <Empty title="No agent activity recorded" hint="This event was resolved before any specialist was involved." />;
  return (
    <div className="grid gap-4 2xl:grid-cols-2">
      {trace.agents.map((a) => (
        <AgentCard key={a.agent} run={a} />
      ))}
    </div>
  );
}
