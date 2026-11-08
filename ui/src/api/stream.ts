import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRunStatus } from "./hooks";
import { prettifyRepr, summarize } from "../lib/format";
import { emitTour } from "../lib/tour";
import { useToast } from "../state";
import { firstSentence } from "../lib/flow";
import { isCustomId, type AgentId, type AgentStep, type FeedEvent, type StepKind, type StreamType, type Transport } from "./types";

export interface ActivityItem {
  id: number;
  at: number;
  type: StreamType;
  eventId: string | null;
  text: string;
  payload: Record<string, unknown>;
}

/** An agent step received over SSE while an event is still running (its trace does not exist yet). */
export type LiveStep = AgentStep & { agent: AgentId; id: number };
const MAX_LIVE_STEPS = 800;

const str = (v: unknown) => (typeof v === "string" ? v : null);
/** agent_step payloads carry the step either flat or under `step`, with v2 fields (turn, tool, args, result, transport, ...). */
export function toLiveStep(p: Record<string, unknown>, id: number): LiveStep | null {
  const s = (typeof p.step === "object" && p.step ? p.step : p) as Record<string, unknown>;
  const agent = str(p.agent) ?? str(s.agent);
  const kind = str(s.kind);
  const text = str(s.text);
  if (!agent || !kind || text === null) return null;
  const obj = (v: unknown) => (typeof v === "object" && v && !Array.isArray(v) ? (v as Record<string, unknown>) : null);
  return {
    id,
    agent: agent as AgentId,
    t: str(s.t) ?? new Date().toISOString(),
    kind: kind as StepKind,
    text,
    data: obj(s.data),
    task: str(s.task),
    turn: typeof s.turn === "number" ? s.turn : null,
    tool: str(s.tool),
    args: obj(s.args),
    result: obj(s.result),
    to_agent: str(s.to_agent) as AgentId | null,
    from_agent: str(s.from_agent) as AgentId | null,
    transport: str(s.transport) as Transport | null,
    model: str(s.model),
    cost_usd: typeof s.cost_usd === "number" ? s.cost_usd : null,
  };
}

const TYPES: StreamType[] = ["event_incoming", "event_received", "agent_step", "action", "event_done"];
/** How long an "Incoming event..." row waits for its event before it is dropped. */
const INCOMING_TTL_MS = 15000;
const MAX_ITEMS = 150;

const hasObj = (o: Record<string, unknown> | null | undefined): o is Record<string, unknown> => !!o && Object.keys(o).length > 0;

/** One plain sentence for a step, built from its structured fields (never the raw `name({json})` text of a tool call). */
export function stepSentence(step: AgentStep): string {
  if (step.kind === "tool" && step.tool) {
    const args = hasObj(step.args) ? ` - ${summarize(step.args)}` : "";
    const result = hasObj(step.result) ? ` -> ${summarize(step.result)}` : "";
    return `${step.tool}${args}${result}`;
  }
  if (step.kind === "message") {
    const route = [step.from_agent, step.to_agent].filter(Boolean).join(" -> ");
    return `${route}${step.task ? ` - ${step.task}` : ""}: ${firstSentence(step.text)}`;
  }
  if (step.kind === "thought") return firstSentence(step.text);
  return prettifyRepr(step.text);
}

function describe(type: StreamType, p: Record<string, unknown>): string {
  const s = (k: string) => (typeof p[k] === "string" ? (p[k] as string) : null);
  switch (type) {
    case "event_incoming":
      return "Incoming event";
    case "event_received":
      return `Received${s("source") ? ` via ${s("source")}` : ""}${s("text") ? `: ${s("text")}` : ""}`;
    case "agent_step": {
      const live = toLiveStep(p, 0);
      return live ? `${live.agent} ${stepSentence(live)}` : "Agent step";
    }
    case "action": {
      const a = (p.action ?? p) as Record<string, unknown>;
      const tool = typeof a.tool === "string" ? a.tool : null;
      const args = typeof a.args === "object" && a.args && !Array.isArray(a.args) ? summarize(a.args as Record<string, unknown>) : "";
      const ok = (a.result as { ok?: boolean } | null | undefined)?.ok;
      return `${tool ?? "action"}${args ? ` - ${args}` : ""}${ok === false ? " FAILED" : ok === true ? " ok" : ""}`;
    }
    case "event_done":
      return `Done${s("status") ? `: ${s("status")}` : ""}${s("summary") ? ` - ${s("summary")}` : ""}`;
  }
}

