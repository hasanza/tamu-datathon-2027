import { customNumber, type FeedEvent, type Trace } from "../api/types";

/** "What would make it actionable": the human question the escalation carries (or the blocking ambiguities). */
export function confirmClause(t: Trace): string | null {
  const esc = t.actions.find((a) => a.tool === "escalate");
  const reason = typeof esc?.args.reason === "string" ? esc.args.reason : "";
  const m = /Please confirm:\s*(.*?)\.\s*(?:No operational|$)/s.exec(reason);
  if (m?.[1]) return m[1];
  const blocking = t.incidents.flatMap((i) => i.ambiguities.filter((a) => a.blocking).map((a) => a.issue));
  return blocking.length ? `Resolve: ${blocking.join("; ")}` : null;
}

/** Latest on top: judge input (C-nn) first, highest number first; the preset events keep E-01..E-15 order. */
export function newestFirst<T extends { event_id: string }>(a: T, b: T): number {
  const ca = customNumber(a.event_id);
  const cb = customNumber(b.event_id);
  if (ca || cb) return ca && cb ? cb - ca : ca ? -1 : 1;
  return a.event_id.localeCompare(b.event_id);
}

/** Follow-ups of an event (custom rows whose parent_id matches), newest first. */
export const followUpsOf = (events: FeedEvent[] | undefined, parentId: string): FeedEvent[] =>
  (events ?? []).filter((e) => e.parent_id === parentId).sort(newestFirst);

/** Navigate to an event from anywhere (the hash router picks it up). */
export const openEvent = (id: string) => {
  window.location.hash = `/${id}`;
};
