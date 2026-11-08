import { Moon, Play, Sun, Undo2 } from "lucide-react";
import { useKpis, useRunStatus } from "../api/hooks";
import type { Page } from "../lib/route";
import { usd } from "../lib/format";
import { useRunMode, useTheme, type RunOrder } from "../state";
import { useReset, useRun } from "./useRun";

const NAV: { page: Page; label: string }[] = [
  { page: "tower", label: "Control tower" },
  { page: "ontology", label: "Ontology" },
  { page: "about", label: "About" },
];

function Kpi({ label, value, warn }: { label: string; value: React.ReactNode; warn?: boolean }) {
  return (
    <div className="flex min-w-0 flex-col px-3 first:pl-0">
      <span className="text-[10px] uppercase tracking-wide text-tx3">{label}</span>
      <span className={`mono text-[13px] font-medium leading-5 ${warn ? "text-fail" : "text-tx"}`}>{value}</span>
    </div>
  );
}

export function KpiStrip() {
  const { data, isError, isLoading } = useKpis();
  if (isLoading) return <div className="px-4 py-1.5 text-[11px] text-tx3">Loading KPIs…</div>;
  if (isError || !data) return <div className="px-4 py-1.5 text-[11px] text-tx3">KPIs unavailable (API unreachable)</div>;
  return (
    <div aria-label="Key performance indicators" className="flex flex-wrap items-center gap-y-1 divide-x divide-line px-4 py-1.5">
      <Kpi label="Events handled" value={`${data.events_with_trace}/${data.events_total}`} />
      <Kpi label="Writes" value={data.writes} />
      <Kpi label="Failed calls" value={data.failed} warn={data.failed > 0} />
      <Kpi label="Escalations" value={data.escalations} />
      <Kpi label="LLM cost" value={usd(data.cost_usd)} />
      <Kpi label="LLM calls" value={data.llm_calls} />
      <Kpi
        label="Models"
        value={<span title={data.models.join(", ")}>{data.models.map((m) => m.replace(/^[^/]+\//, "")).join(" · ") || "-"}</span>}
      />
    </div>
  );
}

export function TopBar({ page, go }: { page: Page; go: (p: Page) => void }) {
  const { theme, toggle } = useTheme();
  const run = useRun();
  const reset = useReset();
  const { order, setOrder } = useRunMode();
  const status = useRunStatus().data;
  const running = !!status?.running;
  return (
    <header className="shrink-0 border-b-2 border-brand bg-surface">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2">
        <h1 className="text-lg font-semibold tracking-tight">
          Wacky Wheels <span className="text-tx2">Control Tower</span>
        </h1>
        <nav aria-label="Primary" className="flex items-center gap-1">
          {NAV.map((n) => (
            <button
              key={n.page}
              onClick={() => go(n.page)}
              aria-current={page === n.page ? "page" : undefined}
              className={`rounded-md px-2.5 py-1 text-[13px] font-medium transition-colors ${
                page === n.page ? "bg-brand text-white" : "text-tx2 hover:bg-surface-2 hover:text-tx"
              }`}
            >
              {n.label}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-x-3 gap-y-2">
          {status?.mode && !running && (
            <button
              onClick={() => reset.mutate()}
              disabled={reset.isPending}
              title="Discard this run and show the committed snapshot of all 15 events"
              className="inline-flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1.5 text-[13px] text-tx2 hover:border-brand-bright hover:text-tx disabled:opacity-60"
            >
              <Undo2 size={14} aria-hidden /> Back to snapshot
            </button>
          )}
          <div role="group" aria-label="Run order" className="flex rounded-md border border-line p-0.5 text-[12px]">
            {(["sequential", "parallel"] as RunOrder[]).map((o) => (
              <button
                key={o}
                aria-pressed={order === o}
                disabled={running}
                onClick={() => setOrder(o)}
                title={o === "sequential" ? "Handle the events one by one (the default)" : "Handle several events side by side, each in its own fresh world"}
                className={`rounded px-2 py-1 font-medium capitalize disabled:opacity-60 ${order === o ? "bg-surface-2 text-tx" : "text-tx3 hover:text-tx"}`}
              >
                {o}
              </button>
            ))}
          </div>
          <button
            onClick={() => run.mutate({ all: true })}
            disabled={run.isPending || running}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-[13px] font-medium text-white hover:bg-brand-bright disabled:opacity-60"
          >
            <Play size={14} aria-hidden /> {run.isPending ? "Starting…" : running ? "Running…" : "Run feed"}
          </button>
          <button
            onClick={toggle}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            className="rounded-md border border-line p-1.5 text-tx2 hover:border-brand-bright hover:text-tx"
          >
            {theme === "dark" ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
          </button>
          <div className="hidden text-right leading-tight sm:block" aria-label="Powered by Hitachi Digital Services">
            <div className="text-[9px] uppercase tracking-[0.12em] text-tx3">Powered by</div>
            <div className="text-[12px] font-bold tracking-tight text-tx">
              HITACHI <span className="font-medium text-tx2">Digital Services</span>
            </div>
          </div>
        </div>
      </div>
      {page === "tower" && (
        <div className="border-t border-line">
          <KpiStrip />
        </div>
      )}
    </header>
  );
}
