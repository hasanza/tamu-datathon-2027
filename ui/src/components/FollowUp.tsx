import { useId, useState } from "react";
import { CornerDownRight, FlaskConical, Loader2, RotateCw } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../api/client";
import { useEvents, useTraces } from "../api/hooks";
import type { Trace } from "../api/types";
import { confirmClause, followUpsOf, openEvent } from "../lib/escalation";
import { clip } from "../lib/format";
import { useToast } from "../state";
import { failureMessage } from "./CustomEventCard";
import { CategoryBadge, Mono, StatusChip } from "./ui/primitives";

export const MIN_DETAILS = 4;
const MAX_DETAILS = 1000;

/**
 * "Add details and re-run" for an escalated event. The operator adds what the escalation asked for; the API appends
 * it to the original text and runs the whole pipeline again against a private sandbox copy of the enterprise server (the same
 * mechanism as "Try your own event"). It never touches the scored action log.
 */
export function FollowUpControl({ trace }: { trace: Trace }) {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  const fieldId = useId();
  const need = confirmClause(trace);
  const trimmed = details.trim();
  const tooShort = trimmed.length < MIN_DETAILS;

  const submit = async () => {
    if (tooShort || busy) return;
    setBusy(true);
    try {
      const r = await api.followUp(trace.event_id, trimmed);
      await Promise.all([qc.invalidateQueries({ queryKey: ["events"] }), qc.invalidateQueries({ queryKey: ["kpis"] })]);
      toast(`${r.event_id}: ${r.category.replace("_", " ")} (${r.status}). Follow-up to ${trace.event_id}, re-run in the sandbox.`, "ok");
      setDetails("");
      setOpen(false);
      openEvent(r.event_id);
    } catch (e) {
      toast(failureMessage(e), "error"); // the text stays in the box so it can be retried
    } finally {
      setBusy(false);
    }
  };

  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className="mt-2 inline-flex items-center gap-1.5 rounded-md border border-brand px-2 py-1 text-xs font-medium text-tx hover:border-brand-bright"
      >
        <RotateCw size={13} className="text-brand-bright" aria-hidden /> Add details and re-run
      </button>
    );

  return (
    <div className="mt-2 space-y-1.5 rounded-md border border-brand bg-surface p-2">
      <label htmlFor={fieldId} className="block text-[11px] text-tx3">
        {need ? (
          <>
            What would make this actionable: <span className="text-tx2">{need}</span>
          </>
        ) : (
          "Add what the escalation is missing (part, lot or shipment, plant, dates)."
        )}
      </label>
      <textarea
        id={fieldId}
        value={details}
        onChange={(e) => setDetails(e.target.value.slice(0, MAX_DETAILS))}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void submit();
        }}
        disabled={busy}
        rows={3}
        placeholder="e.g. It is shipment SH-0190 of the infotainment chip to Princeton, now due Fri Mar 19 instead of Mar 15."
        className="w-full resize-y rounded-md border border-line bg-bg px-2 py-1.5 text-[13px] text-tx placeholder:text-tx3 disabled:opacity-60"
      />
      <p className="flex items-center gap-1 text-[11px] text-tx3">
        <FlaskConical size={11} aria-hidden /> Re-runs in the sandbox: a private copy of the enterprise server; the scored action log is never touched.
      </p>
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-tx3" aria-live="polite">
          {tooShort ? `${MIN_DETAILS - trimmed.length} more characters needed` : `${trimmed.length}/${MAX_DETAILS}`}
        </span>
        <button
          onClick={() => setOpen(false)}
          disabled={busy}
          className="ml-auto rounded-md border border-line px-2 py-1 text-xs text-tx2 hover:text-tx disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          onClick={() => void submit()}
          disabled={tooShort || busy}
          className="inline-flex items-center gap-1.5 rounded-md bg-brand px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-bright disabled:opacity-60"
        >
          {busy ? <Loader2 size={13} className="animate-spin" aria-hidden /> : <RotateCw size={13} aria-hidden />}
          {busy ? "Re-running…" : "Re-run"}
        </button>
      </div>
    </div>
  );
}

/** Follow-ups under an escalation: custom events created from it, newest first. */
export function FollowUpList({ parentId }: { parentId: string }) {
  const events = useEvents().data;
  const rows = followUpsOf(events, parentId);
  const { traces } = useTraces(rows.map((r) => r.event_id));
  if (rows.length === 0) return null;
  const summary = (id: string) => traces.find((t) => t.event_id === id)?.summary;
  return (
    <div className="mt-2">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-tx3">
        <CornerDownRight size={12} aria-hidden /> Follow-ups ({rows.length})
      </div>
      <p className="text-[11px] text-tx3">Re-run in the sandbox: a private copy of the enterprise server; the scored action log was not touched.</p>
      <ul className="mt-1 space-y-1">
        {rows.map((r) => (
          <li key={r.event_id}>
            <button
              onClick={() => openEvent(r.event_id)}
              className="w-full rounded-md border border-line bg-surface px-2 py-1.5 text-left hover:border-brand-bright"
            >
              <span className="flex flex-wrap items-center gap-1.5">
                <Mono className="font-medium text-tx">{r.event_id}</Mono>
                <StatusChip status={r.status} />
                <CategoryBadge category={r.category} />
              </span>
              {summary(r.event_id) && <span className="mt-1 block text-xs text-tx2">{clip(summary(r.event_id) as string, 160)}</span>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
