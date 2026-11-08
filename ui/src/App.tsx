import { useCallback, useMemo, useRef } from "react";
import { useEvents, useKpis, useTrace } from "./api/hooks";
import { useLiveStream } from "./api/stream";
import { EventFeed } from "./components/EventFeed";
import { ActivityLog, EscalationInbox } from "./components/RightRail";
import { TopBar } from "./components/TopBar";
import { useRoute } from "./lib/route";
import { AboutPage } from "./views/AboutPage";
import { EventDetail } from "./views/EventDetail";
import { OntologyPage } from "./views/OntologyPage";

function Footer({ version }: { version: string | undefined }) {
  const kpis = useKpis();
  const models = kpis.data?.models.map((m) => m.replace(/^[^/]+\//, "")) ?? [];
  return (
    <footer className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-0.5 border-t border-line bg-surface px-4 py-1.5 text-[11px] text-tx3">
      <span>
        Models: <span className="mono text-tx2">{models.length ? models.join(", ") : "gemini-3.5-flash-lite, gemini-3.8-flash"}</span>
      </span>
      <span>
        Pipeline <span className="mono text-tx2">{version ? `v${version}` : "-"}</span>
      </span>
      <span className="ml-auto">Wacky Wheels Control Tower · Powered by Hitachi Digital Services</span>
    </footer>
  );
}

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
  const selectedId = route.eventId ?? feedEvents?.[0]?.event_id ?? null;
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
      <TopBar page={route.page} go={go} />
      <main className="min-h-0 flex-1 overflow-y-auto xl:overflow-hidden">
        {route.page === "ontology" && <OntologyPage />}
        {route.page === "about" && <AboutPage />}
        {route.page === "tower" && (
          <div className="grid min-h-full grid-cols-1 md:grid-cols-[280px_1fr] xl:h-full xl:grid-cols-[320px_minmax(0,1fr)_340px]">
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
              />
            </aside>
            <section id="event-detail" aria-label="Event detail" className="min-h-0 min-w-0 md:overflow-hidden">
              <EventDetail event={selected} processing={!!selectedId && stream.processing.has(selectedId)} />
            </section>
            <aside
              aria-label="Escalations and activity"
              className="min-h-0 space-y-4 border-t border-line p-3 md:col-span-2 xl:col-span-1 xl:overflow-y-auto xl:border-l xl:border-t-0"
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
      <Footer version={lastVersion.current} />
    </div>
  );
}
