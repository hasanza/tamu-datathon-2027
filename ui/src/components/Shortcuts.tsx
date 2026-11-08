import { useEffect, useState } from "react";
import { isCustomId } from "../api/types";
import { TABS } from "../views/EventDetail";
import { Dialog } from "./ui/Dialog";
import { useRun } from "./useRun";

const KEYS: [string, string][] = [
  ["j / k", "Next / previous event in the feed"],
  ["/", "Focus the feed search"],
  ["r", "Run the selected event"],
  ["1 - 5", "Summary, Orchestration, Graph, Actions, Audit"],
  ["?", "Show or hide this list"],
];

/** Global keys. They never fire while typing, and stay out of the way of an open dialog or a modal tutorial step. */
export function useShortcuts(selectedId: string | null) {
  const [help, setHelp] = useState(false);
  const run = useRun();
  useEffect(() => {
    const on = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)) return;
      if (e.key === "?") {
        e.preventDefault();
        setHelp((h) => !h);
        return;
      }
      const modal = document.querySelector('[role="dialog"], [role="menu"], .driver-popover:not(.ct-tour-hint)');
      if (modal) return;
      if (e.key === "/") {
        const box = document.querySelector<HTMLInputElement>("[data-feed] input");
        if (box) {
          e.preventDefault();
          box.focus();
        }
      } else if (e.key === "r" && selectedId && !isCustomId(selectedId)) {
        e.preventDefault();
        if (!run.isPending) run.mutate({ eventId: selectedId });
      } else if (/^[1-5]$/.test(e.key) && selectedId) {
        window.dispatchEvent(new CustomEvent("ct-open-tab", { detail: TABS[Number(e.key) - 1] }));
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [selectedId, run]);
  return { help, setHelp };
}

export function ShortcutsDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Keyboard shortcuts">
      <dl data-shortcuts className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1.5 text-[13px]">
        {KEYS.map(([k, what]) => (
          <div key={k} className="contents">
            <dt>
              <kbd className="mono rounded border border-line bg-surface-2 px-1.5 py-0.5 text-[12px] text-tx">{k}</kbd>
            </dt>
            <dd className="text-tx2">{what}</dd>
          </div>
        ))}
      </dl>
    </Dialog>
  );
}
