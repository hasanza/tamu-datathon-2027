import type { GraphEdge, GraphNode, NodeType } from "../api/types";

/** Left-to-right "cause -> impact" rank of each node type. */
const RANK: Record<NodeType, number> = {
  Event: -1, // the message sits left of everything it mentions
  Supplier: 0,
  Shipment: 0,
  Lot: 0,
  Part: 1,
  Model: 2,
  Plant: 2,
  Day: 3,
  ProductionOrder: 3,
  CustomerOrder: 4,
  Vehicle: 4,
  Dealer: 5,
  Customer: 5,
};

/**
 * Deterministic layered layout. Columns are the type ranks; inside a column nodes are ordered by the mean
 * row of their already-placed neighbours (one barycentre sweep) so most edges stay short and uncrossed.
 */
export function layeredPositions(
  nodes: GraphNode[],
  edges: GraphEdge[],
  dx = 210,
  dy = 40,
): Record<string, { x: number; y: number }> {
  const cols = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const r = RANK[n.type] ?? 3;
    cols.set(r, [...(cols.get(r) ?? []), n]);
  }
  const adj = new Map<string, string[]>();
  for (const e of edges) {
    adj.set(e.from, [...(adj.get(e.from) ?? []), e.to]);
    adj.set(e.to, [...(adj.get(e.to) ?? []), e.from]);
  }
  const y = new Map<string, number>();
  const pos: Record<string, { x: number; y: number }> = {};
  const ranks = [...cols.keys()].sort((a, b) => a - b);
  // compact: drop empty columns so the graph does not have blank gutters
  ranks.forEach((r, ci) => {
    const col = cols.get(r) ?? [];
    const score = (n: GraphNode) => {
      const ys = (adj.get(n.id) ?? []).map((m) => y.get(m)).filter((v): v is number => v !== undefined);
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : Number.POSITIVE_INFINITY;
    };
    col.sort((a, b) => score(a) - score(b) || a.type.localeCompare(b.type) || a.id.localeCompare(b.id));
    col.forEach((n, i) => {
      const yy = (i - (col.length - 1) / 2) * dy;
      y.set(n.id, yy);
      pos[n.id] = { x: ci * dx, y: yy };
    });
  });
  return pos;
}
