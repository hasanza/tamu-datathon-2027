import { useEffect, useMemo, useState } from "react";
import { CheckCheck, Radio, RotateCcw, Trash2, TriangleAlert } from "lucide-react";
import type { ActivityItem } from "../api/stream";
import { useRunStatus, useTraces } from "../api/hooks";
import type { FeedEvent, Trace } from "../api/types";
import { safeStorage } from "../lib/format";
import { Chip, Empty, Mono, Panel } from "./ui/primitives";

/* ---------------- Escalation inbox ---------------- */

function confirmClause(t: Trace): string | null {
  const esc = t.actions.find((a) => a.tool === "escalate");
  const reason = typeof esc?.args.reason === "string" ? esc.args.reason : "";
  const m = /Please confirm:\s*(.*?)\.\s*(?:No operational|$)/s.exec(reason);
  if (m?.[1]) return m[1];
  const blocking = t.incidents.flatMap((i) => i.ambiguities.filter((a) => a.blocking).map((a) => a.issue));
  return blocking.length ? `Resolve: ${blocking.join("; ")}` : null;
}

function readAcked(): Set<string> {
  try {
    return new Set(JSON.parse(safeStorage("ct-acked") ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

export function EscalationInbox({ events, onSelect }: { events: FeedEvent[] | undefined; onSelect: (id: string) => void }) {
  const ids = useMemo(() => (events ?? []).filter((e) => e.status === "escalated" || e.status === "failed").map((e) => e.event_id), [events]);
  const { traces, loading, failed } = useTraces(ids);
  // An acknowledgement belongs to one run: the same event escalates again in the next run and must reappear.
  const run = String(useRunStatus().data?.started ?? "snapshot");
  const ackKey = (id: string) => `${run}|${id}`;
  const [acked, setAcked] = useState<Set<string>>(readAcked);
  useEffect(() => void safeStorage("ct-acked", JSON.stringify([...acked])), [acked]);
  const open = traces.filter((t) => !acked.has(ackKey(t.event_id)));

  return (
    <Panel
      title={
        <span className="flex items-center gap-2">
          <TriangleAlert size={14} style={{ color: "var(--cat-unconfirmed)" }} aria-hidden /> Escalation inbox
          <Chip color="var(--cat-unconfirmed)">{open.length} open</Chip>
        </span>
      }
    >
      {ids.length === 0 ? (
        <Empty title="Nothing escalated" hint="Unconfirmed or failed events land here with what a human needs to confirm." />
      ) : loading && traces.length === 0 ? (
        <Empty title="Loading escalations…" hint="Reading the traces of escalated events." />
      ) : failed && traces.length === 0 ? (
        <Empty title="Could not load escalations" hint="The API did not return the escalated traces. Check that it is running." />
      ) : open.length === 0 ? (
        <Empty title="All acknowledged" hint="Acknowledgement is local to this browser." />
      ) : (
        <ul className="space-y-2.5">
          {open.map((t) => {
            const need = confirmClause(t);
            return (
              <li key={t.event_id} className="rounded-lg border border-line bg-surface-2 p-2.5 text-[13px]">
                <div className="flex items-center justify-between gap-2">
                  <button onClick={() => onSelect(t.event_id)} className="mono font-medium text-tx underline-offset-2 hover:underline">
                    {t.event_id}
                  </button>
                  <Chip color={t.status === "failed" ? "var(--fail)" : "var(--cat-unconfirmed)"}>{t.status}</Chip>
                </div>
                <p className="mt-1.5 text-tx2">{t.decision_reason}</p>
                {need && (
                  <p className="mt-1.5 rounded-md border border-line bg-surface px-2 py-1.5 text-xs text-tx2">
                    <span className="font-medium text-tx">Would make it actionable: </span>
                    {need}
                  </p>
                )}
                <button
                  onClick={() => setAcked(new Set(acked).add(ackKey(t.event_id)))}
                  className="mt-2 inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs text-tx2 hover:border-ok hover:text-tx"
                >
                  <CheckCheck size={13} aria-hidden /> Acknowledge
                </button>
              </li>
            );
          })}
        </ul>
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
      title={
        <span className="flex items-center gap-2">
          <Radio size={14} aria-hidden /> Activity
          <span role="status" className="inline-flex items-center gap-1 text-[11px] font-medium" style={{ color: live ? "var(--ok)" : "var(--text-3)" }}>
            <span className={`h-1.5 w-1.5 rounded-full ${live ? "anim-pulse bg-ok" : "bg-tx3"}`} />
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
        <ol className="max-h-80 space-y-1.5 overflow-y-auto" aria-live="off">
          {items.map((it) => (
            <li key={it.id} className="anim-slide-in flex gap-2 text-xs">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: TYPE_COLOR[it.type] }} aria-hidden />
              <div className="min-w-0">
                <div className="flex items-center gap-1.5">
                  {it.eventId && (
                    <button onClick={() => onSelect(it.eventId as string)} className="mono font-medium text-tx hover:underline">
                      {it.eventId}
                    </button>
                  )}
                  <span className="text-[10px] uppercase tracking-wide text-tx3">{it.type.replace("_", " ")}</span>
                  <Mono className="ml-auto text-tx3">{new Date(it.at).toLocaleTimeString([], { hour12: false })}</Mono>
                </div>
                <p className="break-words text-tx2">{it.text}</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
