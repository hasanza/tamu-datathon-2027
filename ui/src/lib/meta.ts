import type { AgentId, EventCategory, NodeType, Status, StepKind } from "../api/types";

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

export const AGENT_META: Record<AgentId, { label: string; blurb: string }> = {
  coordinator: { label: "Coordinator", blurb: "Understands the event, gates on confidence, rehearses and executes" },
  supply_chain: { label: "Supply Chain Planner", blurb: "Finds affected production orders and re-plans them" },
  dealer_care: { label: "Dealer & Customer Care", blurb: "Notifies dealers, assigns loaners" },
  quality: { label: "Quality", blurb: "Holds lots, stops sale, contacts owners" },
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
