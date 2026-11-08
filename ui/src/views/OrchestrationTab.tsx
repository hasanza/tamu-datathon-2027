import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight } from "lucide-react";
import type { AgentStep, StepKind, Trace } from "../api/types";
import type { LiveStep } from "../api/stream";
import { Chip, Empty, Mono, Panel } from "../components/ui/primitives";
import { Clamped, DECISION_COLOR, Details, Meta, echoesCall, hasKeys } from "./orchParts";
import { FlowView } from "./FlowView";
import { FollowChip } from "../components/ui/FollowChip";
import { useFollow } from "../lib/useFollow";
import { compactArgs, prettifyRepr, safeStorage, summarize } from "../lib/format";
import { BADGE_COLOR, LANE_META, LANES, laneOf, STEP_META, toolBadge, type LaneId } from "../lib/meta";

/* The Orchestration view (PLAN_V2 §8): four swimlanes, time flowing down. Cards are Thought (the agent's reasoning),
   Tool call (name, args, result, MCP / graph badge), Message (an arrow between two lanes) and Decision
   (gate passed, plan validated, correction round, escalated, executed). v1 traces (old agent ids and step kinds)
   render too: their steps map onto the same lanes as generic cards. */

export interface OrchRow {
  key: string;
  lane: LaneId;
  step: AgentStep;
}

/** Flatten a trace's per-agent runs (v1 or v2 ids) into one time-ordered list of rows. */
export function rowsFromTrace(trace: Trace): OrchRow[] {
  return orderRows(trace.agents.flatMap((run, ri) => run.steps.map((step, si) => ({ key: `${ri}-${si}`, lane: laneOf(run.agent), step }))));
}
export function rowsFromLive(steps: LiveStep[]): OrchRow[] {
  return orderRows(steps.map((s) => ({ key: `live-${s.id}`, lane: laneOf(s.agent), step: s })));
}
function orderRows(rows: OrchRow[]): OrchRow[] {
  return rows
    .map((r, i) => ({ r, i, t: Date.parse(r.step.t) }))
    .sort((a, b) => (Number.isNaN(a.t) || Number.isNaN(b.t) || a.t === b.t ? a.i - b.i : a.t - b.t))
    .map((x) => x.r);
}

/* ---------- cards ---------- */

function Card({ row, start }: { row: OrchRow; start: string }) {
  const { step, lane } = row;
  const color = LANE_META[lane].color;
  const base = "rounded-lg border bg-surface-2 px-2 py-1.5 text-[12px]";
  const kind: StepKind = step.kind;

  if (kind === "thought") {
    return (
      <div className={`${base} border-line`} style={{ borderLeftColor: color, borderLeftWidth: 3 }}>
        <div className="mb-0.5 flex items-center gap-1.5">
          <Chip color={STEP_META.thought.color}>Thought{step.turn != null ? ` ${step.turn}` : ""}</Chip>
          <Meta step={step} start={start} />
        </div>
        <Clamped text={step.text} italic />
        <Details step={step} />
      </div>
    );
  }

  if (kind === "tool") {
    const badge = toolBadge(step);
    return (
      <div className={`${base} border-line`} style={{ borderLeftColor: color, borderLeftWidth: 3 }}>
        <div className="mb-1 flex flex-wrap items-center gap-1.5">
          <Chip color={STEP_META.tool.color}>Call</Chip>
          <Chip color={BADGE_COLOR[badge]}>{badge}</Chip>
          <Meta step={step} start={start} />
        </div>
        <Mono className="break-all font-medium text-tx">{step.tool ?? "tool"}</Mono>
        {echoesCall(step) && hasKeys(step.args) && (
          <p className="mono mt-0.5 truncate text-[11px] text-tx3" title={compactArgs(step.args)}>
            {summarize(step.args)}
          </p>
        )}
        {!echoesCall(step) && <p className="mt-1 break-words text-tx2">{prettifyRepr(step.text)}</p>}
        {hasKeys(step.result) && (
          <p className="mono mt-0.5 truncate text-[11px] text-tx2" title={compactArgs(step.result)}>
            → {summarize(step.result)}
          </p>
        )}
        <Details step={step} />
      </div>
    );
  }

  if (kind === "decision") {
    const c = DECISION_COLOR(step.text);
    return (
      <div className={`${base}`} style={{ borderColor: `color-mix(in srgb, ${c} 55%, transparent)`, background: `color-mix(in srgb, ${c} 10%, var(--surface-2))` }}>
        <div className="mb-0.5 flex items-center gap-1.5">
          <Chip color={c}>Decision</Chip>
          <Meta step={step} start={start} />
        </div>
        <p className="break-words font-medium text-tx">{prettifyRepr(step.text)}</p>
        <Details step={step} />
      </div>
    );
  }

  // v1 kinds (llm, graph, plan, rehearse, audit, execute, gate, note) and anything unknown
  const m = STEP_META[kind] ?? { label: String(kind), color: "var(--text-3)" };
  return (
    <div className={`${base} border-line`} style={{ borderLeftColor: m.color, borderLeftWidth: 3 }}>
      <div className="mb-0.5 flex items-center gap-1.5">
        <Chip color={m.color}>{m.label}</Chip>
        <Meta step={step} start={start} />
      </div>
      <p className="break-words text-tx2">{prettifyRepr(step.text)}</p>
      <Details step={step} />
    </div>
  );
}

