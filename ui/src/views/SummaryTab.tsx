import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { Brief, BriefOutcome, Incident, IncidentBrief, Trace } from "../api/types";
import { CategoryBadge, Chip, ConfidenceRing, Mono, Panel, Stat } from "../components/ui/primitives";
import { Disclosure } from "../components/ui/Disclosure";
import { FollowUpControl, FollowUpList } from "../components/FollowUp";
import { briefOf, whyOf } from "../lib/brief";
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

/** The columns the table no longer shows: supplier, shipment, lot and the dates. */
function IncidentFacts({ inc }: { inc: Incident }) {
  const rows: [string, React.ReactNode][] = [
    ["Supplier", inc.supplier_id ? <Mono key="s">{inc.supplier_id}</Mono> : null],
    ["Shipment", inc.shipment_id ? <Mono key="h">{inc.shipment_id}</Mono> : null],
    ["Lot", inc.lot_id ? <Mono key="l">{inc.lot_id}</Mono> : null],
    ["ETA", inc.orig_eta || inc.new_eta ? <Range key="e" a={inc.orig_eta} b={inc.new_eta} /> : null],
    ["Down", inc.outage_start || inc.outage_end ? <Range key="d" a={inc.outage_start} b={inc.outage_end} /> : null],
    ["Build window", inc.build_window_start || inc.build_window_end ? <Range key="b" a={inc.build_window_start} b={inc.build_window_end} /> : null],
  ];
  const shown = rows.filter(([, v]) => v);
  if (shown.length === 0) return null;
  return (
    <dl className="grid grid-cols-[7rem_1fr] gap-x-2 gap-y-0.5 pb-1">
      {shown.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-tx3">{k}</dt>
          <dd className="text-tx2">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function IncidentDetail({ inc }: { inc: Incident }) {
  return (
    <div className="grid gap-4 bg-surface-2 p-3 text-xs md:grid-cols-2">
      <div className="space-y-2">
        <IncidentFacts inc={inc} />
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
            <th className="px-2 py-1.5">Incident</th>
            <th className="px-2 py-1.5">Category</th>
            <th className="px-2 py-1.5">Conf.</th>
            <th className="px-2 py-1.5">Plant</th>
            <th className="px-2 py-1.5">Part</th>
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
                      className="inline-flex items-center gap-1 text-tx3 hover:text-tx"
                    >
                      {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      <Mono className="text-tx">{inc.incident_id}</Mono>
                    </button>
                  </td>
                  <td className="px-2 py-2"><CategoryBadge category={inc.category} /></td>
                  <td className="px-2 py-2"><ConfidenceRing value={inc.confidence} size={24} /></td>
                  <td className="px-2 py-2"><Id v={inc.plant_id} /></td>
                  <td className="px-2 py-2"><Id v={inc.part_id} /></td>
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
                    <td colSpan={6} className="p-0">
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

function ImpactSlips({ trace }: { trace: Trace }) {
  // the panel renders nothing for events without moved orders; do not offer an empty trigger then
  const cf = trace.counterfactual;
  if (!cf || (trace.world_diff.moved_pos.length === 0 && cf.vehicles_pulled === 0 && cf.owners_contacted === 0)) return null;
  return (
    <Disclosure summary="Show slip distribution" storageKey="ct-summary-impact">
      <ImpactPanel trace={trace} />
    </Disclosure>
  );
}

const OUTCOME_COLOR: Record<BriefOutcome, string> = {
  acted: "var(--ok)",
  partial: "var(--warn)",
  escalated: "var(--cat-unconfirmed)",
  noise: "var(--text-3)",
  failed: "var(--fail)",
};

/** The conclusion first: one line, its first word tinted by the outcome. */
function Headline({ brief }: { brief: Brief }) {
  const [first, ...rest] = brief.headline.split(" ");
  return (
    <h3 data-headline className="text-[15px] font-semibold leading-snug text-tx">
      <span style={{ color: OUTCOME_COLOR[brief.outcome] }}>{first}</span> {rest.join(" ")}
    </h3>
  );
}

function IncidentBlock({ inc }: { inc: IncidentBrief }) {
  return (
    <section data-incident-block aria-label={inc.title} className="rounded-md border border-line bg-surface-2 px-3 py-2">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-[13px] font-medium text-tx">{inc.title}</span>
        {inc.window && <Mono className="text-[11.5px] text-tx3">{inc.window}</Mono>}
      </div>
      {inc.facts.length > 0 && (
        <dl className="mt-1.5 grid grid-cols-[9.5rem_1fr] items-baseline gap-x-3 gap-y-1" data-facts>
          {inc.facts.map((f) => (
            <div key={f.label} className="contents">
              <dt className="text-[11px] uppercase tracking-wide text-tx3">{f.label}</dt>
              <dd>
                <Mono className="text-[15px] font-semibold text-tx">{f.value}</Mono>
                {f.detail && <span className="ml-2 text-[12px] text-tx3">{f.detail}</span>}
              </dd>
            </div>
          ))}
        </dl>
      )}
      {inc.note && <p className="mt-1 text-[12.5px] text-tx2">{inc.note}</p>}
    </section>
  );
}

export function SummaryTab({ trace }: { trace: Trace }) {
  const cf = trace.counterfactual;
  const brief = briefOf(trace);
  const why = whyOf(trace.decision_reason);
  return (
    <div className="space-y-4">
      <Panel title="Summary">
        <Headline brief={brief} />
        {brief.gates.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5" aria-label="Checks passed">
            {brief.gates.map((g) => (
              <Chip key={g} color="var(--ok)">{g}</Chip>
            ))}
          </div>
        )}
        <div className="mt-3 space-y-3">
          {brief.incidents.map((inc) => (
            <IncidentBlock key={inc.incident_id} inc={inc} />
          ))}
        </div>
        <div className="mt-3 border-l-[3px] border-brand-bright bg-surface-2 px-3 py-2">
          <p className="text-[13px] text-tx2">
            <span className="mr-1.5 text-[11px] font-semibold uppercase tracking-wide text-tx3">Why</span>
            {why.why}
          </p>
          {why.rest && (
            <Disclosure summary="Full reason" className="mt-1">
              <p className="text-[13px] text-tx2">{why.rest}</p>
            </Disclosure>
          )}
        </div>
        <div className="mt-2 flex flex-col items-start gap-1">
          <Disclosure summary="Read the full account">
            <p className="max-w-3xl text-[14px] leading-relaxed text-tx">{trace.summary}</p>
          </Disclosure>
          <Disclosure summary="Show the original message">
            <blockquote className="whitespace-pre-wrap rounded-md border border-line bg-bg px-3 py-2 text-[13px] text-tx2">{trace.text}</blockquote>
            <p className="mt-2 text-xs text-tx3">Classifier: {trace.classification.reason}</p>
          </Disclosure>
        </div>
      </Panel>

      {(trace.status === "escalated" || trace.status === "failed") && (
        <Panel title="Needs a human">
          <p className="text-[13px] text-tx2">Handed to a person, nothing changed: add the missing details to re-run it in the sandbox.</p>
          <FollowUpControl trace={trace} />
          <FollowUpList parentId={trace.event_id} />
        </Panel>
      )}

      <Panel title={`Business impact${cf ? "" : " (none)"}`}>
        {cf ? (
          <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-5">
            <Stat label="Customers affected" value={cf.customers_affected} />
            <Stat label="Avg slip (days)" value={cf.avg_slip_days != null ? cf.avg_slip_days.toFixed(1) : "-"} />
            <Stat label="Loaners assigned" value={cf.loaners_assigned} />
            <Stat label="Vehicles pulled" value={cf.vehicles_pulled} />
            <Stat label="Owners contacted" value={cf.owners_contacted} />
          </div>
        ) : (
          <p className="text-[13px] text-tx3">No operational change was made, so there is no business impact to measure.</p>
        )}
      </Panel>

      <ImpactSlips trace={trace} />

      <Panel title={`Incidents (${trace.incidents.length})`} className="[&>div]:p-0">
        <IncidentsTable incidents={trace.incidents} />
      </Panel>
    </div>
  );
}
