import { useId, useState } from "react";
import { FlaskConical, Loader2, Send, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useToast } from "../state";

export const MIN_CHARS = 8;
const MAX_CHARS = 2000;

/** Examples that resolve against the real tables (Greensboro / LOT-0330 / Tulsa dealer D10). */
export const EXAMPLES: { label: string; text: string }[] = [
  {
    label: "Plant outage",
    text: "Plant alert: the Greensboro plant (P_NC) lost production to a power failure. Production is stopped from 2027-03-17 through 2027-03-18 inclusive.",
  },
  {
    label: "Quality hold",
    text: "Quality alert: Volt says the heavy-duty wiring harness sent to the Greensboro plant had a moisture contamination. Anything built Thursday Feb 25 through last Monday is suspect.",
  },
  { label: "Noise", text: "Dealer Tulsa, OK asks when the spring service promotion flyer will be available." },
];

/** What the user sees when the sandbox call fails. Exported for tests of the message mapping. */
export function failureMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (e.status === 422) return `That text was rejected: ${e.message}`;
    if (e.status === 404) return `Could not find that event: ${e.message}`;
    if (e.status === 504) return "The pipeline took too long on this event. Try a shorter message.";
    if (e.status === 409) return e.message;
    // The API appends the tail of the pipeline's stderr to a 500 (library warnings, tracebacks): not for a toast.
    if (e.status === 500) return "The pipeline failed on this event. Check the API log for details (is the LLM key set?).";
    if (e.status === 0) return e.message;
    return `Could not run the event (${e.status}): ${e.message}`;
  }
  return e instanceof Error ? e.message : "Could not run the event";
}

/**
 * "Try your own event": the text goes through the same four agents and MCP client as the feed, against a private sandbox
 * copy of the enterprise server (the scored action log is never touched). The request blocks for about a minute or two.
 */
export function CustomEventCard({ onCreated }: { onCreated: (id: string) => void }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  const fieldId = useId();
  const trimmed = text.trim();
  const tooShort = trimmed.length < MIN_CHARS;

  const submit = async () => {
    if (tooShort || busy) return;
    setBusy(true);
    try {
      const r = await api.custom(trimmed);
      await Promise.all([qc.invalidateQueries({ queryKey: ["events"] }), qc.invalidateQueries({ queryKey: ["kpis"] })]);
      toast(`${r.event_id}: ${r.category.replace("_", " ")} (${r.status}). Ran in the sandbox; the scored action log is untouched.`, "ok");
      setText("");
      setOpen(false);
      onCreated(r.event_id);
    } catch (e) {
      toast(failureMessage(e), "error");
    } finally {
      setBusy(false);
    }
  };

  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex w-full items-center gap-2 rounded-lg border border-brand bg-surface-2 px-3 py-2 text-left text-[13px] font-medium text-tx hover:border-brand-bright"
      >
        <FlaskConical size={15} className="shrink-0 text-brand-bright" aria-hidden />
        Try your own event
        <span className="ml-auto text-[11px] font-normal text-tx3">sandbox</span>
      </button>
    );

  return (
    <section aria-label="Try your own event" className="space-y-2 rounded-lg border border-brand bg-surface-2 p-3">
      <div className="flex items-center gap-2">
        <FlaskConical size={15} className="text-brand-bright" aria-hidden />
        <h3 className="text-[13px] font-semibold">Try your own event</h3>
        <button onClick={() => setOpen(false)} disabled={busy} aria-label="Close" className="ml-auto rounded p-0.5 text-tx3 hover:text-tx disabled:opacity-50">
          <X size={14} aria-hidden />
        </button>
      </div>
      <p className="text-[11px] text-tx3">
        Paste an operational message (ops chat, supplier email, dealer note…). It runs through the same four agents and MCP client as the feed,
        against a private sandbox copy of the enterprise server; the scored action log is never touched.
      </p>
      <div className="flex flex-wrap gap-1" role="group" aria-label="Example events">
        {EXAMPLES.map((x) => (
          <button
            key={x.label}
            onClick={() => setText(x.text)}
            disabled={busy}
            className="rounded-md border border-line px-1.5 py-0.5 text-[11px] text-tx2 hover:border-brand-bright hover:text-tx disabled:opacity-50"
          >
            {x.label}
          </button>
        ))}
      </div>
      <label htmlFor={fieldId} className="sr-only">
        Event text
      </label>
      <textarea
        id={fieldId}
        value={text}
        onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
        onKeyDown={(e) => {
          if ((e.metaKey || e.ctrlKey) && e.key === "Enter") void submit();
        }}
        disabled={busy}
        rows={5}
        placeholder="e.g. The Huntsville line is down next Wednesday for a software fix."
        className="w-full resize-y rounded-md border border-line bg-bg px-2 py-1.5 text-[13px] text-tx placeholder:text-tx3 disabled:opacity-60"
      />
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-tx3" aria-live="polite">
          {tooShort ? `${MIN_CHARS - trimmed.length} more characters needed` : `${trimmed.length}/${MAX_CHARS}`}
        </span>
        <button
          onClick={() => void submit()}
          disabled={tooShort || busy}
          className="ml-auto inline-flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-[13px] font-medium text-white hover:bg-brand-bright disabled:opacity-60"
        >
          {busy ? <Loader2 size={14} className="animate-spin" aria-hidden /> : <Send size={14} aria-hidden />}
          {busy ? "Running the pipeline…" : "Submit"}
        </button>
      </div>
      {busy && <p className="text-[11px] text-tx3">This can take a minute or two: the four agents read, plan, pre-flight check, audit and execute against the sandbox server.</p>}
    </section>
  );
}
