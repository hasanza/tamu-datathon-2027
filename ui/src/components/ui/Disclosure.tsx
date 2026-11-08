import { useState, type ReactNode } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { safeStorage } from "../../lib/format";

/**
 * A labelled trigger that opens more detail below it (progressive disclosure, two levels at most).
 * `summary` is the trigger text ("Show the original message"); `count` is shown next to it so the closed state still says
 * how much is hidden. With `storageKey` the open state is remembered per viewer (localStorage, optional).
 */
export function Disclosure({
  summary,
  count,
  defaultOpen = false,
  storageKey,
  className = "",
  children,
}: {
  summary: ReactNode;
  count?: number;
  defaultOpen?: boolean;
  storageKey?: string;
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpenState] = useState(() => {
    const saved = storageKey ? safeStorage(storageKey) : null;
    return saved === "1" ? true : saved === "0" ? false : defaultOpen;
  });
  const setOpen = (v: boolean) => {
    setOpenState(v);
    if (storageKey) safeStorage(storageKey, v ? "1" : "0");
  };
  return (
    <div className={className}>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="inline-flex items-center gap-1 text-[12px] text-tx3 hover:text-tx focus-visible:outline-2">
        {open ? <ChevronDown size={13} aria-hidden /> : <ChevronRight size={13} aria-hidden />}
        <span>{summary}</span>
        {count !== undefined && <span className="mono rounded bg-surface-2 px-1 text-[10.5px] text-tx2">{count}</span>}
      </button>
      {open && <div className="mt-1.5">{children}</div>}
    </div>
  );
}
