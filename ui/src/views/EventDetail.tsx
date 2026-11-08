import { useEffect, useState } from "react";
import { FlaskConical, Play } from "lucide-react";
import { isNotFound, useTrace } from "../api/hooks";
import { isCustomId, type FeedEvent, type Status } from "../api/types";
import { TARGET_META, targetOf } from "../lib/target";
import { CATEGORY_META } from "../lib/meta";
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

export const TABS = ["Summary", "Orchestration", "Graph", "Actions", "Audit"] as const;
type Tab = (typeof TABS)[number];

/** Nothing selected: say what to do first. One quick pick per category (the first event of each), the two ways to start a run. */
function PickEvent({ events, onSelect }: { events?: FeedEvent[]; onSelect?: (id: string) => void }) {
  const picks = new Map<string, FeedEvent>();
  for (const e of events ?? []) if (e.category && !picks.has(e.category)) picks.set(e.category, e);
  return (
    <div data-pick-event className="flex h-full flex-col items-center justify-center gap-4 px-6 text-center">
      <div>
        <h2 className="text-[16px] font-semibold text-tx">Pick an event from the feed</h2>
        <p className="mt-1 max-w-md text-[13px] text-tx3">See what the four agents did with it and why. Or start something yourself:</p>
      </div>
      <div className="flex flex-wrap justify-center gap-2">
        <button onClick={() => window.dispatchEvent(new Event("ct-run-feed"))} className="inline-flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-[13px] font-medium text-white hover:bg-brand-bright">
          <Play size={14} aria-hidden /> Run feed
        </button>
        <button onClick={() => window.dispatchEvent(new Event("ct-open-custom"))} className="inline-flex items-center gap-1.5 rounded-md border border-brand px-3 py-1.5 text-[13px] font-medium text-tx hover:border-brand-bright">
          <FlaskConical size={14} className="text-brand-bright" aria-hidden /> Try your own event
        </button>
      </div>
      {picks.size > 0 && (
        <div className="flex max-w-xl flex-wrap justify-center gap-1.5" role="group" aria-label="Quick picks">
          {[...picks.entries()].map(([cat, e]) => {
            const m = CATEGORY_META[cat as keyof typeof CATEGORY_META];
            return (
              <button
                key={cat}
                onClick={() => onSelect?.(e.event_id)}
                className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[12px] text-tx2 hover:border-brand-bright hover:text-tx"
              >
                <span className="h-2 w-2 rounded-full" style={{ background: m?.color }} aria-hidden />
                {m?.label ?? cat}
                <span className="mono text-tx3">{e.event_id}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function EventDetail({ event, processing, liveSteps, events, onSelect }: { event: FeedEvent | undefined; processing: boolean; liveSteps?: LiveStep[]; events?: FeedEvent[]; onSelect?: (id: string) => void }) {
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

  if (!event) return <PickEvent events={events} onSelect={onSelect} />;

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
              data-tour="run-event"
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
          <p className="flex items-center gap-1.5 text-xs text-tx3">
            <FlaskConical size={13} className="shrink-0" style={{ color: "var(--cat-compound)" }} aria-hidden />
            Sandbox server · same agents and MCP client · scored log untouched
          </p>
        )}
        <div role="tablist" aria-label="Event views" className="scroll-shadow-x -mb-px flex gap-1 overflow-x-auto [--shadow-surface:var(--bg)]">
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
                tab === name ? "border-brand-bright font-semibold text-tx" : "border-transparent text-tx3 hover:text-tx"
              }`}
            >
              {name}
              {name === "Actions" && t ? <span className={`mono ml-1.5 text-[11px] ${tab === name ? "text-tx" : "text-tx3"}`}>{t.actions.length}</span> : null}
            </button>
          ))}
        </div>
      </div>

      <div id="tabpanel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="scroll-shadow-y min-h-0 flex-1 overflow-y-auto p-4 [--shadow-surface:var(--bg)]">
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
