import { Fragment, type ReactNode } from "react";

const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

const MONTH = "(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)";
/** What stands out when a trace carries no `brief.entities` (older fixtures): ids and dates. */
const FALLBACK = new RegExp(
  [
    "\\b(?:LOT|CO|PO|SHP|SH|VIN|SUP|CHIP|HARN|D)-?[A-Z0-9][A-Z0-9-]{2,}\\b", // LOT-0130, CO-1042, PO-17, SHP-0182, VIN tokens, dealer ids
    "\\bP_[A-Z]{2}\\b", // plant ids
    "\\b\\d{4}-\\d{2}-\\d{2}\\b", // 2027-03-10
    `\\b${MONTH}\\.? \\d{1,2}(?:, \\d{4})?\\b`, // Feb 23, Mar 26, 2027
    "\\b(?:next|this|last|coming) (?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\\b", // next Tuesday
  ].join("|"),
  "g",
);

/**
 * The text with every entity the agents inferred (plant names, part and lot ids, dates...) in a real <strong>:
 * bold survives without colour. `entities` from `Trace.brief`; without them, ids and dates are found by pattern.
 */
export function Emphasis({ text, entities }: { text: string; entities?: string[] | null }): ReactNode {
  const list = [...new Set((entities ?? []).map((e) => e.trim()).filter((e) => e.length > 1))].sort((a, b) => b.length - a.length);
  const re = list.length > 0 ? new RegExp(list.map(esc).join("|"), "g") : FALLBACK;
  const out: ReactNode[] = [];
  let last = 0;
  re.lastIndex = 0;
  for (let m = re.exec(text); m; m = re.exec(text)) {
    if (m[0] === "") {
      re.lastIndex += 1;
      continue;
    }
    if (m.index > last) out.push(text.slice(last, m.index));
    out.push(<strong key={m.index} className="font-semibold text-tx">{m[0]}</strong>);
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(text.slice(last));
  return <Fragment>{out}</Fragment>;
}
