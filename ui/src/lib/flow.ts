import type { AgentId, AgentStep } from "../api/types";
import type { OrchRow } from "../views/OrchestrationTab";
import { prettifyRepr } from "./format";
import { laneOf, type LaneId } from "./meta";

/* The Flow view's model (docs: CORE #68). A trace is a long list of steps; this groups consecutive steps into STAGE NODES:
     understand -> [hub -> delegate (one per delegated task)]* -> validate -> execute -> finish
   Coordinator nodes sit on the top row, specialist (delegate) nodes on the bottom row. Edges are the hand-off message steps:
   the brief goes down to the specialist, its result comes back up. Pure functions, no React: easy to reason about and to test. */

export type NodeKind = "understand" | "delegate" | "hub" | "validate" | "execute" | "finish";
export type Tone = "ok" | "warn" | "fail" | "info" | "muted";
export interface FlowChip {
  text: string;
  tone: Tone;
}
export interface FlowNode {
  /** stable while a live run grows, so existing nodes are not re-animated */
  id: string;
  kind: NodeKind;
  lane: LaneId;
  row: "top" | "bottom";
  /** "Supply Chain Planner" / "Understand the message" / ... */
  title: string;
  /** "reschedule · E-01#1" / "hand off to Dealer Network" / ... */
  subtitle: string;
  summary: string;
  chips: FlowChip[];
  steps: OrchRow[];
  turns: number;
  tools: number;
  cost: number;
  ms: number;
  task: string | null;
  incident: string | null;
}
export interface FlowEdge {
  from: string;
  to: string;
  label: string;
  dir: "down" | "up" | "across";
}
export interface Flow {
  nodes: FlowNode[];
  edges: FlowEdge[];
}
export interface FlowContext {
  /** the trace status when known (done | escalated | noise | failed) */
  status?: string;
  correctionRounds?: number;
  escalations?: { incident_id: string; reason: string }[];
  /** a run in progress: the last node is still active */
  live?: boolean;
  /** the coordinator's own words about an escalation, taken from any stage (set by buildFlow) */
  escalationNote?: string;
}

export const TASK_LABEL: Record<string, string> = {
  reschedule: "reschedule",
  dealer_comms: "dealer notices",
  loaners: "loaners",
  quality_hold: "quality hold",
};
const taskLabel = (t: string | null | undefined) => (t ? (TASK_LABEL[t] ?? t.replace(/_/g, " ")) : "task");

/* ---------- small text helpers ---------- */

const clipText = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);
export function firstSentence(text: string, n = 150): string {
  const flat = prettifyRepr(text).replace(/\s+/g, " ").trim();
  const m = /^(.+?[.!?])(\s|$)/.exec(flat);
  return clipText(m?.[1] ?? flat, n);
}
/** First line of a thought for the collapsed detail row. */
export const firstLine = (text: string, n = 140) => clipText(prettifyRepr(text).split("\n")[0]?.trim() ?? "", n);

const GENERIC_DECISION = /submitted its result|^Coordinator finished$/i;
const isFinishMarker = (s: AgentStep) => (s.kind === "decision" && /^Event settled/i.test(s.text)) || (s.kind === "tool" && s.tool === "finish");
const isValidateMarker = (s: AgentStep) => (s.kind === "tool" && s.tool === "validate_plan") || (s.kind === "decision" && /validat/i.test(s.text));
const isExecuteMarker = (s: AgentStep) => s.kind === "rehearse" || s.kind === "audit" || s.kind === "execute" || (s.kind === "tool" && s.tool === "execute");

function metaOf(steps: OrchRow[]) {
  const times = steps.map((r) => Date.parse(r.step.t)).filter((t) => !Number.isNaN(t));
  const turns = steps.reduce((m, r) => Math.max(m, r.step.turn ?? 0), 0) || steps.filter((r) => r.step.kind === "thought").length;
  return {
    turns,
    tools: steps.filter((r) => r.step.kind === "tool").length,
    cost: steps.reduce((a, r) => a + (r.step.cost_usd ?? 0), 0),
    ms: times.length > 1 ? Math.max(...times) - Math.min(...times) : 0,
  };
}

