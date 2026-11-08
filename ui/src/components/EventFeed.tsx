import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Bell, ClipboardCheck, ListChecks, Mail, MessageSquare, Newspaper, Radio, Search, Siren } from "lucide-react";
import type { EventCategory, FeedEvent, Status } from "../api/types";
import { CATEGORY_META, sourceIconName, STATUS_META } from "../lib/meta";
import { clip, safeStorage } from "../lib/format";
import { CustomEventCard } from "./CustomEventCard";
import { FilterMenu } from "./ui/FilterMenu";
import { FilterSummary, type FilterSegment } from "./ui/FilterSummary";
import { ConfidenceRing, Empty, ErrorBox, Loading, StatusChip } from "./ui/primitives";

const SOURCE_ICON = {
  chat: MessageSquare,
  news: Newspaper,
  quality: ClipboardCheck,
  mail: Mail,
  digest: ListChecks,
  alert: Siren,
  radio: Radio,
} as const;

export function SourceIcon({ source, size = 14 }: { source: string; size?: number }) {
  const I = SOURCE_ICON[sourceIconName(source)] ?? Bell;
  return <I size={size} aria-label={source} className="shrink-0 text-tx3" />;
}

const customNo = (id: string) => (/^C-(\d+)$/.exec(id)?.[1] ? Number(/^C-(\d+)$/.exec(id)?.[1]) : -1);
/** Judge events first (highest C-nn on top), then the preset events, the latest to arrive (received) first. */
function arrivalOrder(a: FeedEvent, b: FeedEvent): number {
  const ca = customNo(a.event_id);
  const cb = customNo(b.event_id);
  if (ca >= 0 || cb >= 0) return ca >= 0 && cb >= 0 ? cb - ca : ca >= 0 ? -1 : 1;
  return a.received_at < b.received_at ? 1 : a.received_at > b.received_at ? -1 : b.event_id.localeCompare(a.event_id);
}

const FILTER_KEY = "ct-feed-filters";

/** Saved filters, validated against the known categories/statuses so a stale value cannot hide every row. */
function loadFilters(): { cats: EventCategory[]; stats: Status[] } {
  try {
    const raw = JSON.parse(safeStorage(FILTER_KEY) ?? "{}") as { cats?: unknown; stats?: unknown };
    const pick = <T extends string>(v: unknown, known: Record<string, unknown>): T[] =>
      Array.isArray(v) ? (v.filter((x) => typeof x === "string" && x in known) as T[]) : [];
    return { cats: pick<EventCategory>(raw.cats, CATEGORY_META), stats: pick<Status>(raw.stats, STATUS_META) };
  } catch {
    return { cats: [], stats: [] };
  }
}

interface Props {
  events: FeedEvent[] | undefined;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
  selected: string | null;
  onSelect: (id: string) => void;
  processing: Set<string>;
  recent: Record<string, number>;
  /** ids whose "incoming" notice arrived (about a second before the event itself) */
  incoming?: string[];
  running?: boolean;
  /** how many preset events a full run brings (15) */
  total?: number;
}

