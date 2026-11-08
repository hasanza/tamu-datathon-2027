import { useState } from "react";
import { CheckCircle2, MinusCircle, XCircle } from "lucide-react";
import { WRITE_TOOLS, type Trace } from "../api/types";
import { Disclosure } from "../components/ui/Disclosure";
import { Chip, Mono, Panel } from "../components/ui/primitives";
import { usd } from "../lib/format";
import { TARGET_META, targetOf, type Target } from "../lib/target";
import { STEP_META } from "../lib/meta";

type Verdict = "pass" | "fail" | "na";
interface Check {
  rule: string;
  detail: string;
  verdict: Verdict;
}

function checks(t: Trace, target: Target): Check[] {
  const writes = t.actions.filter((a) => WRITE_TOOLS.has(a.tool));
  const unrehearsed = writes.filter((a) => a.rehearsal?.ok !== true);
  const accepted = t.actions.filter((a) => a.result?.ok === true); // a missing result is not an acceptance
  // a skipped call never ran (an earlier write of its incident failed): count it apart from real failures
  const skipped = t.actions.filter((a) => a.skipped);
  // unknown = transport failure (outcome is not a server rejection, and the write may have happened)
  const unknown = t.actions.filter((a) => a.result?.outcome === "unknown" && !a.skipped);
  const failed = t.actions.filter((a) => a.result && !a.result.ok && !a.skipped && a.result.outcome !== "unknown");
  const noResult = t.actions.length - accepted.length - failed.length - skipped.length - unknown.length;
  const who = TARGET_META[target].label; // "Scored server" | "Sandbox server" | "Dry run"
  const distinctWrites = new Set(writes.map((a) => a.tool)).size;
  const out: Check[] = [
    {
      rule: "Pre-flight check before any write",
      detail: writes.length ? `${writes.length - unrehearsed.length}/${writes.length} write calls were rehearsed ok on a sandbox copy of the enterprise` : "no write calls",
      verdict: writes.length === 0 ? "na" : unrehearsed.length === 0 ? "pass" : "fail",
    },
    {
      rule: `${who} accepted every call`,
      detail: t.actions.length
        ? `${accepted.length}/${t.actions.length} calls returned ok${failed.length ? `, ${failed.length} failed` : ""}${unknown.length ? `, ${unknown.length} unknown (transport failure)` : ""}${skipped.length ? `, ${skipped.length} skipped after a failure (no retry)` : ""}${noResult ? ` (${noResult} without a result)` : ""}`
        : "no calls",
      verdict: t.actions.length === 0 ? "na" : failed.length > 0 || skipped.length > 0 || unknown.length > 0 ? "fail" : noResult > 0 ? "na" : "pass",
    },
  ];
  const byTransport = t.actions.reduce<Record<string, number>>((acc, a) => (a.transport ? { ...acc, [a.transport]: (acc[a.transport] ?? 0) + 1 } : acc), {});
  if (Object.keys(byTransport).length > 0) {
    out.push({
      rule: "Execution transport",
      detail: Object.entries(byTransport).map(([k, n]) => `${n} via ${k}`).join(", ") + ` (mcp/stdio is the MCP client; target: ${TARGET_META[target].label.toLowerCase()}, ${TARGET_META[target].where})`,
      verdict: "na",
    });
  }
  if (t.status === "escalated" || t.status === "noise") {
    out.push({
      rule: `${t.status === "noise" ? "Noise" : "Escalated"} events change nothing`,
      detail: writes.length === 0 ? "no write tool was called" : `${writes.length} write calls found`,
      verdict: writes.length === 0 ? "pass" : "fail",
    });
  }
  if (t.status === "done") {
    out.push({
      rule: "Acted events use the full playbook",
      detail: `${distinctWrites} distinct write tools used (contract: at least 3)`,
      verdict: distinctWrites >= 3 ? "pass" : "fail",
    });
  }
  return out;
}

