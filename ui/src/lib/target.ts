import { isCustomId, type Trace } from "../api/types";

/** Where an event's calls went (contract 0.2.2 `Trace.orchestration.target`). Judges see these three words, never "twin". */
export type Target = "scored" | "sandbox" | "dry";

export const TARGET_META: Record<Target, { label: string; short: string; color: string; where: string }> = {
  scored: { label: "Scored server", short: "scored", color: "var(--ok)", where: "the organizers' enterprise server, whose action log is scored" },
  sandbox: { label: "Sandbox server", short: "sandbox", color: "var(--cat-compound)", where: "a private sandbox copy of the enterprise server; the scored action log is never touched" },
  dry: { label: "Dry run", short: "dry run", color: "var(--text-3)", where: "an in-process copy, for developers; nothing was sent to a server" },
};

/**
 * The target of an event. Prefer what the trace says. Until a trace carries it: a legacy `twin` transport is a dry run,
 * a custom event (C-nn) is a sandbox run, and every feed event (E-nn) went to the scored server.
 */
export function targetOf(trace: Pick<Trace, "event_id" | "orchestration" | "actions"> | undefined, eventId?: string): Target {
  const said = trace?.orchestration?.target;
  if (said === "scored" || said === "sandbox" || said === "dry") return said;
  if (trace?.actions.some((a) => a.transport === "twin")) return "dry";
  return isCustomId(trace?.event_id ?? eventId ?? "") ? "sandbox" : "scored";
}