function MessageCard({ row, start }: { row: OrchRow; start: string }) {
  const { step } = row;
  const from = laneOf(step.from_agent ?? row.lane);
  const to = step.to_agent ? laneOf(step.to_agent) : null;
  return (
    <div className="rounded-lg border border-dashed border-line bg-surface px-2.5 py-2 text-[12.5px]">
      <div className="mb-0.5 flex flex-wrap items-center gap-1.5">
        <Chip color={STEP_META.message.color}>Message</Chip>
        <span className="inline-flex items-center gap-1 text-[11px] font-medium text-tx">
          {LANE_META[from].label}
          {to && (
            <>
              <ArrowRight size={13} style={{ color: STEP_META.message.color }} aria-label="to" />
              {LANE_META[to].label}
            </>
          )}
        </span>
        <Meta step={step} start={start} />
      </div>
      <Clamped text={step.text} />
      <Details step={step} />
    </div>
  );
}

/* ---------- the view ---------- */

export function OrchestrationView({ rows, live = false, empty }: { rows: OrchRow[]; live?: boolean; empty?: { title: string; hint: string } }) {
  const start = rows[0]?.step.t ?? "";
  const listRef = useRef<HTMLOListElement>(null);
  const count = rows.length;
  const [reduced, setReduced] = useState(() => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const m = window.matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setReduced(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  // a live run: keep the newest card in the middle of the tab's scroller until the reader scrolls (then offer to resume)
  const follow = useFollow({
    scroller: () => listRef.current?.closest<HTMLElement>('[role="tabpanel"]') ?? null,
    target: () => (listRef.current?.lastElementChild as HTMLElement | null) ?? null,
    axis: "y",
    enabled: live && count > 0,
    activeKey: count,
    resetKey: live,
    reduced,
  });

  if (count === 0) return empty ? <Empty title={empty.title} hint={empty.hint} /> : null;
  return (
    <div className="space-y-3">
      {follow.paused && (
        <div className="sticky top-0 z-20 flex justify-end">
          <FollowChip onResume={follow.resume} />
        </div>
      )}
      <Panel>
        {/* lane headers (desktop): one column per agent */}
        <div className="sticky top-0 z-10 -mx-3 -mt-3 mb-3 hidden grid-cols-4 gap-x-3 border-b border-line bg-surface px-3 py-2 md:grid">
          {LANES.map((l) => (
            <div key={l} className="min-w-0">
              <div className="flex items-center gap-1.5 text-[12px] font-semibold">
                <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: LANE_META[l].color }} aria-hidden />
                <span className="truncate">{LANE_META[l].label}</span>
              </div>
              <div className="truncate text-[10.5px] text-tx3">{LANE_META[l].blurb}</div>
            </div>
          ))}
        </div>
        <div className="relative">
          <div className="pointer-events-none absolute inset-0 hidden grid-cols-4 gap-x-3 md:grid" aria-hidden>
            {LANES.map((l) => (
              <div key={l} className="border-l border-line/60" />
            ))}
          </div>
          <ol ref={listRef} className="relative space-y-2">
            {rows.map((row) => {
              const from = LANES.indexOf(laneOf(row.step.from_agent ?? row.lane));
              const toLane = row.step.to_agent ? LANES.indexOf(laneOf(row.step.to_agent)) : -1;
              const isMsg = row.step.kind === "message";
              const a = isMsg && toLane >= 0 ? Math.min(from, toLane) : LANES.indexOf(row.lane);
              const b = isMsg && toLane >= 0 ? Math.max(from, toLane) : LANES.indexOf(row.lane);
              return (
                <li key={row.key} className="md:grid md:grid-cols-4 md:gap-x-3">
                  <div className="min-w-0 md:[grid-column:var(--c)]" style={{ ["--c" as string]: `${a + 1} / ${b + 2}` }}>
                    {/* phone: no lanes, so say whose card this is */}
                    <div className="mb-0.5 flex items-center gap-1.5 text-[10.5px] text-tx3 md:hidden">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: LANE_META[row.lane].color }} aria-hidden />
                      {LANE_META[row.lane].label}
                    </div>
                    {isMsg ? <MessageCard row={row} start={start} /> : <Card row={row} start={start} />}
                  </div>
                </li>
              );
            })}
          </ol>
        </div>
      </Panel>
      {/* room below the newest card so that it can reach the middle of the scroller while a run is live */}
      {live && <div aria-hidden className="h-[45vh]" />}
    </div>
  );
}

