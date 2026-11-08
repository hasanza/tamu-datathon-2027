import { ArrowDown, ArrowRight, ArrowUpDown, Brain, Cog, FileText, FlaskConical, Play, UserRound } from "lucide-react";
import type { ReactNode } from "react";
import { useKpis } from "../api/hooks";
import { Chip, Mono, Panel } from "../components/ui/primitives";
import { LANE_META, type LaneId } from "../lib/meta";

/* About page for the v2 architecture (docs/PLAN_V2.md §2): a coordinator and three specialist LLM agents reason and
   orchestrate; plain-code tools compute; a sandbox pre-flight proves; an MCP client executes. */

interface Stage {
  icon: ReactNode;
  verb: string;
  who: string;
  color: string;
  body: string;
  lines: string[];
}

const STAGES: Stage[] = [
  {
    icon: <Brain size={18} />,
    verb: "Agents reason",
    who: "Four LLM agents",
    color: "var(--cat-quality)",
    body: "A coordinator reads the event, decides what it is and delegates. Three specialists each plan their part and say why.",
    lines: ["Coordinator is the hub", "Specialists never call each other", "Every hand-off is validated and recorded"],
  },
  {
    icon: <Cog size={18} />,
    verb: "Tools compute",
    who: "Plain code",
    color: "var(--cat-unconfirmed)",
    body: "Graph traversals, slot planning, loaner ranking and the policy handbook (as validators) are code the agents call, not text the model writes.",
    lines: ["Ids, dates and quantities come from tools", "A failing validator sends the plan back", "Two failed rounds escalate to a human"],
  },
  {
    icon: <FlaskConical size={18} />,
    verb: "Pre-flight proves",
    who: "Sandbox copy of the enterprise",
    color: "var(--cat-compound)",
    body: "Every plan is rehearsed on a sandbox copy before a single write is sent, then checked by a second model. If anything fails, nothing is sent.",
    lines: ["Invariants checked", "Independent auditor model", "Gate: confidence and pre-flight"],
  },
  {
    icon: <Play size={18} />,
    verb: "MCP executes",
    who: "Real MCP client",
    color: "var(--ok)",
    body: "Only a proven plan is executed, through an MCP client against the enterprise server. A failed write is never retried blindly.",
    lines: ["mes · dealer · crm · quality", "Failed call: rest skipped, one escalation", "One trace per event"],
  },
];

function Spoke({ lane, tools }: { lane: LaneId; tools: string[] }) {
  const m = LANE_META[lane];
  return (
    <div className="rounded-lg border bg-surface-2 p-2.5" style={{ borderColor: `color-mix(in srgb, ${m.color} 55%, var(--border))` }}>
      <div className="flex items-center gap-1.5 text-[13px] font-semibold">
        <span className="h-2 w-2 rounded-full" style={{ background: m.color }} aria-hidden />
        {m.label}
      </div>
      <p className="mt-0.5 text-[11px] text-tx3">{m.blurb}</p>
      <ul className="mono mt-1.5 space-y-0.5 text-[11px] text-tx2">
        {tools.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ul>
    </div>
  );
}

/** Hub and spoke: delegation goes out through the coordinator and comes back as a typed result. */
function HubDiagram() {
  const hub = LANE_META.coordinator;
  return (
    <div className="space-y-2" role="img" aria-label="Coordinator in the middle, delegating to Supply Chain Planner, Dealer Network and Customer Care and Quality, then validating, running a pre-flight check on a sandbox copy, auditing and executing through MCP">
      <div className="flex flex-wrap items-center justify-center gap-2">
        <div className="rounded-lg border border-line bg-bg px-3 py-2 text-[12px] text-tx2">
          <FileText size={14} className="mr-1 inline text-tx3" aria-hidden /> event text
        </div>
        <ArrowRight size={16} className="text-tx3" aria-hidden />
        <div className="rounded-lg border-2 bg-surface-2 px-4 py-2 text-center" style={{ borderColor: hub.color }}>
          <div className="text-[14px] font-semibold">{hub.label}</div>
          <div className="text-[11px] text-tx3">understand · resolve · gate · delegate · validate · execute · explain</div>
        </div>
        <ArrowRight size={16} className="text-tx3" aria-hidden />
        <div className="rounded-lg border border-line bg-bg px-3 py-2 text-[12px] text-tx2">
          <UserRound size={14} className="mr-1 inline text-tx3" aria-hidden /> escalate to a human
        </div>
      </div>
      <div className="flex items-center justify-center gap-1.5 text-[11px] text-tx3">
        <ArrowUpDown size={14} aria-hidden /> delegate (task) / typed result (actions, findings, graph paths)
      </div>
      <div className="grid gap-2 md:grid-cols-3">
        <Spoke lane="supply_chain_planner" tools={["affected_builds · graph", "get_schedule · MCP read", "propose_slots · code"]} />
        <Spoke lane="dealer_network" tools={["customer_orders_of · graph", "compose_notices · code", "compose_stop_sales · code"]} />
        <Spoke lane="customer_care_quality" tools={["match_lot · affected_vehicles · graph", "loaner_availability · MCP read", "rank_and_assign · code"]} />
      </div>
      <div className="flex flex-wrap items-center justify-center gap-1.5 text-[12px] text-tx2">
        <ArrowDown size={14} className="text-tx3" aria-hidden />
        {["validate (handbook as code)", "pre-flight check (sandbox copy)", "auditor (second model)", "MCP client", "enterprise server"].map((s, i, a) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span className="rounded-md border border-line bg-bg px-2 py-0.5">{s}</span>
            {i < a.length - 1 && <ArrowRight size={13} className="text-tx3" aria-hidden />}
          </span>
        ))}
      </div>
    </div>
  );
}