const lastOf = (steps: OrchRow[], pred: (s: AgentStep) => boolean) => [...steps].reverse().find((r) => pred(r.step))?.step;

/* ---------- chips from data already in the trace ---------- */

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);
const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** Result chips of a specialist, from the structured data of its result message (`data.findings`, `data.actions_count`). */
function delegateChips(result: AgentStep | undefined, task: string | null): FlowChip[] {
  if (!result) return [];
  const d = (result.data ?? {}) as Record<string, unknown>;
  const f = (d.findings ?? {}) as Record<string, unknown>;
  const chips: FlowChip[] = [];
  const add = (n: number | null, text: (n: number) => string, tone: Tone = "ok") => {
    if (n !== null && n > 0) chips.push({ text: text(n), tone });
  };
  const actions = num(d.actions_count);
  if (task === "reschedule") {
    add(actions, (n) => plural(n, "move"));
    add(num(f.transfers), (n) => `${n} transferred`, "info");
    const unplaceable = Array.isArray(f.unplaceable) ? f.unplaceable.length : num(f.unplaceable);
    add(unplaceable, (n) => `${n} unplaceable`, "warn");
    add(num(f.already_built), (n) => `${n} already built`, "muted");
  } else if (task === "dealer_comms") {
    add(num(f.notices), (n) => plural(n, "notice"));
    add(num(f.stop_sales), (n) => plural(n, "stop-sale"));
  } else if (task === "loaners") {
    add(num(f.assignments), (n) => plural(n, "loaner"));
  } else if (task === "quality_hold") {
    add(num(f.holds), (n) => plural(n, "hold"));
    add(num(f.owner_contacts), (n) => plural(n, "owner contact"));
    add(num(f.unsold_to_stop), (n) => plural(n, "vehicle") + " to stop", "info");
  }
  if (chips.length === 0) {
    // an unknown task: show whatever numeric findings exist, then the action count
    for (const [k, v] of Object.entries(f)) add(num(v), (n) => `${n} ${k.replace(/_/g, " ")}`);
    if (chips.length === 0) add(actions, (n) => plural(n, "action"));
  }
  return chips;
}

function understandChips(steps: OrchRow[]): FlowChip[] {
  const reg = lastOf(steps, (s) => s.kind === "tool" && s.tool === "register_incidents");
  const incidents = ((reg?.result as { incidents?: { category?: string }[] } | null | undefined)?.incidents ?? []).filter((i) => typeof i?.category === "string");
  // a category field may itself list several ("plant_outage, supplier_delay"): count the categories, not the records
  const cats = incidents.flatMap((i) => (i.category as string).split(/\s*[,;]\s*/).filter(Boolean));
  if (cats.length === 0) return [];
  if (cats.length === 1 && cats[0] === "noise") return [{ text: "noise", tone: "muted" }];
  if (cats.length === 1 && cats[0] === "unconfirmed") return [{ text: "unconfirmed", tone: "info" }];
  return [{ text: `${plural(cats.length, "incident")}: ${cats.join(", ")}`, tone: "info" }];
}

function validateChips(steps: OrchRow[], ctx: FlowContext): FlowChip[] {
  const dec = lastOf(steps, (s) => s.kind === "decision" && /validat/i.test(s.text));
  const rounds = ctx.correctionRounds ?? steps.filter((r) => r.step.kind === "decision" && /correction/i.test(r.step.text)).length;
  const blocking = Number(/(\d+)\s+blocking/i.exec(dec?.text ?? "")?.[1] ?? "0");
  const rounds_ = plural(rounds, "correction round");
  if (!dec) return [];
  if (blocking > 0) return [{ text: `${plural(blocking, "blocking finding")} · ${rounds_}`, tone: "warn" }];
  return [{ text: `validators passed · ${rounds_}`, tone: rounds > 0 ? "warn" : "ok" }];
}