/** The tab for a finished event (v1 or v2 trace). */
type OrchView = "flow" | "timeline";
const VIEW_KEY = "ct-orch-view";

/** Flow (the story: stage nodes) is the default; Timeline is the detailed lane view. The choice is remembered per browser. */
function useOrchView(): [OrchView, (v: OrchView) => void] {
  const [view, setView] = useState<OrchView>(() => (safeStorage(VIEW_KEY) === "timeline" ? "timeline" : "flow"));
  return [
    view,
    (v) => {
      setView(v);
      safeStorage(VIEW_KEY, v);
    },
  ];
}

function OrchestrationShell({ rows, trace, live, eventId, empty }: { rows: OrchRow[]; trace?: Trace; live: boolean; eventId: string; empty?: { title: string; hint: string } }) {
  const [view, setView] = useOrchView();
  if (rows.length === 0 && empty) return <Empty title={empty.title} hint={empty.hint} />;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[15px] font-semibold tracking-tight">Reasoning Trace</h2>
        <div role="group" aria-label="Orchestration view" className="ml-auto flex rounded-md border border-line p-0.5 text-[12px]">
          {(["flow", "timeline"] as const).map((v) => (
            <button
              key={v}
              aria-pressed={view === v}
              onClick={() => setView(v)}
              className={`rounded px-2.5 py-1 font-medium ${view === v ? "bg-surface-2 text-tx" : "text-tx3 hover:text-tx"}`}
            >
              {v === "flow" ? "Flow" : "Detailed timeline"}
            </button>
          ))}
        </div>
      </div>
      {view === "flow" ? (
        <>
          <FlowView
            rows={rows}
            status={trace?.status}
            correctionRounds={trace?.orchestration?.correction_rounds}
            escalations={trace?.orchestration?.escalations}
            live={live}
            eventId={eventId}
          />
        </>
      ) : (
        <OrchestrationView rows={rows} live={live} empty={empty} />
      )}
    </div>
  );
}

/** The tab for a finished event (v1 or v2 trace). */
export function OrchestrationTab({ trace }: { trace: Trace }) {
  const rows = useMemo(() => rowsFromTrace(trace), [trace]);
  return (
    <OrchestrationShell
      rows={rows}
      trace={trace}
      live={false}
      eventId={trace.event_id}
      empty={{ title: "No agent activity recorded", hint: "This event was resolved before any agent was involved." }}
    />
  );
}

/** Stages and cards streamed over SSE while an event is still running and its trace does not exist yet. */
export function LiveOrchestration({ steps, eventId }: { steps: LiveStep[]; eventId: string }) {
  const rows = useMemo(() => rowsFromLive(steps), [steps]);
  return <OrchestrationShell rows={rows} live eventId={eventId} />;
}
