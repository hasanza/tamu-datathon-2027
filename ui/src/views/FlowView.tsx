import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, FastForward, RotateCcw, X } from "lucide-react";
import type { AgentStep } from "../api/types";
import { Chip, Mono, Panel } from "../components/ui/primitives";
import { buildFlow, firstLine, type Flow, type FlowChip, type FlowNode, type Tone } from "../lib/flow";
import { compactArgs, prettifyRepr, summarize, usd } from "../lib/format";
import { useFollow } from "../lib/useFollow";
import { FollowChip } from "../components/ui/FollowChip";
import { BADGE_COLOR, LANE_META, STEP_META, toolBadge } from "../lib/meta";
import type { OrchRow } from "./OrchestrationTab";
import { Clamped, DECISION_COLOR, Details, echoesCall, hasKeys } from "./orchParts";

/* Level 1 of the Orchestration tab (CORE #68): "How the four agents handled this event".
   Stage nodes on two rows (coordinator above, specialists below), time left to right; the brief goes down, the result comes back up.
   Click a node to read its steps. Plain CSS/SVG animation, off under prefers-reduced-motion. */

const W = 224; // node width
const H = 172; // node height (fixed so the edges know where to attach)
const GAP = 30;
const TOP_Y = 8;
const ROW_GAP = 96;
const BOTTOM_Y = TOP_Y + H + ROW_GAP;

const TONE: Record<Tone, string> = {
  ok: "var(--ok)",
  warn: "var(--warn)",
  fail: "var(--fail)",
  info: "var(--cat-unconfirmed)",
  muted: "var(--text-3)",
};

/** Played-once memory: reopening a finished event (or switching tabs back) shows the final state instead of replaying. */
const PLAYED = new Set<string>();

function useMedia(query: string): boolean {
  const [match, setMatch] = useState(() => (typeof window === "undefined" ? false : window.matchMedia(query).matches));
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setMatch(m.matches);
    on();
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return match;
}

