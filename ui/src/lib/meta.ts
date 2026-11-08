import type { AgentId, EventCategory, NodeType, Status, StepKind, Transport } from "../api/types";
import { TARGET_META, type Target } from "./target";

export const CATEGORY_META: Record<EventCategory, { label: string; color: string }> = {
  supplier_delay: { label: "Supplier delay", color: "var(--cat-delay)" },
  plant_outage: { label: "Plant outage", color: "var(--cat-outage)" },
  quality_hold: { label: "Quality hold", color: "var(--cat-quality)" },
  noise: { label: "Noise", color: "var(--cat-noise)" },
  unconfirmed: { label: "Unconfirmed", color: "var(--cat-unconfirmed)" },
  compound: { label: "Compound", color: "var(--cat-compound)" },
};

export const STATUS_META: Record<Status, { label: string; color: string }> = {
  queued: { label: "Queued", color: "var(--text-3)" },
  processing: { label: "Processing", color: "var(--brand-bright)" },
  done: { label: "Done", color: "var(--ok)" },
  escalated: { label: "Escalated", color: "var(--cat-unconfirmed)" },
  noise: { label: "Noise", color: "var(--cat-noise)" },
  failed: { label: "Failed", color: "var(--fail)" },
};

/** The four lanes of the Orchestration view, in display order (PLAN_V2 §2.1). */
export type LaneId = "coordinator" | "supply_chain_planner" | "dealer_network" | "customer_care_quality";
export const LANES: LaneId[] = ["coordinator", "supply_chain_planner", "dealer_network", "customer_care_quality"];

/** v1 agent ids still appear in traces/snapshot; map them onto the v2 lanes. */
export const laneOf = (agent: AgentId): LaneId =>
  agent === "supply_chain" ? "supply_chain_planner"
  : agent === "dealer_care" ? "dealer_network"
  : agent === "quality" ? "customer_care_quality"
  : agent;

export const LANE_META: Record<LaneId, { label: string; blurb: string; color: string }> = {
  coordinator: { label: "Coordinator", blurb: "Understands, gates, delegates, validates, executes", color: "var(--brand-bright)" },
  supply_chain_planner: { label: "Supply Chain Planner", blurb: "Affected builds and the earliest feasible slots", color: "var(--cat-delay)" },
  dealer_network: { label: "Dealer Network", blurb: "One notice per dealer, stop-sale of unsold vehicles", color: "var(--cat-unconfirmed)" },
  customer_care_quality: { label: "Customer Care & Quality", blurb: "Loaners by priority, lot holds, owner contact", color: "var(--cat-quality)" },
};

/** Kept for code that still looks agents up by id (both v1 and v2 ids work). */
export const AGENT_META: Record<AgentId, { label: string; blurb: string }> = {
  coordinator: LANE_META.coordinator,
  supply_chain_planner: LANE_META.supply_chain_planner,
  dealer_network: LANE_META.dealer_network,
  customer_care_quality: LANE_META.customer_care_quality,
  supply_chain: LANE_META.supply_chain_planner,
  dealer_care: LANE_META.dealer_network,
  quality: LANE_META.customer_care_quality,
};

export const STEP_META: Record<StepKind, { label: string; color: string }> = {
  llm: { label: "LLM", color: "var(--cat-quality)" },
  graph: { label: "Graph", color: "var(--cat-unconfirmed)" },
  plan: { label: "Plan", color: "var(--cat-delay)" },
  rehearse: { label: "Rehearse", color: "var(--cat-compound)" },
  audit: { label: "Audit", color: "var(--cat-outage)" },
  execute: { label: "Execute", color: "var(--ok)" },
  gate: { label: "Gate", color: "var(--text-2)" },
  note: { label: "Note", color: "var(--text-3)" },
  thought: { label: "Thought", color: "var(--text-3)" },
  tool: { label: "Tool call", color: "var(--cat-unconfirmed)" },
  message: { label: "Message", color: "var(--cat-delay)" },
  decision: { label: "Decision", color: "var(--cat-compound)" },
};

/** What kind of tool a v2 tool call is (PLAN_V2 §3.1): graph traversal, deterministic code, or coordinator control. */
const GRAPH_TOOLS = new Set(["affected_builds", "customer_orders_of", "match_lot", "affected_vehicles", "eligible_customers"]);
const CODE_TOOLS = new Set([
  "register_incidents", "resolve_entity", "resolve_date", "validate_plan", "propose_slots", "compose_notices",
  "compose_stop_sales", "rank_and_assign", "compose_hold", "compose_owner_contacts",
]);
export type ToolBadge = "MCP" | "dry run" | "graph" | "code" | "control";
export function toolBadge(step: { tool?: string | null; transport?: Transport | null }): ToolBadge {
  if (step.transport === "mcp/stdio") return "MCP";
  if (step.transport === "twin") return "dry run"; // old traces / developer dry runs: an in-process copy, nothing sent to a server
  const t = step.tool ?? "";
  if (GRAPH_TOOLS.has(t)) return "graph";
  if (CODE_TOOLS.has(t)) return "code";
  return "control";
}
/** Label and colour for how a call reached the enterprise (contracts v0.2.0); null for v1 traces, which do not record it.
 *  An MCP call says which server it went to: "MCP → sandbox server" or "MCP → scored server". */
export function transportMeta(t: Transport | null | undefined, target: Target = "scored"): { label: string; color: string } | null {
  if (!t) return null;
  if (t === "mcp/stdio") return { label: `MCP → ${target === "dry" ? "dry run" : `${TARGET_META[target].short} server`}`, color: TARGET_META[target].color };
  if (t === "twin") return { label: "dry run", color: "var(--text-3)" };
  return { label: "in-process", color: "var(--text-3)" };
}
export const BADGE_COLOR: Record<ToolBadge, string> = {
  MCP: "var(--ok)",
  "dry run": "var(--text-3)",
  graph: "var(--cat-unconfirmed)",
  code: "var(--cat-delay)",
  control: "var(--text-3)",
};

/** Node colors by type (docs/BRAND.md). Day is not in BRAND.md; it gets a muted neutral. */
export const NODE_COLOR: Record<NodeType, string> = {
  Plant: "#ff5a36",
  Supplier: "#3b82f6",
  Part: "#8b5cf6",
  Model: "#c9cac8",
  Shipment: "#e6a100",
  Lot: "#8b5cf6",
  ProductionOrder: "var(--po-node)",
  CustomerOrder: "#2fa66a",
  Dealer: "#b30000",
  Customer: "#e6a100",
  Vehicle: "#747474",
  Day: "#4d6a8a",
  Event: "#7a8aa0", // not in BRAND.md either: the message itself, a muted blue-grey
};

export const NODE_TYPES = Object.keys(NODE_COLOR) as NodeType[];

export function sourceIconName(source: string): "chat" | "news" | "quality" | "mail" | "digest" | "alert" | "radio" {
  const s = source.toLowerCase();
  if (s.includes("chat")) return "chat";
  if (s.includes("news")) return "news";
  if (s.includes("quality")) return "quality";
  if (s.includes("mail")) return "mail";
  if (s.includes("digest")) return "digest";
  if (s.includes("alert")) return "alert";
  return "radio";
}
