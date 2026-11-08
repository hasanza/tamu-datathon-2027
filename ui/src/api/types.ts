// Hand-written mirror of src/control_tower/schemas/*.py and the api/app.py responses.

export type Category = "supplier_delay" | "plant_outage" | "quality_hold" | "noise" | "unconfirmed";
export type EventCategory = Category | "compound";
export type Status = "queued" | "processing" | "done" | "escalated" | "noise" | "failed";

export type Tool =
  | "mes.get_schedule"
  | "mes.reschedule"
  | "mes.transfer"
  | "dealer.notify"
  | "dealer.stop_sale"
  | "crm.loaner_availability"
  | "crm.assign_loaner"
  | "crm.notify_customer"
  | "quality.hold_lot"
  | "escalate";
export type AgentId = "coordinator" | "supply_chain" | "dealer_care" | "quality";

export const WRITE_TOOLS: ReadonlySet<string> = new Set([
  "mes.reschedule",
  "mes.transfer",
  "dealer.notify",
  "dealer.stop_sale",
  "crm.assign_loaner",
  "crm.notify_customer",
  "quality.hold_lot",
]);

export type NodeType =
  | "Supplier"
  | "Part"
  | "Model"
  | "Plant"
  | "Shipment"
  | "ProductionOrder"
  | "CustomerOrder"
  | "Customer"
  | "Dealer"
  | "Lot"
  | "Vehicle"
  | "Day";
export type StepKind = "llm" | "graph" | "plan" | "rehearse" | "audit" | "execute" | "gate" | "note";

export interface FeedEvent {
  event_id: string;
  received_at: string;
  source: string;
  text: string;
  status: Status;
  category: EventCategory | null;
  confidence: number | null;
  /** true for an event typed in by a user (sandbox: twin only, never the real server) */
  custom?: boolean;
  /** custom events created by "Add details and re-run": the event this one follows up on */
  parent_id?: string | null;
}

/** Custom events are ids C-nn; they run on the twin only and live in traces/custom. */
export const isCustomId = (id: string) => /^C-\d{2}$/.test(id);
/** C-14 -> 14 (newest custom event has the highest number); 0 for anything else. */
export const customNumber = (id: string) => (isCustomId(id) ? Number(id.slice(2)) : 0);

export interface ResolutionStep {
  mention: string;
  entity_type: string;
  candidates: string[];
  chosen: string | null;
  method: string;
  note: string | null;
}
export interface Ambiguity {
  field: string;
  issue: string;
  options: string[];
  blocking: boolean;
}
export interface Incident {
  incident_id: string;
  event_id: string;
  category: Category;
  confidence: number;
  plant_id: string | null;
  part_id: string | null;
  supplier_id: string | null;
  shipment_id: string | null;
  lot_id: string | null;
  orig_eta: string | null;
  new_eta: string | null;
  outage_start: string | null;
  outage_end: string | null;
  build_window_start: string | null;
  build_window_end: string | null;
  raw_mentions: Record<string, string>;
  resolution_steps: ResolutionStep[];
  ambiguities: Ambiguity[];
  reason: string;
}

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  group: string | null;
  count: number | null;
}
export interface GraphEdge {
  from: string;
  to: string;
  type: string;
}
export interface GraphPath {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AgentStep {
  t: string;
  kind: StepKind;
  text: string;
  data: Record<string, unknown> | null;
}
export interface AgentRun {
  agent: AgentId;
  started: string;
  ended: string | null;
  steps: AgentStep[];
}

export interface Action {
  seq: number;
  incident_id: string | null;
  agent: AgentId;
  tool: Tool;
  args: Record<string, unknown>;
  justification: string;
  path_ids: string[];
  rehearsal: { ok: boolean; error: string | null } | null;
  result: { ok: boolean; error: string | null; response: Record<string, unknown> | null } | null;
}

export interface MovedPO {
  production_order_id: string;
  kind: "reschedule" | "transfer";
  from_plant: string;
  from_date: string;
  to_plant: string;
  to_date: string;
}
export interface WorldDiff {
  moved_pos: MovedPO[];
  notified_dealers: { dealer_id: string; customer_order_ids: string[] }[];
  loaners: string[];
  held_lots: string[];
  stopped_vins: string[];
  contacted_customers: string[];
}
export interface Counterfactual {
  customers_affected: number;
  avg_slip_days: number | null;
  loaners_entitled: number;
  loaners_assigned: number;
  vehicles_pulled: number;
  owners_contacted: number;
}
export interface LLMCall {
  provider: string;
  model: string;
  purpose: "extract" | "audit" | "summarize" | "resolve" | "paraphrase";
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  cached: boolean;
}

export interface Trace {
  pipeline_version: string;
  event_id: string;
  received_at: string;
  source: string;
  text: string;
  status: Status;
  classification: { category: EventCategory; confidence: number; reason: string };
  incidents: Incident[];
  paths: Record<string, GraphPath[]>;
  agents: AgentRun[];
  actions: Action[];
  world_diff: WorldDiff;
  counterfactual: Counterfactual | null;
  llm: { calls: LLMCall[]; total_cost_usd: number };
  summary: string;
  decision_reason: string;
}

/** Row of GET /api/actions (the enterprise server's action_log.jsonl plus line and write flag). */
export interface LogRow {
  line: number;
  event_id: string;
  tool: string;
  args: Record<string, unknown>;
  ok: boolean;
  write: boolean;
}

export interface Kpis {
  events_total: number;
  events_with_trace: number;
  by_status: Record<string, number>;
  actions: number;
  writes: number;
  failed: number;
  escalations: number;
  cost_usd: number;
  llm_calls: number;
  models: string[];
}

export type StreamType = "event_received" | "agent_step" | "action" | "event_done";

export type RunMode = "dry" | "server";
/** GET /api/run/status. `mode` is null until a run was started in this API session (and after a reset). */
export interface RunStatus {
  running: boolean;
  mode: RunMode | null;
  exit_code: number | null;
  started: number | null;
}
