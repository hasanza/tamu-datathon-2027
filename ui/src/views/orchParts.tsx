import { useState } from "react";
import { Disclosure } from "../components/ui/Disclosure";
import { KVGrid, RawJson } from "../components/ui/KeyValue";
import type { AgentStep } from "../api/types";
import { clock, offsetMs, prettifyRepr } from "../lib/format";

/* Small pieces shared by the Timeline cards and the Flow view. */

/** The v2 runtime sets a tool step's text to `name({...args})`: it only repeats the name and arguments the card already shows. */
export const echoesCall = (step: AgentStep) => !!step.tool && step.text.startsWith(`${step.tool}(`);

export const hasKeys = (o: Record<string, unknown> | null | undefined): o is Record<string, unknown> => !!o && Object.keys(o).length > 0;

export function Details({ step }: { step: AgentStep }) {
  const payload = {
    ...(hasKeys(step.args) ? { args: step.args } : {}),
    ...(hasKeys(step.result) ? { result: step.result } : {}),
    ...(hasKeys(step.data) ? { data: step.data } : {}),
    ...(step.transport ? { transport: step.transport } : {}),
  };
  if (Object.keys(payload).length === 0) return null;
  return (
    <Disclosure summary="details" className="mt-1">
      <KVGrid value={payload} />
      <RawJson value={payload} />
    </Disclosure>
  );
}

/** Time only: the lanes are narrow. The offset is in the tooltip (model and cost are in the Audit tab). */
export function Meta({ step, start }: { step: AgentStep; start: string }) {
  const tip = offsetMs(start, step.t);
  return (
    <span className="mono text-[10px] text-tx3" title={tip}>
      {clock(step.t)}
    </span>
  );
}

/** Thoughts and hand-off briefs can be long (a task brief is ~450 characters): show a few lines, let the reader expand. */
export function Clamped({ text, italic = false }: { text: string; italic?: boolean }) {
  const [open, setOpen] = useState(false);
  text = prettifyRepr(text); // traces from before the pipeline text fix embed dict reprs
  const long = text.length > 170;
  return (
    <>
      <p className={`break-words text-tx2 ${italic ? "italic" : ""} ${open || !long ? "" : "line-clamp-4"}`}>{text}</p>
      {long && (
        <button onClick={() => setOpen(!open)} aria-expanded={open} className="text-[11px] text-tx3 hover:text-tx">
          {open ? "less" : "more"}
        </button>
      )}
    </>
  );
}

export const DECISION_COLOR = (text: string) =>
  /escalat/i.test(text) ? "var(--cat-unconfirmed)" : /correction|fail|reject|violat/i.test(text) ? "var(--warn)" : /valid|passed|executed|ok\b|accept/i.test(text) ? "var(--ok)" : "var(--cat-compound)";
