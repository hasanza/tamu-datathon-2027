import { Fragment, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, Network, Pencil, Eye } from "lucide-react";
import { useLog } from "../api/hooks";
import { isCustomId, WRITE_TOOLS, type Action, type AgentId, type Trace } from "../api/types";
import { FilterMenu } from "../components/ui/FilterMenu";
import { KV, KVGrid, RawJson } from "../components/ui/KeyValue";
import { Chip, Empty, Mono, OkChip, Panel } from "../components/ui/primitives";
import { clip, compactArgs } from "../lib/format";
import { AGENT_META, transportMeta } from "../lib/meta";
import { TARGET_META, targetOf } from "../lib/target";

const PAGE = 100;

const asObject = (v: unknown): Record<string, unknown> => (v && typeof v === "object" && !Array.isArray(v) ? (v as Record<string, unknown>) : { value: v });

function ActionDetail({ a, target }: { a: Action; target: ReturnType<typeof targetOf> }) {
  const tr = transportMeta(a.transport, target);
  return (
    <div className="grid gap-3 bg-surface-2 p-3 text-xs md:grid-cols-2">
      <div className="space-y-2">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Justification</div>
          <p className="text-tx2">{a.justification}</p>
        </div>
        {tr && (
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Transport</span>
            <Chip color={tr.color}>{tr.label}</Chip>
          </div>
        )}
        {a.rehearsal?.error && <p className="text-fail">Rehearsal error: <Mono>{a.rehearsal.error}</Mono></p>}
        {a.result?.error && <p className="text-fail">Result error: <Mono>{a.result.error}</Mono></p>}
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
          <KVGrid value={a.args} />
        </div>
        {a.result?.response && (
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-tx3">Server response</div>
            <KVGrid value={asObject(a.result.response)} />
          </div>
        )}
        <RawJson value={{ args: a.args, ...(a.result?.response ? { response: a.result.response } : {}) }} />
      </div>
    </div>
  );
}

export function ActionsTab({ trace, onShowOnGraph }: { trace: Trace; onShowOnGraph: (ids: string[]) => void }) {
  const sandbox = isCustomId(trace.event_id); // no server log exists for sandbox events: trace.actions is the record
  const log = useLog(sandbox ? null : trace.event_id);
  const target = targetOf(trace); // scored | sandbox | dry: where this event's calls went
  const [tools, setTools] = useState<string[]>([]);
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
        (tools.length === 0 || tools.includes(a.tool)) &&
        (agent === "all" || a.agent === agent) &&
        (kind === "all" || (kind === "write") === WRITE_TOOLS.has(a.tool)) &&
        (!needle || `${a.tool} ${compactArgs(a.args)} ${a.justification}`.toLowerCase().includes(needle)),
    );
  }, [trace.actions, tools, agent, kind, q]);

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
                · {TARGET_META[target].short} log: <span className="mono">{log.data.length}</span> calls, <span className="mono">{logOk}</span> ok
                {log.data.length !== trace.actions.length && <span className="text-warn"> (differs from trace)</span>}
              </>
            )}
          </span>
        }
      >
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <FilterMenu
            label="Tool"
            selected={tools}
            onChange={setTools}
            options={byTool.map(([t, n]) => ({
              value: t,
              label: t,
              count: n,
              icon: WRITE_TOOLS.has(t) ? <Pencil size={11} className="shrink-0 text-brand-bright" aria-label="write" /> : <Eye size={11} className="shrink-0 text-tx3" aria-label="read" />,
            }))}
          />
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
          <div role="group" aria-label="Call type" className="flex rounded-md border border-line p-0.5">
            {([["all", "All"], ["write", "Writes"], ["read", "Reads"]] as const).map(([k, label]) => (
              <button
                key={k}
                aria-pressed={kind === k}
                onClick={() => setKind(k)}
                className={`rounded px-2 py-0.5 font-medium ${kind === k ? "bg-surface-2 text-tx" : "text-tx3 hover:text-tx"}`}
              >
                {label}
              </button>
            ))}
          </div>
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

      <div className="scroll-shadow-x overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full text-left text-[13px]">
          <thead className="bg-surface-2 text-[11px] uppercase tracking-wide text-tx3">
            <tr>
              <th className="px-2 py-1.5">#</th>
              <th className="px-2 py-1.5">Agent</th>
              <th className="px-2 py-1.5">Tool</th>
              <th className="px-2 py-1.5">Args</th>
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
                      <button onClick={() => toggle(a.seq)} aria-expanded={isOpen} aria-label={`${isOpen ? "Collapse" : "Expand"} action ${a.seq}`} className="inline-flex items-center gap-1 text-tx3 hover:text-tx">
                        {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                        <Mono className="text-tx3">{a.seq}</Mono>
                      </button>
                    </td>
                    <td className="whitespace-nowrap px-2 py-1.5 text-tx2">{AGENT_META[a.agent].label}</td>
                    <td className="max-w-72 px-2 py-1.5">
                      <div className="flex items-center gap-1.5">
                        {WRITE_TOOLS.has(a.tool) ? <Pencil size={11} className="shrink-0 text-brand-bright" aria-label="write" /> : <Eye size={11} className="shrink-0 text-tx3" aria-label="read" />}
                        <Mono className="font-medium text-tx">{a.tool}</Mono>
                      </div>
                      <div className="mt-0.5 text-[11.5px] leading-snug text-tx3">{clip(a.justification, 60)}</div>
                    </td>
                    <td className="max-w-64 px-2 py-1.5" title={compactArgs(a.args)}><KV value={a.args} /></td>
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
                    <td className="px-2 py-1.5"><OkChip ok={a.rehearsal?.ok} label="pre-flight" /></td>
                    <td className="px-2 py-1.5">
                      {a.result?.outcome === "unknown" ? (
                        <Chip color="var(--warn)" title="Transport failure: the call may or may not have reached the server. The event stopped and was escalated.">unknown</Chip>
                      ) : a.skipped ? (
                        <Chip color="var(--warn)" title="Not run: an earlier write of this incident failed (no retry, the rest is skipped)">skipped</Chip>
                      ) : (
                        <OkChip ok={a.result?.ok} label={TARGET_META[target].short} />
                      )}
                    </td>
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={7} className="p-0"><ActionDetail a={a} target={target} /></td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7}><Empty title="No actions match the filters" /></td>
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
