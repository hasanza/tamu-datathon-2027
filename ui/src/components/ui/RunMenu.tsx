import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { Check, ChevronDown } from "lucide-react";
import { useKpis } from "../../api/hooks";
import { usd } from "../../lib/format";
import { useRunMode, type RunOrder } from "../../state";

const ORDERS: { id: RunOrder; label: string; hint: string }[] = [
  { id: "sequential", label: "Sequential", hint: "one event at a time (default)" },
  { id: "parallel", label: "Parallel", hint: "several at once, each in its own fresh world" },
];

/** Run options beside the Run feed button: Sequential/Parallel, and while a run is live its counters. */
export function RunMenu({ running }: { running: boolean }) {
  const { order, setOrder } = useRunMode();
  const kpis = useKpis().data;
  return (
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
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
