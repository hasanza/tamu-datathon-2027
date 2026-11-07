import { useMemo, useRef, useState } from "react";
import { Maximize2, Minus, Plus, Tags, X } from "lucide-react";
import { useGraph } from "../api/hooks";
import type { GraphEdge, GraphNode, GraphPath, Trace } from "../api/types";
import { CytoGraph, edgeKey, type CytoHandle } from "../components/CytoGraph";
import { CategoryBadge, Chip, Empty, ErrorBox, Loading, Mono, Panel } from "../components/ui/primitives";
import { layeredPositions } from "../lib/layout";
import { NODE_COLOR } from "../lib/meta";

interface Highlight {
  nodes: Set<string>;
  edges: Set<string>;
}

function pathHighlight(paths: GraphPath[]): Highlight {
  const nodes = new Set<string>();
  const edges = new Set<string>();
  for (const p of paths) {
    p.nodes.forEach((n) => nodes.add(n.id));
    p.edges.forEach((e) => edges.add(edgeKey(e)));
  }
  return { nodes, edges };
}

function idsHighlight(ids: string[], graphEdges: GraphEdge[]): Highlight {
  const nodes = new Set(ids);
  const edges = new Set(graphEdges.filter((e) => nodes.has(e.from) && nodes.has(e.to)).map(edgeKey));
  return { nodes, edges };
}

const pathLabel = (p: GraphPath) =>
  p.nodes.map((n) => (n.group ? `+${n.count ?? "?"} ${n.group.replace("_", " ")}` : n.id)).join(" → ");

function Legend({ types }: { types: string[] }) {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-tx2" aria-label="Legend">
      {types.map((t) => (
        <li key={t} className="flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full border border-line" style={{ background: NODE_COLOR[t as keyof typeof NODE_COLOR] }} aria-hidden />
          {t}
        </li>
      ))}
      <li className="flex items-center gap-1.5">
        <span className="h-3 w-5 rounded-sm border border-dashed border-tx3" aria-hidden /> collapsed set (+N)
      </li>
      <li className="flex items-center gap-1.5">
        <span className="h-0.5 w-5 bg-brand-bright" aria-hidden /> highlighted path
      </li>
    </ul>
  );
}