function executeChips(steps: OrchRow[]): FlowChip[] {
  const chips: FlowChip[] = [];
  const reh = lastOf(steps, (s) => s.kind === "rehearse");
  const r = /(\d+)\s+ok,\s*(\d+)\s+failed/i.exec(reh?.text ?? "");
  if (r) chips.push({ text: `pre-flight ${r[1]} ok${r[2] !== "0" ? ` · ${r[2]} failed` : ""}`, tone: r[2] === "0" ? "ok" : "fail" });
  const aud = lastOf(steps, (s) => s.kind === "audit");
  if (aud) chips.push(/^Auditor agrees/i.test(aud.text) ? { text: "auditor agrees", tone: "ok" } : { text: "auditor concern", tone: "warn" });
  const ex = lastOf(steps, (s) => s.kind === "execute");
  const m = /Executed\s+(\d+)\/(\d+)\s+writes\s+via\s+(\w+):\s*(\d+)\s+failed,\s*(\d+)\s+unknown,\s*(\d+)\s+skipped/i.exec(ex?.text ?? "");
  if (m) {
    const failed = Number(m[4]);
    const unknown = Number(m[5]);
    const skipped = Number(m[6]);
    const bad = failed + unknown + skipped;
    const parts = [`${m[1]} writes via ${(m[3] ?? "").toUpperCase()}`, `${failed} failed`, ...(unknown ? [`${unknown} unknown`] : []), `${skipped} skipped`];
    chips.push({ text: parts.join(" · "), tone: bad === 0 ? "ok" : failed + unknown > 0 ? "fail" : "warn" });
  }
  return chips;
}

function settledStatus(steps: OrchRow[], ctx: FlowContext): string | null {
  const dec = lastOf(steps, (s) => s.kind === "decision" && /^Event settled/i.test(s.text));
  return /^Event settled \((\w+)\)/i.exec(dec?.text ?? "")?.[1]?.toLowerCase() ?? ctx.status ?? null;
}