const V_ICON = { pass: CheckCircle2, fail: XCircle, na: MinusCircle };
const V_COLOR = { pass: "var(--ok)", fail: "var(--fail)", na: "var(--text-3)" };

function ChipList({ items, limit = 40 }: { items: string[]; limit?: number }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, limit);
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map((i) => (
        <span key={i} className="mono rounded-md border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] text-tx2">{i}</span>
      ))}
      {items.length > limit && (
        <button onClick={() => setAll(!all)} className="rounded-md border border-line px-1.5 py-0.5 text-[11px] text-tx3 hover:text-tx">
          {all ? "show less" : `+${items.length - limit} more`}
        </button>
      )}
    </div>
  );
}

/** One piece of the world diff behind a trigger that carries its count ("Show 9 moved production orders"). Zero is one line. */
function DiffSection({ noun, count, children }: { noun: string; count: number; children: React.ReactNode }) {
  if (count === 0) return <p data-diff-section={noun} data-count={0} className="text-xs text-tx3">No {noun}.</p>;
  return (
    <div data-diff-section={noun} data-count={count}>
      <Disclosure summary={`Show ${count} ${noun}`}>{children}</Disclosure>
    </div>
  );
}

function DealerRow({ id, orders }: { id: string; orders: string[] }) {
  return (
    <li className="rounded-md border border-line bg-surface-2 px-2 py-1">
      <Disclosure summary={<Mono className="font-medium text-tx">{id}</Mono>} count={orders.length}>
        <ChipList items={orders} />
      </Disclosure>
    </li>
  );
}