export function GraphTab({ trace, focus, onClearFocus }: { trace: Trace; focus: string[] | null; onClearFocus: () => void }) {
  const q = useGraph(trace.event_id, true);
  const handle = useRef<CytoHandle>(null);
  const [incident, setIncident] = useState<string>("all");
  const [pinned, setPinned] = useState<{ inc: string; idx: number } | null>(null);
  const [hover, setHover] = useState<{ inc: string; idx: number } | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [labels, setLabels] = useState(false);
  const [showAll, setShowAll] = useState<Set<string>>(new Set());

  const graph = q.data;
  const positions = useMemo(() => (graph ? layeredPositions(graph.nodes, graph.edges) : undefined), [graph]);

  const highlight: Highlight | null = useMemo(() => {
    if (!graph) return null;
    const active = hover ?? pinned;
    if (active) {
      const p = trace.paths[active.inc]?.[active.idx];
      if (p) return pathHighlight([p]);
    }
    if (focus && focus.length) return idsHighlight(focus, graph.edges);
    if (incident !== "all") return pathHighlight(trace.paths[incident] ?? []);
    return null;
  }, [graph, hover, pinned, focus, incident, trace.paths]);

  const selNode: GraphNode | undefined = graph?.nodes.find((n) => n.id === selected);
  const selPaths = selNode
    ? Object.entries(trace.paths).flatMap(([inc, ps]) => ps.map((p, idx) => ({ inc, idx, p })).filter(({ p }) => p.nodes.some((n) => n.id === selNode.id)))
    : [];
  const selDegree = selNode && graph ? graph.edges.filter((e) => e.from === selNode.id || e.to === selNode.id).length : 0;

  if (q.isLoading) return <Loading label="Loading graph" />;
  if (q.isError) return <ErrorBox message={(q.error as Error).message} onRetry={() => void q.refetch()} />;
  if (!graph || graph.nodes.length === 0)
    return <Empty title="No graph for this event" hint="Noise and escalated events never reach the knowledge graph, so there are no paths to draw." />;

  const types = [...new Set(graph.nodes.map((n) => n.type))];
  const incidents = trace.incidents.filter((i) => (trace.paths[i.incident_id] ?? []).length > 0);

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-1" role="group" aria-label="Highlight incident">
            {["all", ...incidents.map((i) => i.incident_id)].map((id) => (
              <button
                key={id}
                aria-pressed={incident === id}
                onClick={() => {
                  setIncident(id);
                  setPinned(null);
                  onClearFocus();
                }}
                className={`rounded-md border px-2 py-1 text-xs ${incident === id ? "border-brand-bright text-tx" : "border-line text-tx3 hover:text-tx"}`}
              >
                {id === "all" ? "All incidents" : <span className="mono">{id}</span>}
              </button>
            ))}
          </div>
          {focus && (
            <button onClick={onClearFocus} className="inline-flex items-center gap-1 rounded-md border border-brand-bright px-2 py-1 text-xs text-tx">
              Action path ({focus.length} nodes) <X size={12} aria-label="clear action path" />
            </button>
          )}
          <div className="ml-auto flex items-center gap-1">
            <button onClick={() => setLabels(!labels)} aria-pressed={labels} aria-label="Toggle edge labels" title="Edge labels" className={`rounded-md border p-1.5 ${labels ? "border-brand-bright text-tx" : "border-line text-tx2"} hover:text-tx`}>
              <Tags size={14} />
            </button>
            <button onClick={() => handle.current?.zoom(1.3)} aria-label="Zoom in" className="rounded-md border border-line p-1.5 text-tx2 hover:text-tx"><Plus size={14} /></button>
            <button onClick={() => handle.current?.zoom(1 / 1.3)} aria-label="Zoom out" className="rounded-md border border-line p-1.5 text-tx2 hover:text-tx"><Minus size={14} /></button>
            <button onClick={() => handle.current?.fit()} aria-label="Fit to screen" className="rounded-md border border-line p-1.5 text-tx2 hover:text-tx"><Maximize2 size={14} /></button>
          </div>
        </div>
        <CytoGraph
          ref={handle}
          nodes={graph.nodes}
          edges={graph.edges}
          positions={positions}
          highlightNodes={highlight?.nodes ?? null}
          highlightEdges={highlight?.edges ?? null}
          selectedId={selected}
          edgeLabels={labels}
          onSelect={setSelected}
          height={600}
          label={`Knowledge graph paths for ${trace.event_id}: ${graph.nodes.length} nodes, ${graph.edges.length} edges`}
        />
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Legend types={types} />
          <span className="mono text-[11px] text-tx3">{graph.nodes.length} nodes · {graph.edges.length} edges</span>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
        <Panel title="Selected node">
          {selNode ? (
            <div className="space-y-1.5 text-[13px]">
              <div className="flex items-center gap-2">
                <Mono className="font-medium text-tx">{selNode.id}</Mono>
                <Chip color={NODE_COLOR[selNode.type]}>{selNode.type}</Chip>
              </div>
              <p className="text-tx2">{selNode.label}</p>
              {selNode.group && (
                <p className="rounded-md border border-dashed border-line px-2 py-1.5 text-xs text-tx3">
                  Collapsed set of <span className="mono text-tx">{selNode.count}</span> {selNode.group.replace("_", " ")}. The trace
                  stores only the count, not the members.
                </p>
              )}
              <p className="text-xs text-tx3">{selDegree} connections · on {selPaths.length} path{selPaths.length === 1 ? "" : "s"}</p>
              {selPaths.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {selPaths.slice(0, 8).map(({ inc, idx }) => (
                    <button key={`${inc}-${idx}`} onClick={() => setPinned({ inc, idx })} className="mono rounded-md border border-line px-1.5 py-0.5 text-[11px] text-tx2 hover:border-brand-bright">
                      {inc} p{idx + 1}
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="text-xs text-tx3">Click a node to see what it is and which paths run through it.</p>
          )}
        </Panel>

        <Panel
          title="Why: paths per incident"
          action={pinned && <button onClick={() => setPinned(null)} className="text-[11px] text-tx3 hover:text-tx">unpin</button>}
        >
          <p className="mb-2 text-[11px] text-tx3">Hover a path to trace it on the graph, click to pin it.</p>
          <div className="max-h-[420px] space-y-3 overflow-y-auto pr-1">
            {incidents.map((inc) => {
              const ps = trace.paths[inc.incident_id] ?? [];
              const expanded = showAll.has(inc.incident_id);
              return (
                <div key={inc.incident_id}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Mono className="font-medium text-tx">{inc.incident_id}</Mono>
                    <CategoryBadge category={inc.category} />
                    <span className="text-[11px] text-tx3">{ps.length} paths</span>
                  </div>
                  <p className="mt-1 text-xs text-tx2">{inc.reason}</p>
                  <ol className="mt-1.5 space-y-1">
                    {(expanded ? ps : ps.slice(0, 5)).map((p, idx) => {
                      const isPinned = pinned?.inc === inc.incident_id && pinned.idx === idx;
                      return (
                        <li key={idx}>
                          <button
                            onMouseEnter={() => setHover({ inc: inc.incident_id, idx })}
                            onMouseLeave={() => setHover(null)}
                            onFocus={() => setHover({ inc: inc.incident_id, idx })}
                            onBlur={() => setHover(null)}
                            onClick={() => setPinned(isPinned ? null : { inc: inc.incident_id, idx })}
                            aria-pressed={isPinned}
                            className={`mono w-full rounded-md border px-2 py-1 text-left text-[11px] leading-snug ${isPinned ? "border-brand-bright bg-surface-2 text-tx" : "border-line text-tx2 hover:border-brand-bright"}`}
                          >
                            {pathLabel(p)}
                          </button>
                        </li>
                      );
                    })}
                  </ol>
                  {ps.length > 5 && (
                    <button
                      onClick={() => setShowAll((s) => { const n = new Set(s); if (n.has(inc.incident_id)) n.delete(inc.incident_id); else n.add(inc.incident_id); return n; })}
                      className="mt-1 text-[11px] text-tx3 hover:text-tx"
                    >
                      {expanded ? "show fewer" : `show all ${ps.length}`}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </Panel>
      </div>
    </div>
  );
}
