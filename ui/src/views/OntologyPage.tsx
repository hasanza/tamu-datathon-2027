import { useRef, useState } from "react";
import { Maximize2, Tags } from "lucide-react";
import type { GraphEdge, GraphNode, NodeType } from "../api/types";
import { CytoGraph, type CytoHandle } from "../components/CytoGraph";
import { Chip, Mono, Panel } from "../components/ui/primitives";
import { NODE_COLOR } from "../lib/meta";

// Mirrors ONTOLOGY in src/control_tower/graph/ontology.py (from type, edge type, to type).
type OntologyNode = Exclude<NodeType, "Event">; // Event nodes exist only inside a trace's paths, not in the company graph
const ONTOLOGY: [OntologyNode, string, OntologyNode][] = [
  ["Supplier", "SUPPLIES", "Part"],
  ["Shipment", "OF_PART", "Part"],
  ["Shipment", "TO_PLANT", "Plant"],
  ["Shipment", "FROM", "Supplier"],
  ["Model", "USES_PART", "Part"],
  ["Plant", "BUILDS_MODEL", "Model"],
  ["ProductionOrder", "AT_PLANT", "Plant"],
  ["ProductionOrder", "OF_MODEL", "Model"],
  ["ProductionOrder", "ON_DAY", "Day"],
  ["CustomerOrder", "FULFILLED_BY", "ProductionOrder"],
  ["CustomerOrder", "SOLD_BY", "Dealer"],
  ["CustomerOrder", "FOR", "Customer"],
  ["Lot", "OF_PART", "Part"],
  ["Lot", "AT_PLANT", "Plant"],
  ["Lot", "FROM", "Supplier"],
  ["Vehicle", "BUILT_BY", "ProductionOrder"],
  ["Vehicle", "AT_DEALER", "Dealer"],
  ["Vehicle", "OWNED_BY", "Customer"],
];

const POS: Record<OntologyNode, { x: number; y: number }> = {
  Supplier: { x: 0, y: 160 },
  Shipment: { x: 210, y: 130 },
  Lot: { x: 200, y: 280 },
  Part: { x: 440, y: -50 },
  Model: { x: 700, y: -50 },
  Plant: { x: 560, y: 170 },
  ProductionOrder: { x: 820, y: 190 },
  Day: { x: 1060, y: 40 },
  CustomerOrder: { x: 1060, y: 190 },
  Vehicle: { x: 1060, y: 370 },
  Dealer: { x: 1300, y: 140 },
  Customer: { x: 1300, y: 340 },
};

const NOTE: Record<OntologyNode, string> = {
  Supplier: "Company that ships parts",
  Part: "Component built into vehicle models",
  Model: "Vehicle model (bill of materials)",
  Plant: "Factory with daily build slots",
  Shipment: "Inbound parts delivery with an ETA",
  ProductionOrder: "A build slot: model, plant, day",
  CustomerOrder: "A sold car awaiting its production order",
  Customer: "Owner, with a loyalty tier",
  Dealer: "Sells and services vehicles",
  Lot: "Batch of a part used in a build window",
  Vehicle: "A built car with a VIN",
  Day: "Working day on the calendar",
};

const NODES: GraphNode[] = (Object.keys(POS) as OntologyNode[]).map((t) => ({ id: t, type: t, label: t, group: null, count: null }));
const EDGES: GraphEdge[] = ONTOLOGY.map(([from, type, to]) => ({ from, to, type }));
const EDGE_TYPES = new Set(ONTOLOGY.map((o) => o[1]));

export function OntologyPage() {
  const handle = useRef<CytoHandle>(null);
  const [labels, setLabels] = useState(true);
  const [sel, setSel] = useState<string | null>(null);
  const selType = sel as OntologyNode | null;
  const touching = selType ? ONTOLOGY.filter(([a, , b]) => a === selType || b === selType) : [];
  const hlNodes = selType ? new Set([selType, ...touching.flatMap(([a, , b]) => [a, b])]) : null;
  const hlEdges = selType ? new Set(touching.map(([a, t, b]) => `${a}|${b}|${t}`)) : null;

  return (
    <div className="mx-auto max-w-[1500px] space-y-4 p-4">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">Ontology</h2>
        <p className="mt-1 max-w-3xl text-[13px] text-tx2">
          The company as a typed property graph: <b>{NODES.length} node types</b> and <b>{EDGE_TYPES.size} edge types</b>. Every incident is
          resolved to ids in this graph, and the agents walk it (shipment to plant to production order to customer order to dealer) instead of
          guessing. Click a type to see its relations.
        </p>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_320px]">
        <Panel
          title="Schema"
          action={
            <div className="flex gap-1">
              <button onClick={() => setLabels(!labels)} aria-pressed={labels} aria-label="Toggle edge labels" className={`rounded-md border p-1.5 ${labels ? "border-brand-bright text-tx" : "border-line text-tx2"}`}>
                <Tags size={14} />
              </button>
              <button onClick={() => handle.current?.fit()} aria-label="Fit to screen" className="rounded-md border border-line p-1.5 text-tx2 hover:text-tx">
                <Maximize2 size={14} />
              </button>
            </div>
          }
        >
          <CytoGraph
            ref={handle}
            nodes={NODES}
            edges={EDGES}
            positions={POS}
            edgeLabels={labels}
            big
            highlightNodes={hlNodes}
            highlightEdges={hlEdges}
            selectedId={sel}
            onSelect={setSel}
            height={520}
            label="Ontology schema diagram with 12 node types and 15 edge types"
          />
          <ul className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-tx2" aria-label="Node type legend">
            {NODES.map((n) => (
              <li key={n.id} className="flex items-center gap-1.5">
                <span className="h-2.5 w-2.5 rounded-full border border-line" style={{ background: NODE_COLOR[n.type] }} aria-hidden />
                {n.type}
              </li>
            ))}
          </ul>
        </Panel>
        <Panel title={selType ?? "Node types"}>
          {selType ? (
            <div className="space-y-2 text-[13px]">
              <p className="text-tx2">{NOTE[selType]}</p>
              <ul className="space-y-1">
                {touching.map(([a, t, b]) => (
                  <li key={`${a}${t}${b}`} className="mono text-[12px] text-tx2">
                    {a} <span className="text-brand-bright">{t}</span> {b}
                  </li>
                ))}
              </ul>
              <button onClick={() => setSel(null)} className="text-xs text-tx3 hover:text-tx">Clear selection</button>
            </div>
          ) : (
            <ul className="space-y-1.5">
              {NODES.map((n) => (
                <li key={n.id}>
                  <button onClick={() => setSel(n.id)} className="flex w-full items-start gap-2 rounded-md px-1 py-0.5 text-left hover:bg-surface-2">
                    <Chip color={NODE_COLOR[n.type]}>{n.type}</Chip>
                    <span className="text-xs text-tx2">{NOTE[n.type as OntologyNode]}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-3 border-t border-line pt-2 text-[11px] text-tx3">
            Large sets (for example the customers behind a production order) are drawn as a collapsed <Mono>grp:</Mono> node with a count.
          </p>
        </Panel>
      </div>
    </div>
  );
}
