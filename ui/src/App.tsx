import { useCallback, useEffect, useMemo, useRef } from "react";
import { useEvents, useTrace } from "./api/hooks";
import { useLiveStream } from "./api/stream";
import { EventFeed } from "./components/EventFeed";
import { ActivityLog, EscalationInbox } from "./components/RightRail";
import { TopBar } from "./components/TopBar";
import { useRoute } from "./lib/route";
import { useTour } from "./components/useTour";
import { ShortcutsDialog, useShortcuts } from "./components/Shortcuts";
import { useRunStatus } from "./api/hooks";
import { AboutPage } from "./views/AboutPage";
import { EventDetail } from "./views/EventDetail";
import { OntologyPage } from "./views/OntologyPage";

export default function App() {
  const { route, go } = useRoute();
  const events = useEvents();
  const stream = useLiveStream();
  // custom runs in flight appear in the feed (as "processing") before the API lists them
  const feedEvents = useMemo(() => {
    if (!events.data) return events.data;
    const known = new Set(events.data.map((e) => e.event_id));
    return [...events.data, ...stream.pendingCustom.filter((p) => !known.has(p.event_id)).map(({ at: _at, ...row }) => row)];
  }, [events.data, stream.pendingCustom]);
  // nothing is selected until the reader picks (or follows a deep link): the event pane then shows what to do first
  const selectedId = route.eventId;
  const { clearAll } = stream;
  useEffect(() => {
    window.addEventListener("ct-reset-all", clearAll);
    return () => window.removeEventListener("ct-reset-all", clearAll);
  }, [clearAll]);
  const runStatus = useRunStatus().data;
  // events that have arrived (what the feed lists): judge events and preset events that are not queued
  const arrivedEvents = useMemo(() => (feedEvents ?? []).filter((e) => e.custom || e.status !== "queued" || stream.processing.has(e.event_id)), [feedEvents, stream.processing]);
  useTour({ tower: route.page === "tower", selectedId, feedReady: !!events.data?.length, runState: runStatus?.state, arrivedCount: arrivedEvents.length });
  const keys = useShortcuts(selectedId);
  const presetTotal = (events.data ?? []).filter((e) => !e.custom).length || 15;
  const selected = feedEvents?.find((e) => e.event_id === selectedId);
  const trace = useTrace(selectedId);
  const lastVersion = useRef<string>();
  if (trace.data) lastVersion.current = trace.data.pipeline_version;
  const select = useCallback(
    (id: string) => {
      go(id);
      // Stacked (phone) layout: the detail sits below the feed, so bring it into view when an event is picked.
      if (window.matchMedia("(max-width: 767px)").matches)
        window.setTimeout(() => document.getElementById("event-detail")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50);
    },
    [go],
  );

  return (
    <div className="flex h-full flex-col">
      <ShortcutsDialog open={keys.help} onOpenChange={keys.setHelp} />
      <TopBar page={route.page} go={go} version={lastVersion.current} finished={stream.finished} total={presetTotal} activityCount={stream.items.length} />
      <main className="min-h-0 flex-1 overflow-y-auto xl:overflow-hidden">
        {route.page === "ontology" && <OntologyPage />}
        {route.page === "about" && <AboutPage />}
        {route.page === "tower" && (
          <div className="grid min-h-full grid-cols-1 md:grid-cols-[280px_1fr] xl:h-full xl:grid-cols-[minmax(280px,23fr)_minmax(0,54fr)_minmax(280px,23fr)]">
            <aside aria-label="Event feed" className="min-h-0 border-b border-line md:overflow-hidden md:border-b-0 md:border-r max-md:max-h-[420px]">
              <EventFeed
                events={feedEvents}
                loading={events.isLoading}
                error={events.error}
                onRetry={() => void events.refetch()}
                selected={selectedId}
                onSelect={select}
                processing={stream.processing}
                recent={stream.recent}
                incoming={stream.incoming}
                running={!!runStatus?.running}
                total={presetTotal}
              />
            </aside>
            <section id="event-detail" aria-label="Event detail" className="min-h-0 min-w-0 md:overflow-hidden">
              <EventDetail events={arrivedEvents} onSelect={select} event={selected} processing={!!selectedId && stream.processing.has(selectedId)} liveSteps={selectedId ? stream.liveSteps[selectedId] : undefined} />
            </section>
            <aside
              aria-label="Escalations and activity"
              className="min-h-0 space-y-4 border-t border-line p-3 md:col-span-2 xl:col-span-1 xl:flex xl:flex-col xl:gap-3 xl:space-y-0 xl:overflow-hidden xl:border-l xl:border-t-0"
            >
              <EscalationInbox events={events.data} onSelect={select} />
              <ActivityLog
                live={stream.live}
                items={stream.items}
                replay={stream.replay}
                setReplay={stream.setReplay}
                clear={stream.clear}
                onSelect={select}
              />
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}
