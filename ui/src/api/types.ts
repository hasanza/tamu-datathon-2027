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
/** v1 trace ids (traces/snapshot) and v2 ids (PLAN_V2 §7). Both are valid; lib/meta.ts maps them onto the four lanes. */
export type AgentId =
  | "coordinator"
  | "supply_chain"
  | "dealer_care"
  | "quality"
  | "supply_chain_planner"
  | "dealer_network"
  | "customer_care_quality";
/** How a call reached the enterprise (contracts v0.2.0): the MCP client, a dry-run in-process copy ("twin" in old traces), or plain code. */
export type Transport = "mcp/stdio" | "twin" | "in-process";

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
  | "Day"
  // v2 (PLAN_V2 §6): noise and unconfirmed events get a minimal path Event -MENTIONS-> entity
  | "Event";
export type StepKind =
  // v1
  | "llm"
  | "graph"
  | "plan"
  | "rehearse"
  | "audit"
  | "execute"
  | "gate"
  | "note"
  // v2 (PLAN_V2 §7)
  | "thought"
  | "tool"
  | "message"
  | "decision";

export interface FeedEvent {
  event_id: string;
  received_at: string;
  source: string;
  text: string;
  status: Status;
  category: EventCategory | null;
  confidence: number | null;
  /** true for an event typed in by a user (runs against a private sandbox server, never the scored one) */
  custom?: boolean;
  /** custom events created by "Add details and re-run": the event this one follows up on */
  parent_id?: string | null;
}

/** Custom events are ids C-nn; they run against a private sandbox server and live in traces/custom. */
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
  // v2 additions, all optional so v1 traces stay valid
  /** contract 0.2.1: coordinator steps carry their phase (understand | delegate | validate | execute | finish), specialist steps
   *  the delegated task (reschedule | dealer_comms | loaners | quality_hold). Null on older traces. */
  task?: string | null;
  turn?: number | null;
  tool?: string | null;
  args?: Record<string, unknown> | null;
  result?: Record<string, unknown> | null;
  to_agent?: AgentId | null;
  from_agent?: AgentId | null;
  transport?: Transport | null;
  model?: string | null;
  cost_usd?: number | null;
}
export interface AgentRun {
  agent: AgentId;
  started: string;
  ended: string | null;
  steps: AgentStep[];
  model?: string | null;
  llm_calls?: number;
  cost_usd?: number;
}

export interface Orchestration {
  /** contract 0.2.2: where the calls went. Absent on older traces (see lib/target.ts for the fallback). */
  target?: "scored" | "sandbox" | "dry" | null;
  mode: "sequential" | "parallel";
  correction_rounds: number;
  escalations: { incident_id: string; reason: string }[];
  mcp_transport: string | null;
}

/** What came back from a call. `outcome` (v0.2.0): ok; failed = the server rejected it; unknown = transport failure
 *  (an MCP timeout or exception: the write may or may not have happened, so the event stops and escalates). */
export interface ToolResult {
  ok: boolean;
  error: string | null;
  response: Record<string, unknown> | null;
  http_status?: number | null;
  outcome?: "ok" | "failed" | "unknown" | null;
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
  result: ToolResult | null;
  transport?: Transport | null;
  /** v2: true when a failed write made this call not run ("skipped: dependency failed") */
  skipped?: boolean;
  /** v2: an event-wide notice lists every incident it serves */
  incident_ids?: string[];
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
  purpose: "extract" | "audit" | "summarize" | "resolve" | "paraphrase" | "agent_turn";
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  cached: boolean;
  /** v0.2.0: how many tries the call took (a schema error retries once) */
  attempts?: number;
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
  /** v2 only (contracts v0.2.0) */
  orchestration?: Orchestration | null;
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
