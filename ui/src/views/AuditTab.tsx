import { useState } from "react";
import { CheckCircle2, ChevronDown, ChevronRight, MinusCircle, XCircle } from "lucide-react";
import { useExecTarget } from "../api/hooks";
import { WRITE_TOOLS, type Trace } from "../api/types";
import { Chip, Mono, Panel, Stat } from "../components/ui/primitives";
import { usd } from "../lib/format";
import { STEP_META } from "../lib/meta";

type Verdict = "pass" | "fail" | "na";
interface Check {
  rule: string;
  detail: string;
  verdict: Verdict;
}

function checks(t: Trace, target: "twin" | "server"): Check[] {
  const writes = t.actions.filter((a) => WRITE_TOOLS.has(a.tool));
  const unrehearsed = writes.filter((a) => a.rehearsal?.ok !== true);
  const accepted = t.actions.filter((a) => a.result?.ok === true); // a missing result is not an acceptance
  // a skipped call never ran (an earlier write of its incident failed): count it apart from real failures
  const skipped = t.actions.filter((a) => a.skipped);
  const failed = t.actions.filter((a) => a.result && !a.result.ok && !a.skipped);
  const noResult = t.actions.length - accepted.length - failed.length - skipped.length;
  const who = target === "twin" ? "Twin" : "Server";
  const distinctWrites = new Set(writes.map((a) => a.tool)).size;
  const out: Check[] = [
    {
      rule: "Twin rehearsal before any write",
      detail: writes.length ? `${writes.length - unrehearsed.length}/${writes.length} write calls were rehearsed ok on the in-process twin` : "no write calls",
      verdict: writes.length === 0 ? "na" : unrehearsed.length === 0 ? "pass" : "fail",
    },
    {
      rule: `${who} accepted every call`,
      detail: t.actions.length
        ? `${accepted.length}/${t.actions.length} calls returned ok${failed.length ? `, ${failed.length} failed` : ""}${skipped.length ? `, ${skipped.length} skipped after a failure (no retry)` : ""}${noResult ? ` (${noResult} without a result)` : ""}`
        : "no calls",
      verdict: t.actions.length === 0 ? "na" : failed.length > 0 || skipped.length > 0 ? "fail" : noResult > 0 ? "na" : "pass",
    },
  ];
  const byTransport = t.actions.reduce<Record<string, number>>((acc, a) => (a.transport ? { ...acc, [a.transport]: (acc[a.transport] ?? 0) + 1 } : acc), {});
  if (Object.keys(byTransport).length > 0) {
    out.push({
      rule: "Execution transport",
      detail: Object.entries(byTransport).map(([k, n]) => `${n} via ${k}`).join(", ") + ` (${t.orchestration?.mcp_transport ?? "mcp/stdio"} is the real MCP client; twin = in-process sandbox)`,
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

function DiffSection({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-tx3">
        {title} <span className="mono text-tx2">{count}</span>
      </div>
      {count === 0 ? <p className="text-xs text-tx3">None.</p> : children}
    </div>
  );
}

function DealerRow({ id, orders }: { id: string; orders: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="rounded-md border border-line bg-surface-2 px-2 py-1">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-center gap-1.5 text-left text-xs">
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <Mono className="font-medium text-tx">{id}</Mono>
        <span className="text-tx3">{orders.length} order{orders.length === 1 ? "" : "s"}</span>
      </button>
      {open && <div className="mt-1.5"><ChipList items={orders} /></div>}
    </li>
  );
}

export function AuditTab({ trace }: { trace: Trace }) {
  const d = trace.world_diff;
  const target = useExecTarget(trace.event_id);
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
          <ul className="mt-3 space-y-1 border-t border-line pt-3">
            {gateSteps.map(({ agent, s }, i) => (
              <li key={i} className="flex flex-wrap items-baseline gap-2 text-xs">
                <Chip color={STEP_META[s.kind].color}>{STEP_META[s.kind].label}</Chip>
                <span className="text-tx3">{agent}</span>
                <span className="text-tx2">{s.text}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="World diff: what changed">
        <div className="mb-4 grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
          <Stat label="POs moved" value={d.moved_pos.length} />
          <Stat label="Dealers notified" value={d.notified_dealers.length} />
          <Stat label="Loaners" value={d.loaners.length} />
          <Stat label="Lots held" value={d.held_lots.length} />
          <Stat label="VINs stopped" value={d.stopped_vins.length} />
          <Stat label="Owners contacted" value={d.contacted_customers.length} />
        </div>
        <div className="space-y-4">
          <DiffSection title="Moved production orders" count={d.moved_pos.length}>
            <div className="max-h-72 overflow-auto rounded-md border border-line">
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
          <DiffSection title="Dealers notified" count={d.notified_dealers.length}>
            <ul className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">
              {d.notified_dealers.map((n) => (
                <DealerRow key={n.dealer_id} id={n.dealer_id} orders={n.customer_order_ids} />
              ))}
            </ul>
          </DiffSection>
          <DiffSection title="Loaners assigned (customer orders)" count={d.loaners.length}><ChipList items={d.loaners} /></DiffSection>
          <DiffSection title="Held lots" count={d.held_lots.length}><ChipList items={d.held_lots} /></DiffSection>
          <DiffSection title="Stopped VINs" count={d.stopped_vins.length}><ChipList items={d.stopped_vins} /></DiffSection>
          <DiffSection title="Contacted customers" count={d.contacted_customers.length}><ChipList items={d.contacted_customers} /></DiffSection>
        </div>
      </Panel>

      <Panel
        title="LLM usage"
        action={<span className="mono text-[11px] text-tx3">{calls.length} calls · {usd(trace.llm.total_cost_usd)} · pipeline v{trace.pipeline_version}</span>}
      >
        {calls.length === 0 ? (
          <p className="text-xs text-tx3">No model calls were made for this event (everything was decided by code).</p>
        ) : (
          <div className="overflow-x-auto">
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
        )}
      </Panel>
    </div>
  );
}
