import { useEffect, useState } from "react";
import { FlaskConical, Play } from "lucide-react";
import { isNotFound, useTrace } from "../api/hooks";
import { isCustomId, type FeedEvent, type Status } from "../api/types";
import { TARGET_META, targetOf } from "../lib/target";
import { SourceIcon } from "../components/EventFeed";
import { useRun } from "../components/useRun";
import { CategoryBadge, Chip, ConfidenceRing, Empty, ErrorBox, Loading, StatusChip } from "../components/ui/primitives";
import { dateTime } from "../lib/format";
import { ActionsTab } from "./ActionsTab";
import { AuditTab } from "./AuditTab";
import { GraphTab } from "./GraphTab";
import { LiveOrchestration, OrchestrationTab } from "./OrchestrationTab";
import type { LiveStep } from "../api/stream";
import { SummaryTab } from "./SummaryTab";

const TABS = ["Summary", "Orchestration", "Graph", "Actions", "Audit"] as const;
type Tab = (typeof TABS)[number];

export function EventDetail({ event, processing, liveSteps }: { event: FeedEvent | undefined; processing: boolean; liveSteps?: LiveStep[] }) {
  const id = event?.event_id ?? null;
  const trace = useTrace(id);
  const run = useRun();
  const [tab, setTab] = useState<Tab>("Summary");
  const [focus, setFocus] = useState<string[] | null>(null);

  useEffect(() => {
    setFocus(null);
  }, [id]);
  // the Activity rail asks for a tab ("open this event's Orchestration")
  useEffect(() => {
    const on = (e: Event) => {
      const want = (e as CustomEvent<string>).detail;
      if ((TABS as readonly string[]).includes(want)) setTab(want as Tab);
    };
    window.addEventListener("ct-open-tab", on);
    return () => window.removeEventListener("ct-open-tab", on);
  }, []);

  if (!event) return <Empty title="Select an event" hint="Pick an event from the feed (or press j / k) to see what the agents did and why." />;

  const t = trace.data;
  const target = targetOf(t, event.event_id);
  const sandbox = isCustomId(event.event_id) || !!event.custom;
  const status: Status = processing ? "processing" : (t?.status ?? event.status);
  // While an event runs, every throttled refresh of its (not yet existing) trace flips the query back to "loading".
  // That must not unmount the live view: it would remount the stages and replay their animation every few hundred ms.
  const loadingFirst = trace.isLoading && !processing;
  const queued = !t && !loadingFirst && (!trace.isError || isNotFound(trace.error));

  const showOnGraph = (ids: string[]) => {
    setFocus(ids);
    setTab("Graph");
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b border-line px-4 pt-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <h2 className="mono text-lg font-semibold">{event.event_id}</h2>
          <CategoryBadge category={t?.classification.category ?? event.category} />
          {status !== "done" && <StatusChip status={status} />}
          <Chip color={TARGET_META[target].color} title={`Calls went to ${TARGET_META[target].where}`}>{TARGET_META[target].label}</Chip>
          <span className="flex items-center gap-1.5 text-xs text-tx3">
            <SourceIcon source={event.source} /> {event.source} · <span className="mono" title={dateTime(event.received_at)}>{event.received_at.split("T")[1]?.slice(0, 5) ?? ""}</span>
          </span>
          <div className="ml-auto flex items-center gap-3">
            <ConfidenceRing value={t?.classification.confidence ?? event.confidence} size={34} />
            {!sandbox && (
            <button
              onClick={() => run.mutate({ eventId: event.event_id })}
              disabled={run.isPending}
              className="inline-flex items-center gap-1 rounded-md border border-line px-2.5 py-1 text-xs text-tx2 hover:border-brand-bright hover:text-tx disabled:opacity-60"
            >
              <Play size={12} aria-hidden /> Run this event
            </button>
            )}
          </div>
        </div>
        {sandbox && (
          <p className="flex items-center gap-1.5 rounded-md border border-line bg-surface-2 px-2.5 py-1.5 text-xs text-tx2">
            <FlaskConical size={13} className="shrink-0" style={{ color: "var(--cat-compound)" }} aria-hidden />
            Sandbox run: executed through the same MCP client as the feed against a private sandbox copy of the enterprise server. The scored action log is untouched.
          </p>
        )}
        <div role="tablist" aria-label="Event views" className="-mb-px flex gap-1 overflow-x-auto">
          {TABS.map((name) => (
            <button
              key={name}
              role="tab"
              id={`tab-${name}`}
              aria-selected={tab === name}
              aria-controls="tabpanel"
              onClick={() => setTab(name)}
              onKeyDown={(e) => {
                const i = TABS.indexOf(name);
                const to =
                  e.key === "ArrowRight" ? (i + 1) % TABS.length
                  : e.key === "ArrowLeft" ? (i + TABS.length - 1) % TABS.length
                  : e.key === "Home" ? 0
                  : e.key === "End" ? TABS.length - 1
                  : -1;
                if (to < 0) return;
                e.preventDefault();
                const next = TABS[to] as Tab;
                setTab(next);
                document.getElementById(`tab-${next}`)?.focus(); // roving tabindex: focus must follow the selection
              }}
              tabIndex={tab === name ? 0 : -1}
              className={`whitespace-nowrap border-b-2 px-3 py-2 text-[13px] font-medium ${
                tab === name ? "border-brand-bright text-tx" : "border-transparent text-tx3 hover:text-tx"
              }`}
            >
              {name}
              {name === "Actions" && t ? <span className="mono ml-1.5 text-[11px] text-tx3">{t.actions.length}</span> : null}
            </button>
          ))}
        </div>
      </div>

      <div id="tabpanel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="min-h-0 flex-1 overflow-y-auto p-4">
        {loadingFirst && <Loading label="Loading trace" />}
        {trace.isError && !isNotFound(trace.error) && <ErrorBox message={(trace.error as Error).message} onRetry={() => void trace.refetch()} />}
        {queued && (
          <div className="space-y-4">
            <Empty
              title={processing ? "Processing" : "Queued: no trace yet"}
              hint={processing ? "The agents are working on this event. The trace appears here when it completes." : "This event has not been run through the pipeline. Use Run this event, or Run feed in the top bar."}
            />
            <blockquote className="rounded-lg border border-line bg-surface p-3 text-[13px] text-tx2">{event.text}</blockquote>
            {/* the agents work for seconds to minutes before the trace exists: stream their cards meanwhile */}
            {processing && liveSteps && liveSteps.length > 0 && <LiveOrchestration steps={liveSteps} eventId={event.event_id} />}
          </div>
        )}
        {t && tab === "Summary" && <SummaryTab key={t.event_id} trace={t} />}
        {t && tab === "Orchestration" && <OrchestrationTab key={t.event_id} trace={t} />}
        {t && tab === "Graph" && <GraphTab key={t.event_id} trace={t} focus={focus} onClearFocus={() => setFocus(null)} />}
        {t && tab === "Actions" && <ActionsTab key={t.event_id} trace={t} onShowOnGraph={showOnGraph} />}
        {t && tab === "Audit" && <AuditTab key={t.event_id} trace={t} />}
      </div>
    </div>
  );
}