/** Counts the first number in a chip up from 0 when the chip appears ("9 moves" -> 1.. 9 moves). */
function ChipText({ text, animate, delayMs }: { text: string; animate: boolean; delayMs: number }) {
  const m = /^(\D*)(\d+)(.*)$/s.exec(text);
  const target = m ? Number(m[2]) : 0;
  const [n, setN] = useState(animate && m ? 0 : target);
  useEffect(() => {
    if (!animate || !m || target === 0) {
      setN(target); // not animating (or the number changed): always show the real value, never a stale 0
      return;
    }
    let raf = 0;
    const start = performance.now() + delayMs;
    const tick = (now: number) => {
      const p = Math.min(1, Math.max(0, (now - start) / 700));
      setN(Math.round(target * p));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [animate, target, delayMs]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!m) return <>{text}</>;
  return (
    <>
      {m[1]}
      {n}
      {m[3]}
    </>
  );
}

function ChipView({ chip, animate, delayMs }: { chip: FlowChip; animate: boolean; delayMs: number }) {
  const color = TONE[chip.tone];
  return (
    <span
      title={chip.text}
      style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)`, borderColor: `color-mix(in srgb, ${color} 45%, transparent)` }}
      className="inline-block max-w-full break-words rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-4"
    >
      <ChipText text={chip.text} animate={animate} delayMs={delayMs} />
    </span>
  );
}

const durationLabel = (ms: number) => (ms <= 0 ? "" : ms < 1000 ? `${ms} ms` : ms < 60_000 ? `${(ms / 1000).toFixed(0)} s` : `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`);

function NodeCard({
  node,
  selected,
  active,
  animate,
  delay,
  onClick,
  style,
}: {
  node: FlowNode;
  selected: boolean;
  active: boolean;
  animate: boolean;
  delay: number;
  onClick: () => void;
  style?: React.CSSProperties;
}) {
  const color = LANE_META[node.lane].color;
  const shown = node.chips.slice(0, 4);
  const meta = [node.turns ? `${node.turns} turns` : "", node.tools ? `${node.tools} tools` : "", node.cost ? usd(node.cost) : "", durationLabel(node.ms)].filter(Boolean).join(" · ");
  return (
    <button
      onClick={onClick}
      aria-expanded={selected}
      aria-label={`stage: ${LANE_META[node.lane].label} · ${node.task ?? node.kind}`}
      data-flow-node={node.id}
      data-kind={node.kind}
      style={{ ...style, ["--d" as string]: `${delay}s`, borderLeftColor: color, ...(selected ? { boxShadow: `0 0 0 2px ${color}` } : {}) }}
      className={`flow-node flex flex-col overflow-hidden rounded-lg border border-line border-l-[4px] bg-surface-2 p-2.5 text-left transition-colors hover:border-brand-bright focus-visible:outline-2 ${active ? "flow-active" : ""}`}
    >
      <div className="flex items-center gap-1.5">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color }} aria-hidden />
        <span className="truncate text-[12.5px] font-semibold text-tx">{node.title}</span>
        {active && <span className="ml-auto shrink-0 text-[10px] font-medium text-brand-bright">working…</span>}
      </div>
      <div className="mono mt-0.5 truncate text-[10.5px] text-tx3" title={node.subtitle}>
        {node.subtitle}
      </div>
      <p className="mt-1.5 line-clamp-3 text-[12px] leading-snug text-tx2">{node.summary}</p>
      <div className="mt-auto flex flex-wrap gap-1 pt-1.5">
        {shown.map((c, i) => (
          <ChipView key={c.text + i} chip={c} animate={animate} delayMs={delay * 1000 + 450} />
        ))}
        {node.chips.length > shown.length && <span className="text-[11px] text-tx3">+{node.chips.length - shown.length}</span>}
      </div>
      {meta && <div className="mono mt-1 truncate text-[10px] text-tx3">{meta}</div>}
    </button>
  );
}

/* ---------- the node detail: the group's steps, thoughts folded to one line ---------- */

function ThoughtRow({ step }: { step: AgentStep }) {
  const [open, setOpen] = useState(false);
  const multi = step.text.trim().length > firstLine(step.text).length;
  return (
    <li className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px]">
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full items-start gap-1.5 text-left">
        {open ? <ChevronDown size={13} className="mt-0.5 shrink-0 text-tx3" aria-hidden /> : <ChevronRight size={13} className="mt-0.5 shrink-0 text-tx3" aria-hidden />}
        <Chip color={STEP_META.thought.color}>Thought{step.turn != null ? ` ${step.turn}` : ""}</Chip>
        {open ? (
          <span className="min-w-0 flex-1 whitespace-pre-wrap break-words italic text-tx2">{prettifyRepr(step.text)}</span>
        ) : (
          <span className="min-w-0 flex-1 truncate italic text-tx2" title="click for the full thought">
            {firstLine(step.text)}
            {multi ? " …" : ""}
          </span>
        )}
      </button>
    </li>
  );
}

function StepRow({ row }: { row: OrchRow }) {
  const step = row.step;
  if (step.kind === "thought") return <ThoughtRow step={step} />;
  if (step.kind === "tool") {
    const badge = toolBadge(step);
    return (
      <li className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px]">
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip color={STEP_META.tool.color}>Tool call</Chip>
          <Chip color={BADGE_COLOR[badge]}>{badge}</Chip>
          <Mono className="font-medium text-tx">{step.tool ?? "tool"}</Mono>
          {echoesCall(step) && hasKeys(step.args) && (
            <span className="mono min-w-0 truncate text-[11px] text-tx3" title={compactArgs(step.args)}>
              {summarize(step.args)}
            </span>
          )}
        </div>
        {/* the pipeline's own sentence ("register_incidents - 1 incident (noise)") replaces the separate arguments line */}
        {!echoesCall(step) && <p className="mt-1 break-words text-tx2">{prettifyRepr(step.text)}</p>}
        {hasKeys(step.result) && (
          <p className="mono mt-0.5 truncate text-[11px] text-tx2" title={compactArgs(step.result)}>
            → {summarize(step.result)}
          </p>
        )}
        <Details step={step} />
      </li>
    );
  }
  if (step.kind === "decision") {
    const c = DECISION_COLOR(step.text);
    return (
      <li className="rounded-md border px-2.5 py-1.5 text-[12.5px]" style={{ borderColor: `color-mix(in srgb, ${c} 55%, transparent)`, background: `color-mix(in srgb, ${c} 10%, var(--surface))` }}>
        <Chip color={c}>Decision</Chip> <span className="font-medium text-tx">{prettifyRepr(step.text)}</span>
      </li>
    );
  }
  if (step.kind === "message") {
    const from = LANE_META[row.lane]?.label ?? "";
    return (
      <li className="rounded-md border border-dashed border-line bg-surface px-2.5 py-1.5 text-[12.5px]">
        <div className="mb-0.5 flex flex-wrap items-center gap-1.5">
          <Chip color={STEP_META.message.color}>Message</Chip>
          <span className="text-[11px] text-tx3">
            {String(step.from_agent ?? from).replace(/_/g, " ")} → {String(step.to_agent ?? "").replace(/_/g, " ")}
          </span>
        </div>
        <Clamped text={step.text} />
        <Details step={step} />
      </li>
    );
  }
  const m = STEP_META[step.kind] ?? { label: String(step.kind), color: "var(--text-3)" };
  return (
    <li className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12.5px]">
      <Chip color={m.color}>{m.label}</Chip> <span className="break-words text-tx2">{prettifyRepr(step.text)}</span>
      <Details step={step} />
    </li>
  );
}

function NodeDetail({ node, onClose }: { node: FlowNode; onClose: () => void }) {
  const color = LANE_META[node.lane].color;
  return (
    <Panel
      title={
        <span className="flex flex-wrap items-center gap-2">
          <span className="h-2 w-2 rounded-full" style={{ background: color }} aria-hidden />
          {node.title}
          <span className="mono text-[11px] font-normal text-tx3">{node.subtitle}</span>
        </span>
      }
      action={
        <button onClick={onClose} aria-label="Close the stage detail" className="rounded p-0.5 text-tx3 hover:text-tx">
          <X size={14} aria-hidden />
        </button>
      }
    >
      <p className="mb-2 text-[12px] text-tx3">{node.steps.length} steps. Click a thought to read it in full.</p>
      <ol data-flow-detail={node.id} className="space-y-1.5">
        {node.steps.map((r) => (
          <StepRow key={r.key} row={r} />
        ))}
      </ol>
    </Panel>
  );
}

/* ---------- geometry ---------- */

interface Placed {
  node: FlowNode;
  x: number;
  y: number;
}

function layout(flow: Flow): { placed: Placed[]; width: number; height: number } {
  const placed: Placed[] = [];
  let x = 0;
  flow.nodes.forEach((node, i) => {
    if (i > 0) {
      const prev = flow.nodes[i - 1] as FlowNode;
      // nodes that alternate rows overlap in x by half a step; two in a row on the same row need a whole step
      x += prev.row === node.row ? W + GAP : (W + GAP) / 2;
    }
    placed.push({ node, x, y: node.row === "top" ? TOP_Y : BOTTOM_Y });
  });
  const last = placed[placed.length - 1];
  return { placed, width: (last ? last.x : 0) + W + 16, height: BOTTOM_Y + H + 12 };
}

function edgePath(a: Placed, b: Placed, dir: "down" | "up" | "across"): { d: string; mx: number; my: number } {
  if (dir === "across") {
    const sy = a.y + H / 2;
    const sx = a.x + W;
    const ex = b.x;
    return { d: `M ${sx} ${sy} L ${ex - 2} ${sy}`, mx: (sx + ex) / 2, my: sy };
  }
  if (dir === "down") {
    const sx = a.x + W * 0.72;
    const sy = a.y + H;
    const ex = b.x + W * 0.28;
    const ey = b.y;
    return { d: `M ${sx} ${sy} C ${sx} ${sy + ROW_GAP * 0.55}, ${ex} ${ey - ROW_GAP * 0.55}, ${ex} ${ey - 2}`, mx: (sx + ex) / 2, my: (sy + ey) / 2 };
  }
  const sx = a.x + W * 0.72;
  const sy = a.y;
  const ex = b.x + W * 0.28;
  const ey = b.y + H;
  return { d: `M ${sx} ${sy} C ${sx} ${sy - ROW_GAP * 0.55}, ${ex} ${ey + ROW_GAP * 0.55}, ${ex} ${ey + 2}`, mx: (sx + ex) / 2, my: (sy + ey) / 2 };
}

/* ---------- the view ---------- */

export function FlowView({ rows, status, correctionRounds, escalations, live = false, eventId }: { rows: OrchRow[]; status?: string; correctionRounds?: number; escalations?: { incident_id: string; reason: string }[]; live?: boolean; eventId: string }) {
  const flow = useMemo(() => buildFlow(rows, { status, correctionRounds, escalations, live }), [rows, status, correctionRounds, escalations, live]);
  const desktop = useMedia("(min-width: 768px)");
  const reduced = useMedia("(prefers-reduced-motion: reduce)");
  const [selected, setSelected] = useState<string | null>(null);
  const [instant, setInstant] = useState(() => !live && (PLAYED.has(eventId) || reduced));
  const [playKey, setPlayKey] = useState(0);
  const [animating, setAnimating] = useState(() => !live && !instant);
  const n = flow.nodes.length;
  const step = Math.min(0.8, Math.max(0.35, 6.5 / Math.max(n, 1))); // ~5-8 s for the whole build-up
  const total = n * step + 0.9;
  const timer = useRef<number | undefined>(undefined);
  const scroller = useRef<HTMLDivElement>(null);
  const [moreRight, setMoreRight] = useState(false);
  const [viewW, setViewW] = useState(0);
  const checkMore = () => {
    const c = scroller.current;
    setMoreRight(!!c && c.scrollWidth - c.clientWidth - c.scrollLeft > 8);
    if (c) setViewW(c.clientWidth);
  };
  const detail = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (live) return;
    PLAYED.add(eventId);
    if (instant) {
      setAnimating(false);
      return;
    }
    setAnimating(true);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setAnimating(false), total * 1000);
    return () => window.clearTimeout(timer.current);
  }, [eventId, live, instant, playKey, total]);

  useEffect(() => {
    checkMore();
    window.addEventListener("resize", checkMore);
    return () => window.removeEventListener("resize", checkMore);
  }, [n, desktop]); // eslint-disable-line react-hooks/exhaustive-deps
  // replay build-up: the stage whose turn it is (the nodes appear one after another)
  const [replayIdx, setReplayIdx] = useState(0);
  useEffect(() => {
    if (live || !animating || instant) return;
    setReplayIdx(0);
    const ts = flow.nodes.map((_, i) => window.setTimeout(() => setReplayIdx(i), i * step * 1000));
    return () => ts.forEach((t) => window.clearTimeout(t));
  }, [live, animating, instant, playKey, eventId]); // eslint-disable-line react-hooks/exhaustive-deps
  // follow the active stage (live run: the newest; replay: the one appearing), centred, until the reader takes over
  const activeId = live ? (flow.nodes[n - 1]?.id ?? null) : animating && !instant ? (flow.nodes[Math.min(replayIdx, n - 1)]?.id ?? null) : null;
  const follow = useFollow({
    scroller: () => scroller.current,
    target: () => (activeId ? (scroller.current?.querySelector(`[data-flow-node="${activeId}"]`) as HTMLElement | null) : null),
    axis: "x",
    enabled: desktop && (live || (animating && !instant)),
    activeKey: activeId,
    resetKey: `${eventId}|${live}|${playKey}`,
    reduced,
  });
  // the detail opens below the strip (below the fold on a phone): bring it into view
  useEffect(() => {
    if (selected) detail.current?.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }, [selected, reduced]);

  const replay = () => {
    setSelected(null);
    setInstant(false);
    setPlayKey((k) => k + 1);
  };
  const skip = () => {
    window.clearTimeout(timer.current);
    setInstant(true);
    setAnimating(false);
  };

  const { placed, width, height } = useMemo(() => layout(flow), [flow]);
  const byId = useMemo(() => new Map(placed.map((p) => [p.node.id, p])), [placed]);
  const selNode = flow.nodes.find((x) => x.id === selected) ?? null;
  // room to the right of the last stage so that it too can be centred (only when the strip overflows anyway)
  const pad = desktop && width > viewW ? Math.round(viewW / 2) : 0;
  const delayOf = (i: number) => (instant || live || reduced ? 0 : i * step);
  const animate = !instant && !reduced;
  const toggle = (id: string) => setSelected((s) => (s === id ? null : id));

  if (n === 0) return <p className="rounded-lg border border-line bg-surface px-3 py-6 text-center text-[13px] text-tx3">No stages yet: the agents have not started.</p>;

  const controls = !live && (
    <div className="flex items-center gap-1.5">
      {animating && (
        <button onClick={skip} className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] text-tx2 hover:border-brand-bright hover:text-tx">
          <FastForward size={12} aria-hidden /> Skip
        </button>
      )}
      <button onClick={replay} disabled={animating} className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] text-tx2 hover:border-brand-bright hover:text-tx disabled:opacity-50">
        <RotateCcw size={12} aria-hidden /> Replay
      </button>
    </div>
  );

  return (
    <div className={`space-y-3 ${instant ? "flow-instant" : ""}`} data-flow data-nodes={n}>
      <div className="flex items-center gap-2">
        <span className="text-[11px] text-tx3">
          {n} stages · click one to read what the agent did · the brief goes down, the result comes back up
        </span>
        {follow.paused && <FollowChip onResume={follow.resume} />}
        <div className="ml-auto">{controls}</div>
      </div>

      {desktop ? (
        <div className="relative">
        <div ref={scroller} onScroll={checkMore} className="scroll-shadow-x overflow-x-auto rounded-lg border border-line bg-surface p-2" role="group" aria-label="Stages of this event">
          <div key={playKey} className="relative" style={{ width: width + pad, height }}>
            <svg width={width} height={height} className="pointer-events-none absolute inset-0" aria-hidden>
              <defs>
                <marker id="flow-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                  <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
                </marker>
              </defs>
              {flow.edges.map((e, i) => {
                const a = byId.get(e.from);
                const b = byId.get(e.to);
                if (!a || !b) return null;
                const hot = selected === e.from || selected === e.to;
                const { d } = edgePath(a, b, e.dir);
                return (
                  <path
                    key={`${e.from}>${e.to}`}
                    d={d}
                    pathLength={1}
                    fill="none"
                    strokeWidth={hot ? 2.2 : 1.6}
                    markerEnd="url(#flow-arrow)"
                    className="flow-edge"
                    style={{ ["--d" as string]: `${Math.max(0, delayOf(i + 1) - 0.4)}s`, color: hot ? "var(--brand-bright)" : "var(--text-3)", stroke: "currentColor" }}
                  />
                );
              })}
            </svg>
            {flow.edges.map((e, i) => {
              const a = byId.get(e.from);
              const b = byId.get(e.to);
              if (!a || !b || !e.label) return null;
              const { mx, my } = edgePath(a, b, e.dir);
              return (
                <span
                  key={`l-${e.from}>${e.to}`}
                  className="flow-edge-label pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded-md border border-line bg-bg px-1.5 py-0.5 text-[10.5px] text-tx2"
                  style={{ left: mx, top: my, maxWidth: 150, ["--d" as string]: `${delayOf(i + 1)}s` }}
                  title={e.label}
                >
                  <span className="block truncate">
                    {e.dir === "down" ? "↓ " : e.dir === "up" ? "↑ " : ""}
                    {e.label}
                  </span>
                </span>
              );
            })}
            {placed.map((p, i) => (
              <NodeCard
                key={p.node.id}
                node={p.node}
                selected={selected === p.node.id}
                active={live && i === placed.length - 1}
                animate={animate}
                delay={delayOf(i)}
                onClick={() => toggle(p.node.id)}
                style={{ position: "absolute", left: p.x, top: p.y, width: W, height: H }}
              />
            ))}
          </div>
        </div>
        {moreRight && (
          <div className="pointer-events-none absolute inset-y-px right-px flex w-8 items-center justify-end pr-1.5" aria-hidden>
            <ChevronRight size={18} className="text-tx3" />
          </div>
        )}
        </div>
      ) : (
        <ol key={playKey} className="space-y-1" aria-label="Stages of this event">
          {flow.nodes.map((nd, i) => {
            const edge = flow.edges.find((e) => e.to === nd.id);
            return (
              <li key={nd.id}>
                {edge && (
                  <div className="flow-edge-label py-0.5 pl-3 text-[11px] text-tx3" style={{ ["--d" as string]: `${delayOf(i)}s` }}>
                    {edge.dir === "down" ? "↓" : edge.dir === "up" ? "↑" : "→"} {edge.label}
                  </div>
                )}
                <NodeCard node={nd} selected={selected === nd.id} active={live && i === flow.nodes.length - 1} animate={animate} delay={delayOf(i)} onClick={() => toggle(nd.id)} style={{ width: "100%", minHeight: 150 }} />
              </li>
            );
          })}
        </ol>
      )}

      {selNode && (
        <div ref={detail}>
          <NodeDetail node={selNode} onClose={() => setSelected(null)} />
        </div>
      )}
    </div>
  );
}
