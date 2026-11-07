import { ArrowRight, Brain, Cog, FlaskConical, FileText, Play } from "lucide-react";
import type { ReactNode } from "react";
import { Chip, Mono, Panel } from "../components/ui/primitives";

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
    verb: "LLM understands",
    who: "Extraction",
    color: "var(--cat-quality)",
    body: "Free-text events become structured incidents: category, confidence, plant, part, shipment, lot and dates.",
    lines: ["15 messy events in", "Resolver maps mentions to real ids", "Ambiguity is recorded, never guessed"],
  },
  {
    icon: <Cog size={18} />,
    verb: "Code decides",
    who: "Deterministic agents",
    color: "var(--cat-unconfirmed)",
    body: "Three specialists walk the knowledge graph and apply the policy handbook as code. No model is involved in the plan.",
    lines: ["Supply Chain Planner", "Dealer & Customer Care", "Quality"],
  },
  {
    icon: <FlaskConical size={18} />,
    verb: "Twin proves",
    who: "In-process twin",
    color: "var(--cat-compound)",
    body: "The whole plan is rehearsed on a copy of the enterprise. If any step fails, nothing is sent to the real server.",
    lines: ["Invariants checked", "Independent auditor model", "Gate: confidence and rehearsal"],
  },
  {
    icon: <Play size={18} />,
    verb: "Then act",
    who: "MCP tools",
    color: "var(--ok)",
    body: "Only a proven plan is executed against the enterprise server. Every call lands in the action log and the trace.",
    lines: ["mes · dealer · crm · quality", "Writes are counted and graded", "One trace per event"],
  },
];

export function AboutPage() {
  return (
    <div className="mx-auto max-w-[1200px] space-y-4 p-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">About</h2>
        <p className="mt-1 max-w-3xl text-[13px] text-tx2">
          Wacky Wheels Control Tower turns a stream of unstructured disruption reports into a small number of correct, explainable actions.
          The language model is used only where language is the problem; every decision that changes the world is made by code and proven first.
        </p>
      </div>

      <Panel title="Architecture">
        <div className="grid items-stretch gap-2 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
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
            Output per event: a <b className="text-tx">trace</b> (classification, incidents, graph paths, per-agent timeline, actions with rehearsal and result, world
            diff, business impact, LLM usage, plain-language summary) and rows in <Mono>action_log.jsonl</Mono>.
          </span>
        </div>
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Models">
          <ul className="space-y-2 text-[13px]">
            <li className="flex items-center gap-2">
              <Chip color="var(--cat-quality)">workhorse</Chip>
              <Mono className="text-tx">gemini-3.5-flash-lite</Mono>
              <span className="text-tx3">extraction, summaries</span>
            </li>
            <li className="flex items-center gap-2">
              <Chip color="var(--cat-outage)">auditor</Chip>
              <Mono className="text-tx">gemini-3.8-flash</Mono>
              <span className="text-tx3">independent check of the plan</span>
            </li>
          </ul>
          <p className="mt-3 text-xs text-tx3">The planner, graph and world modules import no LLM. Costs and token counts are on each event&apos;s Audit tab.</p>
        </Panel>
        <Panel title="Guarantees">
          <ul className="space-y-1.5 text-[13px] text-tx2">
            <li>The policy handbook is implemented in code, rule by rule.</li>
            <li>Nothing is written to the server unless the twin rehearsal passed.</li>
            <li>Unconfirmed or ambiguous reports are escalated to a human, never acted on.</li>
            <li>Nothing in the pipeline is hard-coded to a specific event.</li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}