export function AuditTab({ trace }: { trace: Trace }) {
  const d = trace.world_diff;
  const target = targetOf(trace);
  const cs = checks(trace, target);
  const gateSteps = trace.agents.flatMap((a) => a.steps.filter((s) => ["rehearse", "audit", "gate", "execute"].includes(s.kind)).map((s) => ({ agent: a.agent, s })));
  const calls = trace.llm.calls;
  return (
    <div className="space-y-4">
      <Panel title="Guardrails and rehearsal">
        <ul className="space-y-1.5">
          {cs.map((c) => {
            const I = V_ICON[c.verdict];
            return (
              <li key={c.rule} className="flex items-start gap-2 text-[13px]">
                <I size={16} className="mt-0.5 shrink-0" style={{ color: V_COLOR[c.verdict] }} aria-label={c.verdict} />
                <div>
                  <span className="font-medium text-tx">{c.rule}</span>
                  <span className="text-tx3"> · {c.detail}</span>
                </div>
              </li>
            );
          })}
        </ul>
        {gateSteps.length > 0 && (
          <Disclosure summary={`Show ${gateSteps.length} check step${gateSteps.length === 1 ? "" : "s"}`} className="mt-3 border-t border-line pt-3">
          <ul className="space-y-1">
            {gateSteps.map(({ agent, s }, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-2 text-xs">
                <Chip color={STEP_META[s.kind].color}>{STEP_META[s.kind].label}</Chip>
                <span className="text-tx3">{agent}</span>
                <span className="text-tx2">{s.text}</span>
              </li>
            ))}
          </ul>
          </Disclosure>
        )}
      </Panel>

      <Panel title="World diff: what changed">
        <div className="space-y-4">
          <DiffSection noun="moved production orders" count={d.moved_pos.length}>
            <div className="scroll-shadow-y max-h-72 overflow-auto rounded-md border border-line">
              <table className="w-full text-left text-[13px]">
                <thead className="sticky top-0 bg-surface-2 text-[11px] uppercase tracking-wide text-tx3">
                  <tr>
                    <th className="px-2 py-1.5">PO</th>
                    <th className="px-2 py-1.5">Kind</th>
                    <th className="px-2 py-1.5">From</th>
                    <th className="px-2 py-1.5">To</th>
                  </tr>
                </thead>
                <tbody>
                  {d.moved_pos.map((m) => (
                    <tr key={m.production_order_id} className="border-t border-line">
                      <td className="px-2 py-1"><Mono>{m.production_order_id}</Mono></td>
                      <td className="px-2 py-1"><Chip color={m.kind === "transfer" ? "var(--cat-outage)" : "var(--cat-delay)"}>{m.kind}</Chip></td>
                      <td className="px-2 py-1"><Mono>{m.from_plant} · {m.from_date}</Mono></td>
                      <td className="px-2 py-1"><Mono>{m.to_plant} · {m.to_date}</Mono></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </DiffSection>
          <DiffSection noun="notified dealers" count={d.notified_dealers.length}>
            <ul className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
              {d.notified_dealers.map((n) => (
                <DealerRow key={n.dealer_id} id={n.dealer_id} orders={n.customer_order_ids} />
              ))}
            </ul>
          </DiffSection>
          <DiffSection noun="loaner assignments" count={d.loaners.length}><ChipList items={d.loaners} /></DiffSection>
          <DiffSection noun="held lots" count={d.held_lots.length}><ChipList items={d.held_lots} /></DiffSection>
          <DiffSection noun="stopped VINs" count={d.stopped_vins.length}><ChipList items={d.stopped_vins} /></DiffSection>
          <DiffSection noun="contacted customers" count={d.contacted_customers.length}><ChipList items={d.contacted_customers} /></DiffSection>
        </div>
      </Panel>

      <Panel
        title="LLM usage"
        action={<span className="mono text-[11px] text-tx3">{calls.length} calls · {usd(trace.llm.total_cost_usd)} · pipeline v{trace.pipeline_version}</span>}
      >
        {calls.length === 0 ? (
          <p className="text-xs text-tx3">No model calls were made for this event (everything was decided by code).</p>
        ) : (
          <Disclosure summary="Show the model calls" count={calls.length}>
          <div className="scroll-shadow-x overflow-x-auto">
            <table className="w-full text-left text-[13px]">
              <thead className="bg-surface-2 text-[11px] uppercase tracking-wide text-tx3">
                <tr>
                  <th className="px-2 py-1.5">Purpose</th>
                  <th className="px-2 py-1.5">Model</th>
                  <th className="px-2 py-1.5 text-right">Input tok</th>
                  <th className="px-2 py-1.5 text-right">Output tok</th>
                  <th className="px-2 py-1.5 text-right">Cost</th>
                  <th className="px-2 py-1.5">Cache</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c, i) => (
                  <tr key={i} className="border-t border-line">
                    <td className="px-2 py-1.5">{c.purpose}</td>
                    <td className="px-2 py-1.5"><Mono>{c.provider}/{c.model}</Mono></td>
                    <td className="mono px-2 py-1.5 text-right">{c.input_tokens}</td>
                    <td className="mono px-2 py-1.5 text-right">{c.output_tokens}</td>
                    <td className="mono px-2 py-1.5 text-right">{usd(c.cost_usd)}</td>
                    <td className="px-2 py-1.5">{c.cached ? <Chip color="var(--cat-unconfirmed)">cached</Chip> : <Chip color="var(--ok)">live</Chip>}</td>
                  </tr>
                ))}
                <tr className="border-t border-line bg-surface-2 font-medium">
                  <td className="px-2 py-1.5" colSpan={2}>Total</td>
                  <td className="mono px-2 py-1.5 text-right">{calls.reduce((s, c) => s + c.input_tokens, 0)}</td>
                  <td className="mono px-2 py-1.5 text-right">{calls.reduce((s, c) => s + c.output_tokens, 0)}</td>
                  <td className="mono px-2 py-1.5 text-right">{usd(trace.llm.total_cost_usd)}</td>
                  <td />
                </tr>
              </tbody>
            </table>
          </div>
          </Disclosure>
        )}
      </Panel>
    </div>
  );
}
