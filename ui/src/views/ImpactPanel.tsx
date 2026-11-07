import type { ReactNode } from "react";
import type { Trace } from "../api/types";
import { Panel } from "../components/ui/primitives";

/* Blast radius (task 4.5): what the incident touched and what the control tower prevented.
   Plain CSS bars on BRAND tokens: every bar carries its number, so nothing relies on colour alone. */

const DAY_MS = 86_400_000;

interface Bin {
  label: string;
  hint: string;
  test: (d: number) => boolean;
}
const SLIP_BINS: Bin[] = [
  { label: "earlier", hint: "transferred to an earlier slot", test: (d) => d < 0 },
  { label: "0 d", hint: "same day (another plant)", test: (d) => d === 0 },
  { label: "1-2 d", hint: "", test: (d) => d >= 1 && d <= 2 },
  { label: "3-4 d", hint: "", test: (d) => d >= 3 && d <= 4 },
  { label: "5-7 d", hint: "", test: (d) => d >= 5 && d <= 7 },
  { label: "8+ d", hint: "", test: (d) => d >= 8 },
];

/** Calendar days between the original and the new build date of each moved production order. */
export function slipDays(t: Trace): number[] {
  return t.world_diff.moved_pos.map((m) => Math.round((Date.parse(m.to_date) - Date.parse(m.from_date)) / DAY_MS));
}

function Bar({ label, value, max, color, note }: { label: ReactNode; value: number; max: number; color: string; note?: ReactNode }) {
  const pct = max > 0 ? Math.max(value > 0 ? 2 : 0, (value / max) * 100) : 0;
  return (
    <div className="grid grid-cols-[84px_minmax(0,1fr)_auto] items-center gap-2 text-[12px]">
      <span className="text-tx2">{label}</span>
      <div className="h-3.5 overflow-hidden rounded-sm bg-surface-2" aria-hidden>
        <div className="h-full rounded-sm" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="mono min-w-[2.5rem] text-right text-tx">
        {value}
        {note && <span className="ml-1 text-[10px] text-tx3">{note}</span>}
      </span>
    </div>
  );
}

function Block({ title, sub, children }: { title: string; sub?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-2 rounded-lg border border-line bg-surface-2 p-3">
      <div>
        <h3 className="text-[12px] font-semibold uppercase tracking-wide text-tx3">{title}</h3>
        {sub && <p className="mt-0.5 text-[12px] text-tx2">{sub}</p>}
      </div>
      <div className="space-y-1.5">{children}</div>
    </section>
  );
}

export function ImpactPanel({ trace }: { trace: Trace }) {
  const cf = trace.counterfactual;
  const moved = trace.world_diff.moved_pos;
  if (!cf || (moved.length === 0 && cf.vehicles_pulled === 0 && cf.owners_contacted === 0)) return null;

  const slips = slipDays(trace);
  const counts = SLIP_BINS.map((b) => slips.filter(b.test).length);
  const maxBin = Math.max(...counts, 1);
  const transfers = moved.filter((m) => m.kind === "transfer").length;
  const dealers = trace.world_diff.notified_dealers.length;
  const shortfall = cf.loaners_entitled - cf.loaners_assigned;
  const quality = cf.vehicles_pulled > 0 || cf.owners_contacted > 0;

  return (
    <Panel title="Blast radius and what we prevented">
      <div className="grid gap-3 lg:grid-cols-2">
        {moved.length > 0 && (
          <Block
            title="Production orders moved: slip per order"
            sub={
              <>
                {moved.length} orders moved ({moved.length - transfers} rescheduled, {transfers} transferred to another plant),
                {" "}
                {cf.customers_affected} customers across {dealers} dealers told once each.
              </>
            }
          >
            <div role="img" aria-label={`Slip histogram: ${SLIP_BINS.map((b, i) => `${b.label} ${counts[i]}`).join(", ")} orders`} className="space-y-1.5">
              {SLIP_BINS.map((b, i) => (
                <Bar key={b.label} label={<span title={b.hint}>{b.label}</span>} value={counts[i] ?? 0} max={maxBin} color={i === 0 ? "var(--ok)" : "var(--cat-outage)"} />
              ))}
            </div>
            <p className="text-[11px] text-tx3">Slip = calendar days between the original and the new build date. Average (clamped at 0): {cf.avg_slip_days?.toFixed(1) ?? "-"} d.</p>
          </Block>
        )}

        {cf.loaners_entitled > 0 && (
          <Block
            title="Loaners: entitled vs assigned"
            sub={
              shortfall > 0
                ? `${shortfall} entitled customer${shortfall === 1 ? "" : "s"} got no loaner: their dealer's pool ran out (Platinum first, then Gold, then earliest promise).`
                : "Every entitled Platinum and Gold customer got a loaner within the dealer pools."
            }
          >
            <div role="img" aria-label={`${cf.loaners_assigned} loaners assigned of ${cf.loaners_entitled} entitled`} className="space-y-1.5">
              <Bar label="Entitled" value={cf.loaners_entitled} max={cf.loaners_entitled} color="var(--text-3)" />
              <Bar label="Assigned" value={cf.loaners_assigned} max={cf.loaners_entitled} color="var(--ok)" note={`${Math.round((cf.loaners_assigned / cf.loaners_entitled) * 100)}%`} />
              {shortfall > 0 && <Bar label="No loaner" value={shortfall} max={cf.loaners_entitled} color="var(--warn)" />}
            </div>
            <p className="text-[11px] text-tx3">Standard-tier customers are told through their dealer but get no loaner (handbook rule 5).</p>
          </Block>
        )}

        {quality && (
          <Block
            title="Vehicles pulled vs owners contacted"
            sub={`${cf.vehicles_pulled} unsold vehicles stopped at their dealers; ${cf.owners_contacted} owners of sold vehicles contacted. ${cf.vehicles_pulled + cf.owners_contacted} affected vehicles in total.`}
          >
            <div role="img" aria-label={`${cf.vehicles_pulled} unsold vehicles stopped, ${cf.owners_contacted} owners contacted`} className="space-y-1.5">
              <Bar label="In stock" value={cf.vehicles_pulled} max={Math.max(cf.vehicles_pulled, cf.owners_contacted)} color="var(--cat-quality)" note="stop sale" />
              <Bar label="Sold" value={cf.owners_contacted} max={Math.max(cf.vehicles_pulled, cf.owners_contacted)} color="var(--ok)" note="owner told" />
            </div>
          </Block>
        )}
      </div>
    </Panel>
  );
}
