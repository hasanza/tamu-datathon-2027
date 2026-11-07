import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useRunStatus } from "./hooks";
import type { StreamType } from "./types";

export interface ActivityItem {
  id: number;
  at: number;
  type: StreamType;
  eventId: string | null;
  text: string;
  payload: Record<string, unknown>;
}

const TYPES: StreamType[] = ["event_received", "agent_step", "action", "event_done"];
const MAX_ITEMS = 150;

function describe(type: StreamType, p: Record<string, unknown>): string {
  const s = (k: string) => (typeof p[k] === "string" ? (p[k] as string) : null);
  switch (type) {
    case "event_received":
      return `Received${s("source") ? ` via ${s("source")}` : ""}${s("text") ? `: ${s("text")}` : ""}`;
    case "agent_step": {
      const who = s("agent");
      const step = (p.step ?? p) as Record<string, unknown>;
      const kind = typeof step.kind === "string" ? step.kind : null;
      const text = typeof step.text === "string" ? step.text : null;
      return [who, kind && `[${kind}]`, text].filter(Boolean).join(" ") || "Agent step";
    }
    case "action": {
      const a = (p.action ?? p) as Record<string, unknown>;
      const tool = typeof a.tool === "string" ? a.tool : null;
      const ok = (a.result as { ok?: boolean } | null | undefined)?.ok;
      return `${tool ?? "action"}${ok === false ? " FAILED" : ok === true ? " ok" : ""}`;
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

  // SSE can miss lines (reconnect starts at the end of the file). When the API says a run has finished,
  // re-read everything so no event is left "processing" or "queued".
  const running = useRunStatus().data?.running;
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && running === false) {
      setProcessing(new Set());
      void qc.invalidateQueries();
    }
    if (running !== undefined) wasRunning.current = running;
  }, [running, qc]);

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
          const id = (seq.current += 1);
          setItems((prev) =>
            [{ id, at: Date.now(), type, eventId, text: describe(type, payload), payload }, ...prev].slice(
              0,
              MAX_ITEMS,
            ),
          );
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

  const clear = useCallback(() => setItems([]), []);
  return { live, items, processing, recent, replay, setReplay, clear };
}
