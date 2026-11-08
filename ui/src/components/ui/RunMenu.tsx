import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { api } from "../../api/client";
import { safeStorage } from "../../lib/format";
import { Check, ChevronDown, Undo2 } from "lucide-react";
import { useKpis, useRunStatus } from "../../api/hooks";
import { usd } from "../../lib/format";
import { useRunMode, type RunOrder } from "../../state";
import { useResetAll } from "../useRun";
import { btnPrimary, btnSecondary, Dialog } from "./Dialog";

const ORDERS: { id: RunOrder; label: string; hint: string }[] = [
  { id: "sequential", label: "Sequential", hint: "one event at a time (default)" },
  { id: "parallel", label: "Parallel", hint: "several at once, each in its own fresh world" },
];

/** Run options beside the Run feed button: Sequential/Parallel, and while a run is live its counters. */
export function RunMenu({ running, activityCount = 0 }: { running: boolean; activityCount?: number }) {
  const { order, setOrder } = useRunMode();
  const kpis = useKpis().data;
  const status = useRunStatus().data;
  const reset = useResetAll();
  const [resetOpen, setResetOpen] = useState(false);
  const preview = useQuery({ queryKey: ["reset-preview"], queryFn: api.resetPreview, enabled: resetOpen, staleTime: 0 });
  const count = (key: string, pick: (v: unknown) => number) => {
    try {
      return pick(JSON.parse(safeStorage(key) ?? "null"));
    } catch {
      return 0;
    }
  };
  const acks = count("ct-acked", (v) => (Array.isArray(v) ? v.length : 0));
  const filters = count("ct-feed-filters", (v) => {
    const o = (v ?? {}) as { cats?: unknown[]; stats?: unknown[] };
    return (o.cats?.length ?? 0) + (o.stats?.length ?? 0);
  });
  const lastRun = !running && !!status?.mode && !!kpis; // a run happened in this session and nothing is running now
  const model = kpis?.models.map((m) => m.replace(/^[^/]+\//, "")).join(" · ") || "-";
  return (
    <>
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          aria-label={`Run options: ${order}`}
          className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1.5 text-[12px] font-medium capitalize text-tx2 hover:border-brand-bright hover:text-tx focus-visible:outline-2"
        >
          {order}
          <ChevronDown size={13} aria-hidden />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={4} className="z-50 w-64 rounded-lg border border-line bg-surface p-1.5 shadow-lg">
          <DropdownMenu.Label className="px-1.5 pb-1 text-[10.5px] uppercase tracking-wide text-tx3">Run order</DropdownMenu.Label>
          <DropdownMenu.RadioGroup value={order} onValueChange={(v) => setOrder(v as RunOrder)}>
            {ORDERS.map((o) => (
              <DropdownMenu.RadioItem
                key={o.id}
                value={o.id}
                disabled={running}
                className="flex cursor-pointer items-start gap-2 rounded px-1.5 py-1 text-[12.5px] text-tx outline-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-2"
              >
                <span className="mt-0.5 flex h-3.5 w-3.5 shrink-0 items-center justify-center">
                  <DropdownMenu.ItemIndicator>
                    <Check size={13} aria-hidden />
                  </DropdownMenu.ItemIndicator>
                </span>
                <span>
                  {o.label}
                  <span className="block text-[11px] text-tx3">{o.hint}</span>
                </span>
              </DropdownMenu.RadioItem>
            ))}
          </DropdownMenu.RadioGroup>
          {lastRun && kpis && (
            <>
              <DropdownMenu.Separator className="my-1.5 h-px bg-line" />
              <DropdownMenu.Label className="px-1.5 pb-1 text-[10.5px] uppercase tracking-wide text-tx3">Last run</DropdownMenu.Label>
              <div aria-label="Last run" data-last-run className="mono grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 px-1.5 pb-1 text-[12px] text-tx2">
                <span>handled</span><span className="text-right text-tx">{kpis.events_with_trace}/{kpis.events_total}</span>
                <span>writes</span><span className="text-right text-tx">{kpis.writes}</span>
                <span>failed</span><span className={`text-right ${kpis.failed ? "text-fail" : "text-tx"}`}>{kpis.failed}</span>
                <span>escalated</span><span className="text-right text-tx">{kpis.escalations}</span>
                <span>cost</span><span className="text-right text-tx">{usd(kpis.cost_usd)}</span>
                <span>model</span><span className="truncate text-right text-tx" title={model}>{model}</span>
              </div>
            </>
          )}
          {running && kpis && (
            <>
              <DropdownMenu.Separator className="my-1.5 h-px bg-line" />
              <div aria-label="Live counters" className="mono grid grid-cols-2 gap-x-3 gap-y-0.5 px-1.5 pb-1 text-[11.5px] text-tx2">
                <span>handled</span><span className="text-right text-tx">{kpis.events_with_trace}/{kpis.events_total}</span>
                <span>writes</span><span className="text-right text-tx">{kpis.writes}</span>
                <span>failed</span><span className={`text-right ${kpis.failed ? "text-fail" : "text-tx"}`}>{kpis.failed}</span>
                <span>escalated</span><span className="text-right text-tx">{kpis.escalations}</span>
                <span>LLM cost</span><span className="text-right text-tx">{usd(kpis.cost_usd)}</span>
              </div>
            </>
          )}
          <DropdownMenu.Separator className="my-1.5 h-px bg-line" />
          <DropdownMenu.Item
            onSelect={() => setResetOpen(true)}
            title="Remove the judge events, the live run and this session's state"
            className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-[12.5px] text-tx2 outline-none data-[highlighted]:bg-surface-2 data-[highlighted]:text-tx"
          >
            <Undo2 size={13} aria-hidden /> Reset...
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
    <Dialog
      open={resetOpen}
      onOpenChange={setResetOpen}
      title="Reset everything?"
      description="This removes the following and returns the app to its starting state."
      footer={
        <>
          <button onClick={() => setResetOpen(false)} className={btnSecondary}>
            Keep it
          </button>
          <button
            onClick={() => reset.mutate(undefined, { onSuccess: () => setResetOpen(false) })}
            disabled={reset.isPending || running || preview.data?.running}
            className={btnPrimary}
          >
            {reset.isPending ? "Resetting..." : "Reset"}
          </button>
        </>
      }
    >
      <ul data-reset-list className="space-y-1 text-[13px] text-tx2">
        <li>Judge events: <b className="mono text-tx">{preview.data?.judge_events ?? "..."}</b></li>
        <li>Live-run traces: <b className="mono text-tx">{preview.data?.live_traces ?? "..."}</b> and action-log rows: <b className="mono text-tx">{preview.data?.live_log_rows ?? "..."}</b></li>
        <li>Acknowledgements: <b className="mono text-tx">{acks}</b></li>
        <li>Active filters: <b className="mono text-tx">{filters}</b></li>
        <li>Activity items: <b className="mono text-tx">{activityCount}</b></li>
      </ul>
      {(running || preview.data?.running) && <p className="mt-2 text-[12px] text-warn">A run is in progress: cancel it first.</p>}
      <p className="mt-2 text-[11.5px] text-tx3">The tutorial state is not touched.</p>
    </Dialog>
    </>
  );
}
