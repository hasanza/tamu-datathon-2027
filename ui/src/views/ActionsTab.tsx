import { Fragment, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Network, Pencil, Eye } from "lucide-react";
import { useExecTarget, useLog } from "../api/hooks";
import { WRITE_TOOLS, type Action, type AgentId, type Trace } from "../api/types";
import { Chip, Empty, Mono, OkChip, Panel } from "../components/ui/primitives";
import { clip, compactArgs } from "../lib/format";
import { AGENT_META } from "../lib/meta";

const PAGE = 100;

function WriteChip({ tool }: { tool: string }) {
  return WRITE_TOOLS.has(tool) ? (
    <Chip color="var(--brand-bright)"><Pencil size={10} aria-hidden /> write</Chip>
  ) : (
    <Chip color="var(--text-3)"><Eye size={10} aria-hidden /> read</Chip>
  );
}

function ActionDetail({ a }: { a: Action }) {
  return (
    <div className="grid gap-3 bg-surface-2 p-3 text-xs md:grid-cols-2">
      <div className="space-y-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Justification</div>
          <p className="text-tx2">{a.justification}</p>
        </div>
        {a.rehearsal?.error && <p className="text-fail">Rehearsal error: {a.rehearsal.error}</p>}
        {a.result?.error && <p className="text-fail">Result error: {a.result.error}</p>}
        {a.path_ids.length > 0 && (
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Graph path</div>
            <Mono className="break-words text-tx2">{a.path_ids.join(" → ")}</Mono>
          </div>
        )}
      </div>
      <div className="space-y-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Arguments</div>
          <pre className="mono max-h-40 overflow-auto rounded-md border border-line bg-bg p-2 text-[11px] text-tx2">{JSON.stringify(a.args, null, 2)}</pre>
        </div>
        {a.result?.response && (
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Server response</div>
            <pre className="mono max-h-40 overflow-auto rounded-md border border-line bg-bg p-2 text-[11px] text-tx2">{JSON.stringify(a.result.response, null, 2)}</pre>
          </div>
        )}
      </div>
    </div>
  );
}

