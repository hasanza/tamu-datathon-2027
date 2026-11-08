import { useRef, type ReactNode } from "react";
import * as Popover from "@radix-ui/react-popover";
import * as Checkbox from "@radix-ui/react-checkbox";
import { Check, ChevronDown } from "lucide-react";

export interface FilterOption<T extends string> {
  value: T;
  label: string;
  count?: number;
  /** colour dot (a CSS colour) or any small node */
  dot?: string;
  icon?: ReactNode;
}

/**
 * Multi-select filter: a trigger with the label and a count badge ("Type · 2") that opens a checkbox list.
 * Opening focuses the first checkbox; Esc or an outside click closes it and returns focus to the trigger.
 */
export function FilterMenu<T extends string>({
  label,
  options,
  selected,
  onChange,
  open,
  onOpenChange,
}: {
  label: string;
  options: FilterOption<T>[];
  selected: T[];
  onChange: (next: T[]) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const first = useRef<HTMLButtonElement>(null);
  const toggle = (v: T) => onChange(selected.includes(v) ? selected.filter((x) => x !== v) : [...selected, v]);
  return (
    <Popover.Root open={open} onOpenChange={onOpenChange}>
      <Popover.Trigger asChild>
        <button
          data-filter={label}
          className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[12px] font-medium focus-visible:outline-2 ${
            selected.length ? "border-brand-bright text-tx" : "border-line text-tx2 hover:border-brand-bright hover:text-tx"
          }`}
        >
          {label}
          {selected.length > 0 && <span className="mono rounded bg-brand px-1 text-[10.5px] text-white">{selected.length}</span>}
          <ChevronDown size={13} aria-hidden />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          align="start"
          sideOffset={4}
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            first.current?.focus();
          }}
          className="z-50 w-60 rounded-lg border border-line bg-surface p-1.5 shadow-lg"
        >
          <ul role="group" aria-label={`${label} filter`} className="max-h-72 overflow-auto">
            {options.map((o, i) => {
              const id = `fm-${label}-${o.value}`.replace(/\W+/g, "-");
              return (
                <li key={o.value}>
                  <label htmlFor={id} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 text-[12.5px] text-tx hover:bg-surface-2">
                    <Checkbox.Root
                      id={id}
                      ref={i === 0 ? first : undefined}
                      checked={selected.includes(o.value)}
                      onCheckedChange={() => toggle(o.value)}
                      className="flex h-4 w-4 shrink-0 items-center justify-center rounded border border-line bg-bg data-[state=checked]:border-brand-bright data-[state=checked]:bg-brand focus-visible:outline-2"
                    >
                      <Checkbox.Indicator>
                        <Check size={12} className="text-white" aria-hidden />
                      </Checkbox.Indicator>
                    </Checkbox.Root>
                    {o.dot && <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: o.dot }} aria-hidden />}
                    {o.icon}
                    <span className="min-w-0 flex-1 truncate">{o.label}</span>
                    {o.count !== undefined && <span className="mono text-[11px] text-tx3">{o.count}</span>}
                  </label>
                </li>
              );
            })}
          </ul>
          <div className="mt-1 flex justify-between border-t border-line px-1.5 pt-1.5 text-[11.5px]">
            <button onClick={() => onChange(options.map((o) => o.value))} className="text-tx2 hover:text-tx">
              Select all
            </button>
            <button onClick={() => onChange([])} disabled={selected.length === 0} className="text-tx2 hover:text-tx disabled:opacity-40">
              Clear
            </button>
          </div>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
