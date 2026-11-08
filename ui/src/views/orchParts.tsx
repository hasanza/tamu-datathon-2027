import { useState } from "react";
import { Disclosure } from "../components/ui/Disclosure";
import type { AgentStep } from "../api/types";
import { clock, offsetMs, usd } from "../lib/format";

/* Small pieces shared by the Timeline cards and the Flow view. */

/** The v2 runtime sets a tool step's text to `name({...args})`: it only repeats the name and arguments the card already shows. */
export const echoesCall = (step: AgentStep) => !!step.tool && step.text.startsWith(`${step.tool}(`);

export const hasKeys = (o: Record<string, unknown> | null | undefined): o is Record<string, unknown> => !!o && Object.keys(o).length > 0;

export function Details({ step }: { step: AgentStep }) {
  const payload = {
    ...(hasKeys(step.args) ? { args: step.args } : {}),
    ...(hasKeys(step.result) ? { result: step.result } : {}),
    ...(hasKeys(step.data) ? { data: step.data } : {}),
    ...(step.model ? { model: step.model } : {}),
    ...(step.cost_usd ? { cost_usd: step.cost_usd } : {}),
    ...(step.transport ? { transport: step.transport } : {}),
  };
  if (Object.keys(payload).length === 0) return null;
  return (
    <Disclosure summary="details" className="mt-1">
      <pre className="mono max-h-60 overflow-auto rounded-md border border-line bg-bg p-2 text-[11px] text-tx2">{JSON.stringify(payload, null, 2)}</pre>
    </Disclosure>
  );
}

/** Time only: the lanes are narrow. Offset, model and cost are in the tooltip. */
export function Meta({ step, start }: { step: AgentStep; start: string }) {
  const tip = [offsetMs(start, step.t), step.model, step.cost_usd ? usd(step.cost_usd) : null].filter(Boolean).join(" · ");
  return (
    <span className="mono text-[10px] text-tx3" title={tip}>
      {clock(step.t)}
    </span>
  );
}

/** Thoughts and hand-off briefs can be long (a task brief is ~450 characters): show a few lines, let the reader expand. */
export function Clamped({ text, italic = false }: { text: string; italic?: boolean }) {
  const [open, setOpen] = useState(false);
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
