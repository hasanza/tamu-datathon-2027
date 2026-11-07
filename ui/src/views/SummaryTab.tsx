import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { Incident, Trace } from "../api/types";
import { CategoryBadge, Chip, ConfidenceRing, Mono, Panel, Stat } from "../components/ui/primitives";
import { ImpactPanel } from "./ImpactPanel";

function Id({ v }: { v: string | null }) {
  return v ? <Mono>{v}</Mono> : <span className="text-tx3">-</span>;
}
function Range({ a, b }: { a: string | null; b: string | null }) {
  if (!a && !b) return <span className="text-tx3">-</span>;
  return (
    <Mono>
      {a ?? "?"}
      {b && b !== a ? ` → ${b}` : ""}
    </Mono>
  );
}

function IncidentDetail({ inc }: { inc: Incident }) {
  return (
    <div className="grid gap-4 bg-surface-2 p-3 text-xs md:grid-cols-2">
      <div className="space-y-2">
        <div className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Why this category</div>
        <p className="text-tx2">{inc.reason}</p>
        {Object.keys(inc.raw_mentions).length > 0 && (
          <>
            <div className="pt-1 text-[11px] font-semibold uppercase tracking-wide text-tx3">Raw mentions</div>
            <dl className="space-y-0.5">
              {Object.entries(inc.raw_mentions).map(([k, v]) => (
                <div key={k} className="flex gap-2">
                  <dt className="mono w-28 shrink-0 text-tx3">{k}</dt>
                  <dd className="text-tx2">“{v}”</dd>
                </div>
              ))}
            </dl>
          </>
        )}
        {inc.ambiguities.length > 0 && (
          <>
            <div className="pt-1 text-[11px] font-semibold uppercase tracking-wide text-tx3">Ambiguities</div>
            <ul className="space-y-1">
              {inc.ambiguities.map((a, i) => (
                <li key={i} className="flex flex-wrap items-center gap-1.5 text-tx2">
                  <Chip color={a.blocking ? "var(--fail)" : "var(--warn)"}>{a.blocking ? "blocking" : "minor"}</Chip>
                  <Mono>{a.field}</Mono> {a.issue}
                  {a.options.length > 0 && <span className="text-tx3">({a.options.join(" | ")})</span>}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      <div>
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-tx3">Resolution steps</div>
        {inc.resolution_steps.length === 0 ? (
          <p className="text-tx3">No entities were resolved.</p>
        ) : (
          <ol className="space-y-1.5">
            {inc.resolution_steps.map((s, i) => (
              <li key={i} className="rounded-md border border-line bg-surface p-2">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span className="text-tx2">“{s.mention}”</span>
                  <span className="text-tx3">→</span>
                  {s.chosen ? <Mono className="font-medium text-tx">{s.chosen}</Mono> : <span className="text-fail">unresolved</span>}
                  <Chip color="var(--text-2)">{s.entity_type}</Chip>
                  <Chip color="var(--cat-unconfirmed)">{s.method}</Chip>
                </div>
                {s.candidates.length > 1 && <div className="mt-1 text-tx3">candidates: {s.candidates.join(", ")}</div>}
                {s.note && <div className="mt-1 text-tx3">{s.note}</div>}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function IncidentsTable({ incidents }: { incidents: Incident[] }) {
  const [open, setOpen] = useState<Set<string>>(new Set(incidents.length === 1 ? [incidents[0]?.incident_id ?? ""] : []));
  const toggle = (id: string) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-[13px]">
        <thead className="bg-surface-2 text-[11px] uppercase tracking-wide text-tx3">
          <tr>
            <th className="w-6 px-2 py-1.5" />
            <th className="px-2 py-1.5">Incident</th>
            <th className="px-2 py-1.5">Category</th>
            <th className="px-2 py-1.5">Conf.</th>
            <th className="px-2 py-1.5">Plant</th>
            <th className="px-2 py-1.5">Part</th>
            <th className="px-2 py-1.5">Supplier</th>
            <th className="px-2 py-1.5">Shipment</th>
            <th className="px-2 py-1.5">Lot</th>
            <th className="px-2 py-1.5">Dates</th>
            <th className="px-2 py-1.5">Flags</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((inc) => {
            const isOpen = open.has(inc.incident_id);
            return (
              <Fragment key={inc.incident_id}>
                <tr className="border-t border-line align-top hover:bg-surface-2/50">
                  <td className="px-2 py-2">
                    <button
                      onClick={() => toggle(inc.incident_id)}
                      aria-expanded={isOpen}
                      aria-label={`${isOpen ? "Collapse" : "Expand"} ${inc.incident_id}`}
                      className="text-tx3 hover:text-tx"
                    >
                      {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </button>
                  </td>
                  <td className="px-2 py-2"><Mono>{inc.incident_id}</Mono></td>
                  <td className="px-2 py-2"><CategoryBadge category={inc.category} /></td>
                  <td className="px-2 py-2"><ConfidenceRing value={inc.confidence} size={24} /></td>
                  <td className="px-2 py-2"><Id v={inc.plant_id} /></td>
                  <td className="px-2 py-2"><Id v={inc.part_id} /></td>
                  <td className="px-2 py-2"><Id v={inc.supplier_id} /></td>
                  <td className="px-2 py-2"><Id v={inc.shipment_id} /></td>
                  <td className="px-2 py-2"><Id v={inc.lot_id} /></td>
                  <td className="space-y-0.5 px-2 py-2 leading-tight">
                    {(inc.orig_eta || inc.new_eta) && (
                      <div className="whitespace-nowrap"><span className="text-tx3">ETA </span><Range a={inc.orig_eta} b={inc.new_eta} /></div>
                    )}
                    {(inc.outage_start || inc.outage_end) && (
                      <div className="whitespace-nowrap"><span className="text-tx3">Down </span><Range a={inc.outage_start} b={inc.outage_end} /></div>
                    )}
                    {(inc.build_window_start || inc.build_window_end) && (
                      <div className="whitespace-nowrap"><span className="text-tx3">Build </span><Range a={inc.build_window_start} b={inc.build_window_end} /></div>
                    )}
                    {!inc.orig_eta && !inc.new_eta && !inc.outage_start && !inc.outage_end && !inc.build_window_start && !inc.build_window_end && (
                      <span className="text-tx3">-</span>
                    )}
                  </td>
                  <td className="px-2 py-2">
                    {inc.ambiguities.length > 0 ? (
                      <Chip color={inc.ambiguities.some((a) => a.blocking) ? "var(--fail)" : "var(--warn)"}>
                        {inc.ambiguities.length} ambiguit{inc.ambiguities.length === 1 ? "y" : "ies"}
                      </Chip>
                    ) : (
                      <span className="text-tx3">-</span>
                    )}
                  </td>
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={11} className="p-0">
                      <IncidentDetail inc={inc} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function SummaryTab({ trace }: { trace: Trace }) {
  const cf = trace.counterfactual;
  return (
    <div className="space-y-4">
      <Panel title="Summary">
        <p className="text-[15px] leading-relaxed text-tx">{trace.summary}</p>
        <div className="mt-3 rounded-md border-l-[3px] border-brand-bright bg-surface-2 px-3 py-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Decision reason</div>
          <p className="text-[13px] text-tx2">{trace.decision_reason}</p>
        </div>
        <div className="mt-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Original event text</div>
          <blockquote className="mt-1 whitespace-pre-wrap rounded-md border border-line bg-bg px-3 py-2 text-[13px] text-tx2">{trace.text}</blockquote>
        </div>
        <p className="mt-2 text-xs text-tx3">Classifier: {trace.classification.reason}</p>
      </Panel>

      <Panel title={`Business impact${cf ? "" : " (none)"}`}>
        {cf ? (
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6">
            <Stat label="Customers affected" value={cf.customers_affected} />
            <Stat label="Avg slip (days)" value={cf.avg_slip_days != null ? cf.avg_slip_days.toFixed(1) : "-"} />
            <Stat label="Loaners assigned" value={cf.loaners_assigned} sub={`of ${cf.loaners_entitled} entitled`} />
            <Stat label="Loaners entitled" value={cf.loaners_entitled} />
            <Stat label="Vehicles pulled" value={cf.vehicles_pulled} />
            <Stat label="Owners contacted" value={cf.owners_contacted} />
          </div>
        ) : (
          <p className="text-[13px] text-tx3">No operational change was made, so there is no business impact to measure.</p>
        )}
      </Panel>

      <ImpactPanel trace={trace} />

      <Panel title={`Incidents (${trace.incidents.length})`} className="[&>div]:p-0">
        <IncidentsTable incidents={trace.incidents} />
      </Panel>
    </div>
  );
}