export function AboutPage() {
  const models = useKpis().data?.models ?? [];
  return (
    <div className="mx-auto max-w-[1200px] space-y-4 p-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">About</h2>
        <p className="mt-1 max-w-3xl text-[13px] text-tx2">
          Wacky Wheels Control Tower turns a stream of unstructured disruption reports into a small number of correct, explainable actions.
          Four agents reason about each event; every number that changes the world comes from code, is proven by a pre-flight check on a sandbox copy first, and is then executed through MCP. Every plan is rehearsed on a sandbox copy before a single write is sent; judge events run on a private sandbox server through the same MCP client.
        </p>
        <p className="mt-2 inline-block rounded-md border-l-[3px] border-brand-bright bg-surface-2 px-3 py-1.5 text-[14px] font-medium text-tx">
          Agents reason and orchestrate; tools compute; the sandbox proves; MCP executes.
        </p>
      </div>

      <Panel title="Architecture">
        <HubDiagram />
        <div className="mt-4 grid items-stretch gap-2 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
          {STAGES.map((s, i) => (
            <div key={s.verb} className="contents">
              <div className="flex flex-col rounded-lg border bg-surface-2 p-3" style={{ borderColor: `color-mix(in srgb, ${s.color} 55%, var(--border))` }}>
                <div className="flex items-center gap-2" style={{ color: s.color }}>
                  {s.icon}
                  <span className="text-[15px] font-semibold tracking-tight text-tx">{s.verb}</span>
                </div>
                <div className="mt-0.5 text-[11px] uppercase tracking-wide text-tx3">{s.who}</div>
                <p className="mt-2 text-[13px] text-tx2">{s.body}</p>
                <ul className="mt-2 space-y-1 text-xs text-tx2">
                  {s.lines.map((l) => (
                    <li key={l} className="flex gap-1.5">
                      <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full" style={{ background: s.color }} aria-hidden />
                      {l}
                    </li>
                  ))}
                </ul>
              </div>
              {i < STAGES.length - 1 && (
                <div className="flex items-center justify-center text-tx3">
                  <ArrowRight size={18} className="rotate-90 lg:rotate-0" aria-hidden />
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center gap-2 rounded-lg border border-line bg-bg px-3 py-2 text-[13px] text-tx2">
          <FileText size={16} className="shrink-0 text-tx3" aria-hidden />
          <span>
            Output per event: a <b className="text-tx">trace</b> (classification, incidents, graph paths, the Orchestration timeline of every agent turn, tool call and
            message, actions with rehearsal, transport and result, world diff, business impact, LLM usage, plain-language summary) and rows in{" "}
            <Mono>action_log.jsonl</Mono>.
          </span>
        </div>
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Models">
          {models.length === 0 ? (
            <p className="text-[13px] text-tx3">The models used appear here once a run has produced traces.</p>
          ) : (
            <ul className="space-y-2 text-[13px]">
              {models.map((m) => (
                <li key={m} className="flex items-center gap-2">
                  <Chip color="var(--cat-quality)">model</Chip>
                  <Mono className="text-tx">{m}</Mono>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 text-xs text-tx3">
            Read from the traces on screen, not written by hand. Per-agent models, token counts and cost are on each event&apos;s Orchestration header and Audit tab.
          </p>
        </Panel>
        <Panel title="Guarantees">
          <ul className="space-y-1.5 text-[13px] text-tx2">
            <li>The policy handbook is enforced by validators written as code, rule by rule.</li>
            <li>Nothing is written to the server unless the pre-flight check on the sandbox copy passed.</li>
            <li>Unconfirmed or ambiguous reports are escalated to a human, never acted on.</li>
            <li>A failed call is not retried blindly: the rest of that incident is skipped and escalated with what was done.</li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}