function finishChips(steps: OrchRow[], ctx: FlowContext): FlowChip[] {
  const status = settledStatus(steps, ctx);
  if (status === "escalated") {
    // the coordinator's own words ("E-02#1: escalated. Unconfirmed rumor regarding ...") say it best
    const said = ctx.escalationNote;
    const reason = ctx.escalations?.[0]?.reason ?? "";
    const head = said ?? reason.replace(/^[A-Z]-\d+#\d+\s*/, "").replace(/^\(([^)]*)\):?\s*/, "$1: ");
    return [{ text: `escalated: ${firstSentence(head, 64)}`, tone: "fail" }];
  }
  if (status === "noise") return [{ text: "noise · no action", tone: "muted" }];
  if (status === "failed") return [{ text: "failed · escalated", tone: "fail" }];
  if (status === "done") return [{ text: "settled: done", tone: "ok" }];
  return [];
}

/* ---------- grouping ---------- */

const GENERIC_SUMMARY = (r: OrchRow) => GENERIC_DECISION.test(r.step.text);

function summaryFor(kind: NodeKind, steps: OrchRow[], result: AgentStep | undefined): string {
  const decision = lastOf(steps, (s) => s.kind === "decision" && !GENERIC_DECISION.test(s.text));
  const thought = lastOf(steps, (s) => s.kind === "thought");
  if (kind === "delegate") return firstSentence(result?.text ?? thought?.text ?? "");
  if (kind === "finish") {
    const settled = lastOf(steps, (s) => s.kind === "decision" && /^Event settled/i.test(s.text));
    if (settled) return firstSentence(settled.text.replace(/^Event settled \(\w+\):\s*/i, ""));
  }
  if (kind === "execute") {
    const ex = lastOf(steps, (s) => s.kind === "execute");
    if (ex) return firstSentence(ex.text);
  }
  return firstSentence(decision?.text ?? thought?.text ?? steps.find((r) => !GENERIC_SUMMARY(r))?.step.text ?? "");
}

/** Assign coordinator steps to a stage by the contract's `task` (phase) when every one of them carries it. */
function byPhase(steps: OrchRow[]): Record<string, OrchRow[]> | null {
  if (steps.length === 0 || !steps.every((r) => ["understand", "delegate", "validate", "execute", "finish"].includes(r.step.task ?? ""))) return null;
  const out: Record<string, OrchRow[]> = {};
  for (const r of steps) (out[r.step.task as string] ??= []).push(r);
  return out;
}

export function buildFlow(rows: OrchRow[], context: FlowContext = {}): Flow {
  const note = /escalated\.\s*(.+)$/is.exec(lastOf(rows, (s) => s.kind === "decision" && /escalated\./i.test(s.text))?.text ?? "")?.[1];
  const ctx: FlowContext = { ...context, escalationNote: note };
  const nodes: FlowNode[] = [];
  const push = (n: Omit<FlowNode, "turns" | "tools" | "cost" | "ms" | "row">) => nodes.push({ ...n, row: n.kind === "delegate" ? "bottom" : "top", ...metaOf(n.steps) });

  let pending: OrchRow[] = []; // coordinator steps since the last boundary
  let open: { lane: LaneId; task: string | null; incident: string | null; steps: OrchRow[] } | null = null;
  let delegations = 0;

  const closeDelegation = () => {
    if (!open) return;
    delegations += 1;
    const resultMsg = [...open.steps].reverse().find((r) => r.step.kind === "message" && String(r.step.to_agent ?? "") === "coordinator")?.step;
    push({
      id: `delegate:${delegations}`,
      kind: "delegate",
      lane: open.lane,
      // the card names its agent on the top line (from the lane), so the stage title here is the job it was given
      title: taskLabel(open.task).replace(/^./, (c) => c.toUpperCase()),
      subtitle: open.incident ?? "",
      summary: summaryFor("delegate", open.steps, resultMsg),
      chips: delegateChips(resultMsg, open.task),
      steps: open.steps,
      task: open.task,
      incident: open.incident,
    });
    open = null;
  };

  for (const r of rows) {
    const s = r.step;
    const toSpecialist = s.kind === "message" && s.to_agent && String(s.to_agent) !== "coordinator" && String(s.from_agent ?? "coordinator") === "coordinator";
    if (toSpecialist) {
      // the brief starts a delegation: whatever the coordinator did before it is the understanding (first time) or a hand-off hub
      if (pending.length > 0) {
        if (nodes.length === 0) {
          push({ id: "understand", kind: "understand", lane: "coordinator", title: "Understand the message", subtitle: "read, resolve, gate", summary: summaryFor("understand", pending, undefined), chips: understandChips(pending), steps: pending, task: "understand", incident: null });
        } else {
          push({ id: `hub:${delegations + 1}`, kind: "hub", lane: "coordinator", title: "Coordinator", subtitle: "reviews and hands off", summary: summaryFor("hub", pending, undefined), chips: [], steps: pending, task: "delegate", incident: null });
        }
        pending = [];
      }
      const d = (s.data ?? {}) as Record<string, unknown>;
      open = {
        lane: laneOf(s.to_agent as AgentId),
        task: s.task ?? (typeof d.task === "string" ? d.task : null),
        incident: typeof d.incident_id === "string" ? d.incident_id : null,
        steps: [r],
      };
      continue;
    }
    if (open) {
      open.steps.push(r);
      const back = s.kind === "message" && String(s.to_agent ?? "") === "coordinator";
      if (back) closeDelegation();
      continue;
    }
    pending.push(r);
  }
  if (open) {
    // a run in progress: the delegation has not reported back yet
    closeDelegation();
  }

  // what is left is coordinator work after the last delegation (or the whole event when nothing was delegated)
  const phases = byPhase(pending);
  const settled = pending.findIndex((r) => isFinishMarker(r.step));
  const finStart = settled >= 0 ? settled : pending.length;
  const execStart = pending.findIndex((r) => isExecuteMarker(r.step));
  const stage = (kind: NodeKind, steps: OrchRow[], title: string, subtitle: string, chips: FlowChip[]) => {
    if (steps.length === 0) return;
    push({ id: kind, kind, lane: "coordinator", title, subtitle, summary: summaryFor(kind, steps, undefined), chips, steps, task: kind, incident: null });
  };
  if (phases) {
    const get = (k: string) => phases[k] ?? [];
    if (delegations === 0) {
      const first = [...get("understand"), ...get("delegate"), ...get("validate")];
      const last = [...get("execute"), ...get("finish")];
      stage("understand", first, "Understand the message", "read, resolve, gate", understandChips(first));
      stage("finish", last, "Finish", "settle and explain", finishChips(last, ctx));
    } else {
      // coordinator steps tagged understand/delegate that come after the last specialist returned (it reviewing the results)
      // belong to the validation stage; dropping them would lose steps from the trace
      const validating = pending.filter((r) => ["understand", "delegate", "validate"].includes(r.step.task ?? ""));
      stage("validate", validating, "Validate the plan", "handbook rules as code", validateChips(validating, ctx));
      stage("execute", get("execute"), "Pre-flight, audit, execute", "sandbox check, second model, MCP", executeChips(get("execute")));
      stage("finish", get("finish"), "Finish", "settle and explain", finishChips(get("finish"), ctx));
    }
  } else if (delegations === 0) {
    // nothing was delegated (noise, unconfirmed, or still reading): understand, then finish
    const cut = settled >= 0 ? settled : pending.length;
    const rest = pending.slice(cut);
    stage("understand", pending.slice(0, cut), "Understand the message", "read, resolve, gate", understandChips(pending));
    stage("finish", rest, "Finish", "settle and explain", finishChips(rest, ctx));
  } else if (ctx.live && !pending.some((r) => isValidateMarker(r.step) || isExecuteMarker(r.step) || isFinishMarker(r.step))) {
    // still deciding what comes next: these steps become the next hand-off hub, so do not give them a stage identity yet
  } else {
    const validateEnd = execStart >= 0 && execStart < finStart ? execStart : finStart;
    const execEnd = finStart;
    stage("validate", pending.slice(0, validateEnd), "Validate the plan", "handbook rules as code", validateChips(pending.slice(0, validateEnd), ctx));
    if (execStart >= 0 && execStart < finStart) {
      const ex = pending.slice(execStart, execEnd);
      stage("execute", ex, "Pre-flight, audit, execute", "sandbox check, second model, MCP", executeChips(ex));
    }
    const fin = pending.slice(finStart);
    stage("finish", fin, "Finish", "settle and explain", finishChips(fin, ctx));
  }

  // hand-off subtitles: say who the hub passes the baton to
  nodes.forEach((n, i) => {
    if (n.kind === "hub") {
      const next = nodes[i + 1];
      if (next?.kind === "delegate") n.subtitle = `hands off to ${next.title} · ${next.subtitle}`;
    }
  });

  // edges: the briefs go down, the results come back up, the coordinator's own stages are chained across
  const edges: FlowEdge[] = [];
  for (let i = 1; i < nodes.length; i++) {
    const a = nodes[i - 1] as FlowNode;
    const b = nodes[i] as FlowNode;
    if (a.row === "top" && b.row === "bottom") edges.push({ from: a.id, to: b.id, dir: "down", label: taskLabel(b.task) });
    else if (a.row === "bottom" && b.row === "top") edges.push({ from: a.id, to: b.id, dir: "up", label: a.chips[0]?.text ?? "result" });
    else if (a.row === "bottom" && b.row === "bottom") edges.push({ from: a.id, to: b.id, dir: "across", label: "" });
    else edges.push({ from: a.id, to: b.id, dir: "across", label: "" });
  }
  return { nodes, edges };
}