export function EventFeed({ events, loading, error, onRetry, selected, onSelect, processing, recent, incoming = [], running = false, total = 15 }: Props) {
  const [q, setQ] = useState("");
  const [saved] = useState(loadFilters);
  const [cats, setCats] = useState<EventCategory[]>(saved.cats);
  const [stats, setStats] = useState<Status[]>(saved.stats);
  const [menu, setMenu] = useState<"Type" | "Status" | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    safeStorage(FILTER_KEY, JSON.stringify({ cats, stats }));
  }, [cats, stats]);
  // "Back to snapshot" (top bar) throws the run away: the filters go with it
  useEffect(() => {
    const on = () => {
      setQ("");
      setCats([]);
      setStats([]);
    };
    window.addEventListener("ct-feed-reset", on);
    return () => window.removeEventListener("ct-feed-reset", on);
  }, []);
  const listRef = useRef<HTMLUListElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // A new judge event lands at the top of the list: bring the top into view so the user sees it appear.
  const customCount = (events ?? []).filter((e) => e.custom).length;
  const prevCustom = useRef(customCount);
  useEffect(() => {
    if (customCount > prevCustom.current) scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" });
    prevCustom.current = customCount;
  }, [customCount]);
  const cursor = useRef(selected); // tracks the selection synchronously so held/rapid keys do not read a stale value
  useEffect(() => {
    cursor.current = selected;
  }, [selected]);

  // the app must not look pre-populated: only events that have arrived are listed (judge events, and preset events that are
  // not queued any more). A queued event can still be opened by its link.
  const arrived = useMemo(
    () =>
      (events ?? [])
        .map((e) => ({ ...e, status: (processing.has(e.event_id) ? "processing" : e.status) as Status }))
        .filter((e) => e.custom || e.status !== "queued"),
    [events, processing],
  );
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return arrived
      .filter(
        (e) =>
          (cats.length === 0 || (e.category && cats.includes(e.category))) &&
          (stats.length === 0 || stats.includes(e.status)) &&
          (!needle || `${e.event_id} ${e.text} ${e.source}`.toLowerCase().includes(needle)),
      )
      .sort(arrivalOrder); // newest on top: judge input first (highest C-nn), then the preset events, the latest to arrive first
  }, [arrived, q, cats, stats]);

  // j/k and arrow keys move the selection unless the user is typing.
  useEffect(() => {
    const on = (ev: KeyboardEvent) => {
      const t = ev.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (ev.metaKey || ev.ctrlKey || ev.altKey || rows.length === 0) return;
      const down = ev.key === "j" || ev.key === "ArrowDown";
      const up = ev.key === "k" || ev.key === "ArrowUp";
      if (!down && !up) return;
      if (ev.key.startsWith("Arrow") && t && t !== document.body && !t.closest("[data-feed]")) return;
      ev.preventDefault();
      const i = rows.findIndex((r) => r.event_id === cursor.current);
      const next = rows[Math.min(rows.length - 1, Math.max(0, i + (down ? 1 : -1)))];
      if (next) {
        cursor.current = next.event_id;
        onSelect(next.event_id);
      }
    };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [rows, onSelect]);

  useEffect(() => {
    listRef.current?.querySelector('[aria-current="true"]')?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  // options and their counts come from the whole feed (not the filtered rows), so a menu always shows what exists
  const options = useMemo(() => {
    const c = new Map<EventCategory, number>();
    const st = new Map<Status, number>();
    for (const e of arrived) {
      if (e.category) c.set(e.category, (c.get(e.category) ?? 0) + 1);
      st.set(e.status, (st.get(e.status) ?? 0) + 1);
    }
    for (const k of Object.keys(CATEGORY_META) as EventCategory[]) if (!c.has(k)) c.set(k, 0); // the menu always lists all six types
    for (const x of stats) if (!st.has(x)) st.set(x, 0);
    return {
      cats: (Object.keys(CATEGORY_META) as EventCategory[]).filter((k) => c.has(k)).map((k) => ({ value: k, label: CATEGORY_META[k].label, dot: CATEGORY_META[k].color, count: c.get(k) })),
      stats: (Object.keys(STATUS_META) as Status[]).filter((k) => st.has(k)).map((k) => ({ value: k, label: STATUS_META[k].label, dot: STATUS_META[k].color, count: st.get(k) })),
    };
  }, [arrived, cats, stats]);
  const clearFilters = () => {
    setQ("");
    setCats([]);
    setStats([]);
  };
  const segments: FilterSegment[] = [
    ...(cats.length ? [{ label: "Type", value: String(cats.length), onOpen: () => setMenu("Type") }] : []),
    ...(stats.length ? [{ label: "Status", value: String(stats.length), onOpen: () => setMenu("Status") }] : []),
    ...(q.trim() ? [{ label: "Search", value: q.trim(), onOpen: () => searchRef.current?.focus() }] : []),
  ];

  return (
    <div data-feed className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b border-line p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-[13px] font-semibold tracking-tight">Event feed</h2>
          <span className="text-[11px] text-tx3" title="j / k (or the arrow keys) move the selection; ? lists all shortcuts">
            {running ? `${arrived.length} of ${total} arrived` : `${arrived.length} arrived`}
            {rows.length !== arrived.length && ` · ${rows.length} shown`}
          </span>
        </div>
        <CustomEventCard onCreated={onSelect} />
        <div className="flex items-center gap-1.5">
          <label className="relative block min-w-0 flex-1">
            <span className="sr-only">Search events</span>
            <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-tx3" aria-hidden />
            <input
              ref={searchRef}
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search id, text, source"
              className="w-full rounded-md border border-line bg-surface-2 py-1 pl-7 pr-2 text-[13px] text-tx placeholder:text-tx3"
            />
          </label>
          <FilterMenu label="Type" options={options.cats} selected={cats} onChange={setCats} open={menu === "Type"} onOpenChange={(o) => setMenu(o ? "Type" : null)} />
          <FilterMenu label="Status" options={options.stats} selected={stats} onChange={setStats} open={menu === "Status"} onOpenChange={(o) => setMenu(o ? "Status" : null)} />
        </div>
        <FilterSummary segments={segments} onClear={clearFilters} />
      </div>

      <div ref={scrollRef} className="scroll-shadow-y min-h-0 flex-1 overflow-y-auto [--shadow-surface:var(--bg)]">
        {loading && <Loading label="Loading events" />}
        {error && <ErrorBox message={error.message} onRetry={onRetry} />}
        {!loading && !error && arrived.length === 0 && incoming.length === 0 && (
          <Empty title="The feed is quiet" hint="Events arrive here as the feed runs. Press Run feed, or try your own event." />
        )}
        {!loading && !error && arrived.length > 0 && rows.length === 0 && <Empty title="No events match" hint="Clear the filters or search." />}
        <ul ref={listRef} role="list" className="divide-y divide-line">
          {incoming.map((id) => (
            <li key={`incoming-${id}`} data-incoming className="px-3 py-2.5" aria-label={`Incoming event ${id}`}>
              <div className="flex items-center gap-2 text-[12px]">
                <span className="mono font-medium text-tx3">{id}</span>
                <span className="text-tx2">Incoming event...</span>
              </div>
              <div className="incoming-bar mt-1.5" role="progressbar" aria-label="Waiting for the event to arrive" />
            </li>
          ))}
          {rows.map((e, i) => {
            const sel = e.event_id === selected;
            const flash = recent[e.event_id];
            const firstCustom = !!e.custom && !rows.slice(0, i).some((r) => r.custom);
            const firstPreset = !e.custom && !rows.slice(0, i).some((r) => !r.custom) && i > 0;
            return (
              <Fragment key={e.event_id}>
              {firstCustom && (
                <li role="presentation" className="bg-surface-2 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-tx3">
                  Judge input · sandbox ({rows.filter((r) => r.custom).length}) · newest first
                </li>
              )}
              {firstPreset && (
                <li role="presentation" className="bg-surface-2 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-tx3">
                  Preset events ({rows.filter((r) => !r.custom).length})
                </li>
              )}
              <li className="relative">
                {flash && <div key={flash} aria-hidden className="anim-flash pointer-events-none absolute inset-0" />}
                <button
                  onClick={() => onSelect(e.event_id)}
                  aria-current={sel ? "true" : undefined}
                  aria-label={`${e.event_id}, ${e.category ?? "pending"}, ${e.status}`}
                  className={`flex w-full gap-2.5 border-l-[3px] px-3 py-2.5 text-left transition-colors ${
                    sel ? "border-brand-bright bg-surface-2" : "border-transparent hover:bg-surface-2/60"
                  }`}
                >
                  <div className="flex w-12 shrink-0 flex-col items-start gap-1.5">
                    <span className="mono text-[12px] font-medium">{e.event_id}</span>
                    <SourceIcon source={e.source} />
                  </div>
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <p className="line-clamp-2 text-[13px] leading-snug text-tx2">{clip(e.text, 140)}</p>
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px]">
                      <StatusChip status={e.status} />
                      <span className="text-tx3" title={e.confidence == null ? undefined : `confidence ${Math.round(e.confidence * 100)}%`}>{e.category ? CATEGORY_META[e.category].label : "Pending"}</span>
                    </div>
                  </div>
                  {(e.confidence == null || e.confidence < 0.7) && <ConfidenceRing value={e.confidence} />}
                </button>
              </li>
              </Fragment>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
