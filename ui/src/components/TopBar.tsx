import { useEffect, useState } from "react";
import { Moon, Play, Square, Sun, TriangleAlert } from "lucide-react";
import { useRunStatus } from "../api/hooks";
import type { Page } from "../lib/route";
import { useTheme } from "../state";
import { RunMenu } from "./ui/RunMenu";
import { useCancelRun, useRun } from "./useRun";
import { btnPrimary, btnSecondary, Dialog } from "./ui/Dialog";

const NAV: { page: Page; label: string }[] = [
  { page: "tower", label: "Control tower" },
  { page: "ontology", label: "Ontology" },
  { page: "about", label: "About" },
];

const FEED_ESTIMATE_S = 17 * 60; // CORE's figure for a full run: about 17 minutes

/** "event 7 of 15 - ~6 min left", from the run's start time and the events the stream has reported finished. */
function RunProgress({ started, finished, total }: { started: number | null; finished: number; total: number }) {
  const cancel = useCancelRun();
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now() / 1000), 15000);
    return () => window.clearInterval(t);
  }, []);
  const elapsed = started ? Math.max(0, now - started) : 0;
  const remaining = finished > 0 ? (elapsed / finished) * Math.max(total - finished, 0) : Math.max(FEED_ESTIMATE_S - elapsed, 60);
  const mins = Math.max(1, Math.round(remaining / 60));
  return (
    <span data-run-progress role="status" className="inline-flex items-center gap-2 text-[12px] text-tx2">
      <span className="mono">
        event {Math.min(finished + 1, total)} of {total} - ~{mins} min left
      </span>
      <button
        onClick={() => cancel.mutate()}
        disabled={cancel.isPending}
        className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[12px] text-tx2 hover:border-fail hover:text-tx disabled:opacity-60"
      >
        <Square size={11} aria-hidden /> {cancel.isPending ? "Cancelling..." : "Cancel"}
      </button>
    </span>
  );
}

export function TopBar({
  page,
  go,
  version,
  finished = 0,
  total = 15,
  activityCount = 0,
}: {
  page: Page;
  go: (p: Page) => void;
  version?: string;
  finished?: number;
  total?: number;
  activityCount?: number;
}) {
  const [confirmRun, setConfirmRun] = useState(false);
  // the empty state's "Run feed" button asks for the same confirmation
  useEffect(() => {
    const on = () => setConfirmRun(true);
    window.addEventListener("ct-run-feed", on);
    return () => window.removeEventListener("ct-run-feed", on);
  }, []);
  const { theme, toggle } = useTheme();
  const run = useRun();
  const status = useRunStatus().data;
  const running = !!status?.running;
  return (
    <header className="shrink-0 border-b-2 border-brand bg-surface">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 px-4 py-2">
        <h1 className="text-lg font-semibold tracking-tight" title={version ? `Pipeline v${version}` : undefined}>
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
          {!running && (status?.state === "aborted" || status?.state === "failed") && (
            <span
              role="alert"
              title={status.message ?? `The run ended with exit code ${status.exit_code}`}
              className="inline-flex max-w-[22rem] items-center gap-1.5 rounded-md border px-2 py-1 text-[12px] font-medium"
              style={{ color: "var(--fail)", borderColor: "color-mix(in srgb, var(--fail) 45%, transparent)", background: "color-mix(in srgb, var(--fail) 12%, transparent)" }}
            >
              <TriangleAlert size={13} className="shrink-0" aria-hidden />
              <span className="truncate">
                {status.state === "aborted" ? "Run aborted" : "Run failed"}
                {status.message ? `: ${status.message.replace(/^ABORTED:\s*/, "")}` : ""}
              </span>
            </span>
          )}
          {running && <RunProgress started={status?.started ?? null} finished={finished} total={total} />}
          <button
            onClick={() => setConfirmRun(true)}
            disabled={run.isPending || running}
            className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-[13px] font-medium text-white hover:bg-brand-bright disabled:opacity-60"
          >
            <Play size={14} aria-hidden /> {run.isPending ? "Starting…" : running ? "Running…" : "Run feed"}
          </button>
          <RunMenu running={running} activityCount={activityCount} />
          <Dialog
            open={confirmRun}
            onOpenChange={setConfirmRun}
            title="Run the whole feed?"
            description={`Runs all ${total} events against a fresh scored server (about 17 minutes, around $0.90). Replaces the current live run.`}
            footer={
              <>
                <button onClick={() => setConfirmRun(false)} className={btnSecondary}>
                  Not now
                </button>
                <button
                  onClick={() => {
                    setConfirmRun(false);
                    run.mutate({ all: true });
                  }}
                  className={btnPrimary}
                >
                  Run feed
                </button>
              </>
            }
          />
          <button
            onClick={toggle}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
            className="rounded-md border border-line p-1.5 text-tx2 hover:border-brand-bright hover:text-tx"
          >
            {theme === "dark" ? <Sun size={16} aria-hidden /> : <Moon size={16} aria-hidden />}
          </button>
          <div className="hidden whitespace-nowrap text-[12px] font-bold leading-none tracking-tight text-tx sm:block" aria-label="Hitachi Digital Services">
            HITACHI <span className="font-medium text-tx2">Digital Services</span>
          </div>
        </div>
      </div>
    </header>
  );
}
