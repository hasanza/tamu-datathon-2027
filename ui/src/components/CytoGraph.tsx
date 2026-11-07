import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from "react";
import cytoscape, { type Core, type StylesheetJson } from "cytoscape";
import type { GraphEdge, GraphNode } from "../api/types";
import { useTheme } from "../state";
import { NODE_COLOR } from "../lib/meta";

export const edgeKey = (e: GraphEdge) => `${e.from}|${e.to}|${e.type}`;

export interface CytoHandle {
  fit: () => void;
  zoom: (factor: number) => void;
}

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  positions?: Record<string, { x: number; y: number }>;
  highlightNodes?: Set<string> | null;
  highlightEdges?: Set<string> | null;
  selectedId?: string | null;
  edgeLabels?: boolean;
  big?: boolean;
  onSelect?: (id: string | null) => void;
  height?: number | string;
  label: string;
}

const css = (name: string) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
/** Cytoscape cannot read CSS variables, so resolve `var(--x)` strings against the current theme. */
const resolve = (c: string) => (c.startsWith("var(") ? css(c.slice(4, -1)) : c);

function buildStyle(edgeLabels: boolean, big: boolean): StylesheetJson {
  const fs = big ? 12 : 10;
  const nodeSize = big ? 26 : 16;
  const text2 = css("--text-2");
  const edgeColor = css("--text-3");
  const surface2 = css("--surface-2");
  const bright = css("--brand-bright");
  return [
    {
      selector: "node",
      style: {
        "background-color": "data(color)",
        label: "data(short)",
        color: text2,
        "font-size": fs,
        "font-family": "JetBrains Mono, monospace",
        "text-valign": "bottom",
        "text-margin-y": 4,
        width: nodeSize,
        height: nodeSize,
        "border-width": 1,
        "border-color": surface2,
      },
    },
    { selector: 'node[type = "Plant"], node[type = "Supplier"]', style: { width: nodeSize + 8, height: nodeSize + 8 } },
    {
      selector: "node[?group]",
      style: {
        shape: "round-rectangle",
        width: "label",
        height: 20,
        padding: "5px",
        "background-color": surface2,
        "border-color": "data(color)",
        "border-width": 1.5,
        "border-style": "dashed",
        label: "data(short)",
        "text-valign": "center",
        "text-margin-y": 0,
        color: text2,
        "font-family": "Noto Sans, sans-serif",
        "font-size": fs,
      },
    },
    {
      selector: "edge",
      style: {
        width: 1.5,
        "line-color": edgeColor,
        "target-arrow-color": edgeColor,
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.7,
        "curve-style": "straight",
        opacity: 1,
        ...(edgeLabels
          ? { label: "data(type)", "font-size": big ? 9 : 7, color: text2, "text-rotation": "autorotate", "font-family": "JetBrains Mono, monospace" }
          : {}),
      },
    },
    { selector: ".dim", style: { opacity: 0.3 } },
    {
      selector: "edge.hl",
      style: {
        width: 2,
        "line-color": bright,
        "target-arrow-color": bright,
        opacity: 1,
        label: "data(type)",
        "font-size": big ? 9 : 7,
        color: bright,
        "text-rotation": "autorotate",
        "font-family": "JetBrains Mono, monospace",
      },
    },
    { selector: "node.hl", style: { "border-color": bright, "border-width": 2, opacity: 1 } },
    { selector: "node:selected", style: { "border-color": text2, "border-width": 3 } },
  ];
}

export const CytoGraph = forwardRef<CytoHandle, Props>(function CytoGraph(
  { nodes, edges, positions, highlightNodes, highlightEdges, selectedId, edgeLabels = false, big = false, onSelect, height = 560, label },
  ref,
) {
  const host = useRef<HTMLDivElement>(null);
  const cy = useRef<Core | null>(null);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const { theme } = useTheme();

  useImperativeHandle(ref, () => ({
    fit: () => cy.current?.fit(undefined, 30),
    zoom: (f) => {
      const c = cy.current;
      if (c) c.zoom({ level: c.zoom() * f, renderedPosition: { x: c.width() / 2, y: c.height() / 2 } });
    },
  }));

  useEffect(() => {
    if (!host.current) return;
    const c = cytoscape({ container: host.current, wheelSensitivity: 0.25, minZoom: 0.1, maxZoom: 3, style: buildStyle(false, big) });
    c.on("tap", "node", (e) => onSelectRef.current?.(e.target.id()));
    c.on("tap", (e) => {
      if (e.target === c) onSelectRef.current?.(null);
    });
    cy.current = c;
    // refit when the container changes size (window resize, tab becoming visible)
    const ro = new ResizeObserver(() => {
      c.resize();
      c.fit(undefined, 30);
    });
    ro.observe(host.current);
    if (import.meta.env.DEV) (window as unknown as { __cy?: Core }).__cy = c; // handy for debugging and UI tests
    return () => {
      ro.disconnect();
      c.destroy();
      cy.current = null;
    };
  }, []);

  // theme or label mode changed: re-resolve the palette
  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.style(buildStyle(edgeLabels, big));
    c.nodes().forEach((n) => {
      n.data("color", resolve(NODE_COLOR[n.data("type") as keyof typeof NODE_COLOR] ?? "#747474"));
    });
  }, [theme, edgeLabels, big]);

  const sig = useMemo(() => nodes.map((n) => n.id).join(",") + "#" + edges.map(edgeKey).join(","), [nodes, edges]);
  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.batch(() => {
      c.elements().remove();
      c.add([
        ...nodes.map((n) => ({
          group: "nodes" as const,
          data: {
            id: n.id,
            type: n.type,
            group: n.group ? 1 : 0,
            short: n.group ? `+ ${n.label}` : n.id,
            color: resolve(NODE_COLOR[n.type]),
          },
          ...(positions?.[n.id] ? { position: positions[n.id] } : {}),
        })),
        ...edges.map((e) => ({ group: "edges" as const, data: { id: edgeKey(e), source: e.from, target: e.to, type: e.type } })),
      ]);
    });
    c.layout(positions ? { name: "preset", fit: true, padding: 30 } : { name: "cose", animate: false, padding: 30, nodeRepulsion: () => 9000 }).run();
    // Zero-height (perfectly horizontal) edges are culled on the first frame; re-measure and repaint after layout.
    requestAnimationFrame(() => {
      c.resize();
      c.style().update();
      c.forceRender();
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, positions]);

  // highlight / selection
  useEffect(() => {
    const c = cy.current;
    if (!c) return;
    c.batch(() => {
      c.elements().removeClass("dim hl");
      if (highlightNodes || highlightEdges) {
        c.nodes().forEach((n) => {
          n.addClass(highlightNodes?.has(n.id()) ? "hl" : "dim");
        });
        c.edges().forEach((e) => {
          e.addClass(highlightEdges?.has(e.id()) ? "hl" : "dim");
        });
      }
      c.nodes().unselect();
      if (selectedId) c.getElementById(selectedId).select();
    });
  }, [highlightNodes, highlightEdges, selectedId, sig]);

  return (
    <div
      ref={host}
      role="group"
      aria-label={label}
      style={{ height }}
      className="w-full rounded-lg border border-line bg-bg"
    />
  );
});