/**
 * Reconnecting EventSource on /api/stream. On every message it invalidates the cached queries
 * for the affected event. Returns the live flag, the activity log and the set of event ids currently processing.
 */
export function useLiveStream() {
  const qc = useQueryClient();
  const [live, setLive] = useState(false);
  const [items, setItems] = useState<ActivityItem[]>([]);
  const [processing, setProcessing] = useState<Set<string>>(new Set());
  const [recent, setRecent] = useState<Record<string, number>>({}); // event id -> last update ms (row flash)
  const [replay, setReplay] = useState(false);
  const seq = useRef(0);
  // A custom (sandbox) event only shows up in /api/events once its trace exists, i.e. when it is done. While it runs
  // (5-10 s) the stream is the only place that knows about it, so keep a placeholder row for the feed.
  const [liveSteps, setLiveSteps] = useState<Record<string, LiveStep[]>>({}); // event id -> steps so far
  const [pendingCustom, setPendingCustom] = useState<Record<string, FeedEvent & { at: number }>>({});

  // SSE can miss lines (reconnect starts at the end of the file). When the API says a run has finished,
  // re-read everything so no event is left "processing" or "queued".
  const runStatus = useRunStatus().data;
  const running = runStatus?.running;
  const wasRunning = useRef(false);
  const toast = useToast();
  // feed events finished in the current run (the header's "event 7 of 15"): reset when a new run starts
  const [incoming, setIncoming] = useState<Record<string, number>>({}); // event id -> when its "incoming" notice arrived
  const [finished, setFinished] = useState<Set<string>>(new Set());
  const finishedRef = useRef(0);
  finishedRef.current = finished.size;
  const startedAt = runStatus?.started ?? null;
  useEffect(() => setFinished(new Set()), [startedAt]);
  useEffect(() => {
    if (wasRunning.current && running === false) {
      setProcessing(new Set());
      void qc.invalidateQueries();
      if (runStatus?.state === "done") {
        const total = (qc.getQueryData<FeedEvent[]>(["events"]) ?? []).filter((e) => !e.custom).length || 15;
        toast(`Run finished: ${Math.max(finishedRef.current, 0)}/${total}`, "ok");
      }
    }
    if (running !== undefined) wasRunning.current = running;
  }, [running, runStatus?.state, qc, toast]);

  useEffect(() => {
    let es: EventSource | null = null;
    let timer: number | undefined;
    let attempt = 0;
    let closed = false;
    let opened = false;

    // A run emits ~50 messages a second. Invalidating per message cancels the read in flight and starts another, so no
    // read ever completes and the screen stays stale until the 15 s poll. Collect keys and flush them once per tick;
    // never cancel a read that is already running (the next tick picks up anything newer).
    const pending = new Map<string, readonly unknown[]>();
    let flushTimer: number | undefined;
    const flush = () => {
      window.clearTimeout(flushTimer);
      flushTimer = undefined;
      for (const key of pending.values()) void qc.invalidateQueries({ queryKey: key }, { cancelRefetch: false });
      pending.clear();
    };
    const refresh = (key: readonly unknown[], now = false) => {
      pending.set(JSON.stringify(key), key);
      if (now) flush();
      else if (flushTimer === undefined) flushTimer = window.setTimeout(flush, 400);
    };

    const connect = () => {
      // A replay stream starts from line 1 on every (re)connect: start the log empty so history is never appended twice.
      if (replay) setItems([]);
      es = new EventSource(`/api/stream${replay ? "?replay=true" : ""}`);
      es.onopen = () => {
        attempt = 0;
        setLive(true);
        if (opened) {
          // Reconnected: lines written while we were away are gone. Rebuild the picture from the API.
          setProcessing(new Set());
          void qc.invalidateQueries();
        }
        opened = true;
      };
      es.onerror = () => {
        setLive(false);
        es?.close();
        if (!closed) {
          attempt += 1;
          timer = window.setTimeout(connect, Math.min(1000 * 2 ** attempt, 15000));
        }
      };
      for (const type of TYPES) {
        es.addEventListener(type, (msg) => {
          let payload: Record<string, unknown> = {};
          try {
            payload = JSON.parse((msg as MessageEvent<string>).data) as Record<string, unknown>;
          } catch {
            /* keep empty payload */
          }
          const eventId = typeof payload.event_id === "string" ? payload.event_id : null;
          if (type === "event_incoming") {
            // the event is about to arrive (about a second ahead): the feed shows an "Incoming event..." row, nothing else changes
            if (eventId) {
              setIncoming((m) => ({ ...m, [eventId]: Date.now() }));
              window.setTimeout(() => setIncoming((m) => (eventId in m ? Object.fromEntries(Object.entries(m).filter(([k]) => k !== eventId)) : m)), INCOMING_TTL_MS);
            }
            return;
          }
          if (eventId && type === "event_received") setIncoming((m) => (eventId in m ? Object.fromEntries(Object.entries(m).filter(([k]) => k !== eventId)) : m));
          const id = (seq.current += 1);
          setItems((prev) =>
            [{ id, at: Date.now(), type, eventId, text: describe(type, payload), payload }, ...prev].slice(
              0,
              MAX_ITEMS,
            ),
          );
          if (eventId && type === "event_received") emitTour("event-received", { id: eventId });
          if (eventId && type === "event_done") emitTour("event-done", { id: eventId, status: typeof payload.status === "string" ? payload.status : undefined });
          if (eventId && type === "event_done" && !isCustomId(eventId)) setFinished((s) => new Set(s).add(eventId));
          if (eventId && type === "event_received") setLiveSteps((m) => ({ ...m, [eventId]: [] })); // a new run of this event
          if (eventId && type === "agent_step") {
            const step = toLiveStep(payload, id);
            if (step) setLiveSteps((m) => ({ ...m, [eventId]: [...(m[eventId] ?? []), step].slice(-MAX_LIVE_STEPS) }));
          }
          if (eventId && isCustomId(eventId)) {
            if (type === "event_received") {
              const source = typeof payload.source === "string" ? payload.source : "judge input";
              setPendingCustom((p) => ({
                ...p,
                [eventId]: {
                  event_id: eventId,
                  received_at: typeof payload.received_at === "string" ? payload.received_at : new Date().toISOString(),
                  source,
                  text: typeof payload.text === "string" ? payload.text : "",
                  status: "processing",
                  category: null,
                  confidence: null,
                  custom: true,
                  parent_id: /^follow-up to ([EC]-\d{2})$/.exec(source)?.[1] ?? null,
                  at: Date.now(),
                },
              }));
            } else if (type === "event_done") {
              // the real row arrives with the events refresh that event_done triggers right below
              window.setTimeout(() => setPendingCustom((p) => Object.fromEntries(Object.entries(p).filter(([k]) => k !== eventId))), 1500);
            }
          }
          if (eventId) {
            setRecent((r) => ({ ...r, [eventId]: Date.now() }));
            setProcessing((s) => {
              const n = new Set(s);
              if (type === "event_done") n.delete(eventId);
              else n.add(eventId);
              return n;
            });
            const done = type === "event_done";
            const keys = [["trace", eventId], ["graph", eventId], ["actions", eventId]] as const;
            if (done) {
              // A trace read started before the trace was written may still be in flight (and end in a 404): drop it, then re-read.
              void qc.cancelQueries({ queryKey: ["trace", eventId] }).then(() => {
                for (const k of keys) refresh(k, false);
                refresh(["events"], true);
                refresh(["kpis"], true);
              });
              return;
            }
            for (const k of keys) refresh(k);
          }
          refresh(["events"]);
          refresh(["kpis"]);
        });
      }
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      window.clearTimeout(flushTimer);
      es?.close();
    };
  }, [qc, replay]);

  // A custom run that never reports event_done (killed API, restart) must not stay "processing" forever.
  useEffect(() => {
    const t = window.setInterval(() => {
      const cutoff = Date.now() - 180_000;
      setPendingCustom((p) => {
        const stale = Object.keys(p).filter((k) => (p[k]?.at ?? 0) < cutoff);
        if (stale.length === 0) return p;
        setProcessing((s) => new Set([...s].filter((id) => !stale.includes(id))));
        return Object.fromEntries(Object.entries(p).filter(([k]) => !stale.includes(k)));
      });
    }, 15_000);
    return () => window.clearInterval(t);
  }, []);

  const clear = useCallback(() => setItems([]), []);
  /** "Reset everything": the Activity log, the steps of events in flight and the judge placeholders all go. */
  const clearAll = useCallback(() => {
    setItems([]);
    setLiveSteps({});
    setPendingCustom({});
    setIncoming({});
    setRecent({});
    setProcessing(new Set());
    setFinished(new Set());
  }, []);
  return { live, items, processing, recent, replay, setReplay, clear, clearAll, liveSteps, incoming: Object.keys(incoming), finished: finished.size, pendingCustom: Object.values(pendingCustom) };
}
