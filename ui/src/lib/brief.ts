import type { Brief, BriefFact, BriefOutcome, Incident, IncidentBrief, Trace } from "../api/types";
import { CATEGORY_META } from "./meta";
import { firstSentence } from "./flow";

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The first word of a headline names the outcome; the Summary tints it. */
export function outcomeOf(trace: Trace): BriefOutcome {
  if (trace.brief?.outcome) return trace.brief.outcome;
  if (trace.status === "noise" || trace.classification.category === "noise") return "noise";
  if (trace.status === "failed") return "failed";
  if (trace.status === "escalated") return "escalated";
  return "acted";
}

const where = (i: Incident) => i.plant_id ?? i.supplier_id ?? i.lot_id ?? i.part_id ?? null;
const windowOf = (i: Incident): string | null => {
  const range = (a: string | null, b: string | null) => (a || b ? `${a ?? "?"}${b && b !== a ? ` to ${b}` : ""}` : null);
  return range(i.outage_start, i.outage_end) ?? range(i.build_window_start, i.build_window_end) ?? range(i.orig_eta, i.new_eta);
};

/** Event-level rows from what the trace recorded (ids, not plant names): the same counting the Flow chips use. */
function factsOf(trace: Trace): BriefFact[] {
  const d = trace.world_diff;
  const cf = trace.counterfactual;
  const facts: BriefFact[] = [];
  if (d.moved_pos.length > 0) {
    const transfers = d.moved_pos.filter((m) => m.kind === "transfer").length;
    const reschedules = d.moved_pos.length - transfers;
    facts.push({
      label: "Orders moved",
      value: String(d.moved_pos.length),
      detail: [reschedules ? `${reschedules} rescheduled` : "", transfers ? `${transfers} transferred` : ""].filter(Boolean).join(", ") || null,
    });
  }
  if (d.notified_dealers.length > 0) {
    const orders = d.notified_dealers.reduce((n, x) => n + x.customer_order_ids.length, 0);
    facts.push({ label: "Dealers notified", value: String(d.notified_dealers.length), detail: orders ? `${plural(orders, "customer order")}` : null });
  }
  if (d.loaners.length > 0) facts.push({ label: "Loaners", value: String(d.loaners.length), detail: cf ? `of ${cf.loaners_entitled} entitled` : null });
  if (d.held_lots.length > 0) facts.push({ label: "Lots held", value: d.held_lots.length === 1 ? (d.held_lots[0] ?? "1") : String(d.held_lots.length) });
  if (d.stopped_vins.length > 0) facts.push({ label: "Stop-sales", value: plural(d.stopped_vins.length, "VIN") });
  if (d.contacted_customers.length > 0) facts.push({ label: "Owners contacted", value: String(d.contacted_customers.length) });
  return facts;
}

function headlineOf(trace: Trace, outcome: BriefOutcome): string {
  const cat = CATEGORY_META[trace.classification.category]?.label.toLowerCase() ?? "event";
  if (outcome === "noise") return "Noise: not an operational event, no action";
  if (outcome === "escalated") return `Escalated: ${cat}, no action`;
  if (outcome === "failed") return `Failed: ${cat}, nothing was changed`;
  const n = trace.incidents.length || 1;
  const d = trace.world_diff;
  const parts = [
    d.moved_pos.length ? `${d.moved_pos.length} orders moved` : "",
    d.notified_dealers.length ? `${d.notified_dealers.length} dealers notified` : "",
    d.loaners.length ? `${plural(d.loaners.length, "loaner")}` : "",
    d.held_lots.length ? `${plural(d.held_lots.length, "lot")} held` : "",
    d.stopped_vins.length ? `${plural(d.stopped_vins.length, "VIN")} stopped` : "",
    d.contacted_customers.length ? `${d.contacted_customers.length} owners contacted` : "",
  ].filter(Boolean);
  return `${outcome === "partial" ? "Partly acted on" : "Acted on"} ${plural(n, "incident")}${parts.length ? `: ${parts.join(", ")}` : ""}`;
}

/** `trace.brief` when the pipeline wrote one; otherwise the same shape derived from the classification, world diff and counterfactual. */
export function briefOf(trace: Trace): Brief {
  if (trace.brief) return trace.brief;
  const outcome = outcomeOf(trace);
  const facts = outcome === "acted" || outcome === "partial" ? factsOf(trace) : [];
  const incidents: IncidentBrief[] = trace.incidents.map((i) => ({
    incident_id: i.incident_id,
    category: i.category,
    title: `${CATEGORY_META[i.category]?.label ?? i.category}${where(i) ? ` - ${where(i)}` : ""}`,
    window: windowOf(i),
    facts: trace.incidents.length === 1 ? facts : [],
    note: facts.length === 0 || trace.incidents.length > 1 ? firstSentence(i.reason, 140) : null,
  }));
  if (trace.incidents.length > 1 && facts.length > 0) {
    // the world diff is not split per incident: show the totals once, after the incident titles
    incidents.push({ incident_id: "all", category: trace.classification.category, title: "Across all incidents", window: null, facts, note: null });
  }
  const gates: string[] = [];
  const checks = trace.actions.filter((a) => a.rehearsal);
  if (outcome === "acted" && checks.length > 0 && checks.every((a) => a.rehearsal?.ok)) gates.push(`pre-flight ${checks.length}/${checks.length} accepted`);
  return { headline: headlineOf(trace, outcome), outcome, incidents, gates };
}

/** The first sentence of the decision reason, with its rule number kept even when it comes later in the text. */
export function whyOf(reason: string): { why: string; rest: string } {
  const flat = reason.replace(/\s+/g, " ").trim();
  const m = /^(.+?[.!?])(\s+|$)/.exec(flat);
  const first = m?.[1] ?? flat;
  const rest = m ? flat.slice(m[0].length) : "";
  const rule = /rule\s+\d+/i.exec(flat)?.[0];
  return { why: !rule || /rule\s+\d+/i.test(first) ? first : `${first.replace(/[.!?]$/, "")} (${rule.toLowerCase()}).`, rest };
}
