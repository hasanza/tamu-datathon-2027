import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCheck, Radio, RotateCcw, Trash2, TriangleAlert } from "lucide-react";
import { stepSentence, toLiveStep, type ActivityItem } from "../api/stream";
import { useRunStatus, useTraces } from "../api/hooks";
import type { FeedEvent } from "../api/types";
import { confirmClause, inboxOrder } from "../lib/escalation";
import { TARGET_META, targetOf } from "../lib/target";
import { FollowUpControl, FollowUpList } from "./FollowUp";
import { prettifyRepr, safeStorage, summarize } from "../lib/format";
import { firstSentence } from "../lib/flow";
import { LANE_META, laneOf, STEP_META } from "../lib/meta";
import { Chip, Empty, Mono, Panel } from "./ui/primitives";

/* ---------------- Escalation inbox ---------------- */

function readAcked(): Set<string> {
  try {
    return new Set(JSON.parse(safeStorage("ct-acked") ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

/** More acknowledged items than this are folded behind a "Show acknowledged (n)" button. */
const ACKED_INLINE_MAX = 4;

export function EscalationInbox({ events, onSelect }: { events: FeedEvent[] | undefined; onSelect: (id: string) => void }) {
  const ids = useMemo(() => (events ?? []).filter((e) => e.status === "escalated" || e.status === "failed").sort(inboxOrder).map((e) => e.event_id), [events]);
  const { traces, loading, failed } = useTraces(ids);
  // An acknowledgement belongs to one run: the same event escalates again in the next run and must reappear.
  const run = String(useRunStatus().data?.started ?? "snapshot");
  const ackKey = (id: string) => `${run}|${id}`;
  const [acked, setAcked] = useState<Set<string>>(readAcked);
  const [showAcked, setShowAcked] = useState(false);
  // a card that appears while the panel is open flashes once (no continuous motion: it would distract)
  const seen = useRef<Set<string> | null>(null);
  const [flash, setFlash] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (loading || failed) return;
    const now = traces.map((t) => t.event_id);
    if (seen.current === null) {
      if (now.length > 0 || ids.length === 0) seen.current = new Set(now);
      return;
    }
    const fresh = now.filter((i) => !seen.current?.has(i));
    if (fresh.length > 0) {
      fresh.forEach((i) => seen.current?.add(i));
      setFlash((s) => new Set([...s, ...fresh]));
    }
  }, [traces, loading, failed, ids.length]);
  useEffect(() => void safeStorage("ct-acked", JSON.stringify([...acked])), [acked]);
  const restore = (id: string) =>
    setAcked((s) => {
      const n = new Set(s);
      n.delete(ackKey(id));
      return n;
    });
  // unacknowledged first; both groups keep the inbox order (judge input newest first, then presets newest received first)
  const open = traces.filter((t) => !acked.has(ackKey(t.event_id)));
  const done = traces.filter((t) => acked.has(ackKey(t.event_id)));
  const foldAcked = done.length > ACKED_INLINE_MAX && !showAcked;

  return (
    <Panel
      fill
      className="xl:flex-[1.8]"
      title={
        <span className="flex items-center gap-2">
          <TriangleAlert size={14} style={{ color: "var(--warn)" }} aria-hidden /> Escalation inbox
          <Chip color={open.length > 0 ? "var(--warn)" : "var(--text-3)"}>
            {open.length} open{done.length > 0 ? ` · ${done.length} acknowledged` : ""}
          </Chip>
        </span>
      }
    >
      {ids.length === 0 ? (
        <Empty title="Nothing escalated" hint="Unconfirmed or failed events land here with what a human needs to confirm." />
      ) : loading && traces.length === 0 ? (
        <Empty title="Loading escalations…" hint="Reading the traces of escalated events." />
      ) : failed && traces.length === 0 ? (
        <Empty title="Could not load escalations" hint="The API did not return the escalated traces. Check that it is running." />
      ) : (
        <>
          {open.length === 0 && <p className="mb-2 text-[12px] text-tx3">All acknowledged. Acknowledgement is local to this browser.</p>}
          <ul className="space-y-2.5" data-inbox="open">
            {open.map((t) => {
              const need = confirmClause(t);
              return (
                <li key={t.event_id} data-inbox-card className="relative rounded-lg border border-line border-l-[3px] border-l-warn bg-surface-2 p-2.5 text-[13px]">
                  {flash.has(t.event_id) && <div aria-hidden className="anim-flash pointer-events-none absolute inset-0 rounded-lg" />}
                  <div className="flex items-center justify-between gap-2">
                    <button onClick={() => onSelect(t.event_id)} className="mono font-medium text-tx underline-offset-2 hover:underline">
                      {t.event_id}
                    </button>
                    <span className="flex items-center gap-1.5">
                      <Chip color={TARGET_META[targetOf(t)].color}>{TARGET_META[targetOf(t)].label}</Chip>
                      <Chip color={t.status === "failed" ? "var(--fail)" : "var(--cat-unconfirmed)"}>{t.status}</Chip>
                    </span>
                  </div>
                  <p className="mt-1.5 text-tx2">{t.decision_reason}</p>
                  {need && (
                    <p className="mt-1.5 rounded-md border border-line bg-surface px-2 py-1.5 text-xs text-tx2">
                      <span className="font-medium text-tx">Would make it actionable: </span>
                      {need}
                    </p>
                  )}
                  <FollowUpControl trace={t} />
                  <FollowUpList parentId={t.event_id} />
                  <button
                    onClick={() => setAcked((s) => new Set(s).add(ackKey(t.event_id)))} // functional: two quick clicks must both count
                    className="mt-2 inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-tx2 hover:border-ok hover:text-tx"
                  >
                    <CheckCheck size={13} aria-hidden /> Acknowledge
                  </button>
                </li>
              );
            })}
          </ul>
          {done.length > 0 && (
            <div className="mt-3 border-t border-line pt-2" data-inbox="acknowledged">
              {foldAcked ? (
                <button onClick={() => setShowAcked(true)} className="text-[12px] text-tx3 hover:text-tx">
                  Show acknowledged ({done.length})
                </button>
              ) : (
                <>
                  {done.length > ACKED_INLINE_MAX && (
                    <button onClick={() => setShowAcked(false)} className="mb-1.5 text-[12px] text-tx3 hover:text-tx">
                      Hide acknowledged ({done.length})
                    </button>
                  )}
                  <ul className="space-y-1">
                    {done.map((t) => (
                      <li key={t.event_id} className="flex items-center gap-2 rounded-md border border-line px-2 py-1 text-[12px] text-tx3">
                        <button onClick={() => onSelect(t.event_id)} className="mono font-medium hover:text-tx hover:underline">
                          {t.event_id}
                        </button>
                        <span className="min-w-0 flex-1 truncate">{t.decision_reason}</span>
                        <button onClick={() => restore(t.event_id)} className="shrink-0 text-tx3 hover:text-tx" title="Move back to the open list">
                          Restore
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

/* ---------------- Activity log ---------------- */

const TYPE_COLOR: Record<ActivityItem["type"], string> = {
  event_received: "var(--cat-unconfirmed)",
  agent_step: "var(--cat-quality)",
  action: "var(--ok)",
  event_done: "var(--brand-bright)",
};

function KindChip({ it }: { it: ActivityItem }) {
  const kind = toLiveStep(it.payload, it.id)?.kind;
  const m = kind ? STEP_META[kind] : null;
  return m ? <Chip color={m.color}>{m.label}</Chip> : <span className="text-[10px] uppercase tracking-wide text-tx3">agent step</span>;
}

/** What one activity item says, from its structured payload fields (never the raw step text of a tool call). */
function ActivityBody({ it }: { it: ActivityItem }) {
  if (it.type === "agent_step") {
    const step = toLiveStep(it.payload, it.id);
    if (!step) return <p className="line-clamp-2 break-words text-tx2">{it.text}</p>;
    const lane = LANE_META[laneOf(step.agent)];
    const meta = STEP_META[step.kind];
    const dot = <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full align-middle" style={{ background: lane.color }} title={lane.label} aria-label={lane.label} />;
    if (step.kind === "tool" && step.tool) {
      return (
        <p className="truncate text-tx2" title={stepSentence(step)}>
          {dot}
          <Mono className="font-medium text-tx">{step.tool}</Mono>
          {step.args && Object.keys(step.args).length > 0 && ` - ${summarize(step.args)}`}
          {step.result && Object.keys(step.result).length > 0 && ` -> ${summarize(step.result)}`}
        </p>
      );
    }
    if (step.kind === "message") {
      const route = [step.from_agent, step.to_agent].filter(Boolean).map((a) => LANE_META[laneOf(a as never)]?.label ?? a).join(" -> ");
      return (
        <>
          <p className="truncate text-tx2" title={`${route}${step.task ? ` - ${step.task}` : ""}`}>
            {dot}
            {route}
            {step.task && <span className="text-tx3"> - {step.task}</span>}
          </p>
          <p className="truncate text-tx3" title={prettifyRepr(step.text)}>{firstSentence(step.text)}</p>
        </>
      );
    }
    const clamp = step.kind === "thought" ? "truncate" : "line-clamp-2";
    return (
      <p className={`${clamp} break-words text-tx2`} title={prettifyRepr(step.text)} data-kind-chip={meta.label}>
        {dot}
        {step.kind === "thought" ? firstSentence(step.text) : prettifyRepr(step.text)}
      </p>
    );
  }
  return <p className="line-clamp-2 break-words text-tx2">{prettifyRepr(it.text)}</p>;
}

export function ActivityLog({
  live,
  items,
  replay,
  setReplay,
  clear,
  onSelect,
}: {
  live: boolean;
  items: ActivityItem[];
  replay: boolean;
  setReplay: (v: boolean) => void;
  clear: () => void;
  onSelect: (id: string) => void;
}) {
  return (
    <Panel
      fill
      className="xl:flex-1"
      title={
        <span className="flex items-center gap-2">
          <Radio size={14} aria-hidden /> Activity
          <span role="status" className="inline-flex items-center gap-1 text-[11px] font-medium" style={{ color: live ? "var(--ok)" : "var(--text-3)" }}>
            <span className={`h-1.5 w-1.5 rounded-full ${live ? "bg-ok" : "bg-tx3"}`} />
            {live ? "Live" : "Reconnecting"}
          </span>
        </span>
      }
      action={
        <div className="flex gap-1">
          <button
            onClick={() => setReplay(!replay)}
            aria-pressed={replay}
            title="Reconnect and replay the whole run from the start"
            className={`rounded-md border px-1.5 py-1 text-[11px] ${replay ? "border-brand-bright text-tx" : "border-line text-tx3 hover:text-tx"}`}
          >
            <RotateCcw size={12} className="mr-1 inline" aria-hidden />
            Replay
          </button>
          <button onClick={clear} aria-label="Clear activity log" className="rounded-md border border-line px-1.5 py-1 text-tx3 hover:text-tx">
            <Trash2 size={12} aria-hidden />
          </button>
        </div>
      }
    >
      {items.length === 0 ? (
        <Empty title="Waiting for activity" hint="New events, agent steps and actions stream in here while a run is in progress." />
      ) : (
        <ol className="max-h-80 space-y-1.5 overflow-y-auto xl:max-h-none xl:overflow-visible" aria-live="off">
          {items.map((it) => (
            <li key={it.id} className="anim-slide-in flex gap-2 text-xs">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: TYPE_COLOR[it.type] }} aria-hidden />
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  {it.eventId && (
                    <button
                      onClick={() => {
                        onSelect(it.eventId as string);
                        if (it.type === "agent_step") window.dispatchEvent(new CustomEvent("ct-open-tab", { detail: "Orchestration" }));
                      }}
                      title={it.type === "agent_step" ? "Open this event's Orchestration tab" : undefined}
                      className="mono font-medium text-tx hover:underline"
                    >
                      {it.eventId}
                    </button>
                  )}
                  {it.type === "agent_step" ? (
                    <KindChip it={it} />
                  ) : (
                    <span className="text-[10px] uppercase tracking-wide text-tx3">{it.type.replace("_", " ")}</span>
                  )}
                  <Mono className="ml-auto text-tx3">{new Date(it.at).toLocaleTimeString([], { hour12: false })}</Mono>
                </div>
                <ActivityBody it={it} />
              </div>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
