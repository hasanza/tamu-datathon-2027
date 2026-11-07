import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
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

  useEffect(() => {
    let es: EventSource | null = null;
    let timer: number | undefined;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      es = new EventSource(`/api/stream${replay ? "?replay=true" : ""}`);
      es.onopen = () => {
        attempt = 0;
        setLive(true);
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
            void qc.invalidateQueries({ queryKey: ["trace", eventId] });
            void qc.invalidateQueries({ queryKey: ["graph", eventId] });
            void qc.invalidateQueries({ queryKey: ["actions", eventId] });
          }
          void qc.invalidateQueries({ queryKey: ["events"] });
          void qc.invalidateQueries({ queryKey: ["kpis"] });
        });
      }
    };
    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      es?.close();
    };
  }, [qc, replay]);

  const clear = useCallback(() => setItems([]), []);
  return { live, items, processing, recent, replay, setReplay, clear };
}