export function ActionsTab({ trace, onShowOnGraph }: { trace: Trace; onShowOnGraph: (ids: string[]) => void }) {
  const log = useLog(trace.event_id);
  const target = useExecTarget(); // "twin" for a dry run started from the UI, "server" for the committed snapshot
  const [tool, setTool] = useState<string | null>(null);
  const [agent, setAgent] = useState<string>("all");
  const [kind, setKind] = useState<"all" | "write" | "read">("all");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Set<number>>(new Set());
  const [limit, setLimit] = useState(PAGE);

  const byTool = useMemo(() => {
    const m = new Map<string, number>();
    for (const a of trace.actions) m.set(a.tool, (m.get(a.tool) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [trace.actions]);
  const writes = trace.actions.filter((a) => WRITE_TOOLS.has(a.tool)).length;
  const agents = [...new Set(trace.actions.map((a) => a.agent))];

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return trace.actions.filter(
      (a) =>
        (!tool || a.tool === tool) &&
        (agent === "all" || a.agent === agent) &&
        (kind === "all" || (kind === "write") === WRITE_TOOLS.has(a.tool)) &&
        (!needle || `${a.tool} ${compactArgs(a.args)} ${a.justification}`.toLowerCase().includes(needle)),
    );
  }, [trace.actions, tool, agent, kind, q]);

  if (trace.actions.length === 0) return <Empty title="No actions" hint="This event led to no tool calls." />;

  const toggle = (seq: number) =>
    setOpen((s) => {
      const n = new Set(s);
      if (n.has(seq)) n.delete(seq);
      else n.add(seq);
      return n;
    });
  const logOk = log.data?.filter((r) => r.ok).length;

  return (
    <div className="space-y-3">
      <Panel
        title={`Tool calls (${trace.actions.length})`}
        action={
          <span className="text-[11px] text-tx3">
            {writes} writes · {trace.actions.length - writes} reads
            {log.data && (
              <>
                {" "}
                · {target} log: <span className="mono">{log.data.length}</span> calls, <span className="mono">{logOk}</span> ok
                {log.data.length !== trace.actions.length && <span className="text-warn"> (differs from trace)</span>}
              </>
            )}
          </span>
        }
      >
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by tool">
          <button
            onClick={() => setTool(null)}
            aria-pressed={tool === null}
            className={`rounded-md border px-2 py-1 text-xs ${tool === null ? "border-brand-bright text-tx" : "border-line text-tx3 hover:text-tx"}`}
          >
            All <span className="mono">{trace.actions.length}</span>
          </button>
          {byTool.map(([t, n]) => (
            <button
              key={t}
              onClick={() => setTool(tool === t ? null : t)}
              aria-pressed={tool === t}
              className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs ${tool === t ? "border-brand-bright bg-surface-2 text-tx" : "border-line text-tx2 hover:text-tx"}`}
            >
              {WRITE_TOOLS.has(t) ? <Pencil size={11} className="text-brand-bright" aria-label="write" /> : <Eye size={11} className="text-tx3" aria-label="read" />}
              <span className="mono">{t}</span>
              <span className="mono text-tx3">{n}</span>
            </button>
          ))}
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
          <label className="flex items-center gap-1 text-tx3">
            Agent
            <select value={agent} onChange={(e) => setAgent(e.target.value)} className="rounded-md border border-line bg-surface-2 px-1.5 py-1 text-tx">
              <option value="all">all</option>
              {agents.map((a) => (
                <option key={a} value={a}>
                  {AGENT_META[a as AgentId].label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-1 text-tx3">
            Type
            <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)} className="rounded-md border border-line bg-surface-2 px-1.5 py-1 text-tx">
              <option value="all">all</option>
              <option value="write">writes</option>
              <option value="read">reads</option>
            </select>
          </label>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Filter by args or justification"
            aria-label="Filter actions by text"
            className="min-w-48 flex-1 rounded-md border border-line bg-surface-2 px-2 py-1 text-tx placeholder:text-tx3"
          />
          <span className="text-tx3">{rows.length} shown</span>
        </div>
      </Panel>

      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full text-left text-[13px]">
          <thead className="bg-surface-2 text-[11px] uppercase tracking-wide text-tx3">
            <tr>
              <th className="w-6 px-2 py-1.5" />
              <th className="px-2 py-1.5">#</th>
              <th className="px-2 py-1.5">Agent</th>
              <th className="px-2 py-1.5">Tool</th>
              <th className="px-2 py-1.5">Args</th>
              <th className="px-2 py-1.5">Justification</th>
              <th className="px-2 py-1.5">Path</th>
              <th className="px-2 py-1.5">Rehearsal</th>
              <th className="px-2 py-1.5">Result</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, limit).map((a) => {
              const isOpen = open.has(a.seq);
              return (
                <Fragment key={a.seq}>
                  <tr className="border-t border-line align-top hover:bg-surface-2/50">
                    <td className="px-2 py-1.5">
                      <button onClick={() => toggle(a.seq)} aria-expanded={isOpen} aria-label={`${isOpen ? "Collapse" : "Expand"} action ${a.seq}`} className="text-tx3 hover:text-tx">
                        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                      </button>
                    </td>
                    <td className="px-2 py-1.5"><Mono className="text-tx3">{a.seq}</Mono></td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-tx2">{AGENT_META[a.agent].label}</td>
                    <td className="px-2 py-1.5">
                      <div className="flex flex-col items-start gap-1">
                        <Mono className="font-medium text-tx">{a.tool}</Mono>
                        <WriteChip tool={a.tool} />
                      </div>
                    </td>
                    <td className="max-w-64 px-2 py-1.5"><Mono className="break-all text-tx2" >{clip(compactArgs(a.args), 110)}</Mono></td>
                    <td className="max-w-72 px-2 py-1.5 text-xs text-tx2">{clip(a.justification, 130)}</td>
                    <td className="px-2 py-1.5">
                      {a.path_ids.length > 0 ? (
                        <button
                          onClick={() => onShowOnGraph(a.path_ids)}
                          className="inline-flex items-center gap-1 whitespace-nowrap rounded-md border border-line px-1.5 py-0.5 text-[11px] text-tx2 hover:border-brand-bright hover:text-tx"
                          title={a.path_ids.join(" → ")}
                        >
                          <Network size={11} aria-hidden /> {a.path_ids.length} node{a.path_ids.length === 1 ? "" : "s"}
                        </button>
                      ) : (
                        <span className="text-tx3">-</span>
                      )}
                    </td>
                    <td className="px-2 py-1.5"><OkChip ok={a.rehearsal?.ok} label="twin" /></td>
                    <td className="px-2 py-1.5"><OkChip ok={a.result?.ok} label={target} /></td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={9} className="p-0"><ActionDetail a={a} /></td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={9}><Empty title="No actions match the filters" /></td>
              </tr>
            )}
          </tbody>
        </table>
        {rows.length > limit && (
          <div className="border-t border-line p-2 text-center">
            <button onClick={() => setLimit(limit + PAGE)} className="rounded-md border border-line px-3 py-1 text-xs text-tx2 hover:border-brand-bright hover:text-tx">
              Show {Math.min(PAGE, rows.length - limit)} more ({rows.length - limit} remaining)
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
