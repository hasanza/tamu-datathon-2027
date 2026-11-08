import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Bell, ClipboardCheck, ListChecks, Mail, MessageSquare, Newspaper, Radio, Search, Siren } from "lucide-react";
import type { EventCategory, FeedEvent, Status } from "../api/types";
import { CATEGORY_META, sourceIconName, STATUS_META } from "../lib/meta";
import { newestFirst } from "../lib/escalation";
import { clip } from "../lib/format";
import { CustomEventCard } from "./CustomEventCard";
import { CategoryBadge, Chip, ConfidenceRing, Empty, ErrorBox, Loading, StatusChip } from "./ui/primitives";

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

function toggle<T>(set: Set<T>, v: T): Set<T> {
  const n = new Set(set);
  if (n.has(v)) n.delete(v);
  else n.add(v);
  return n;
}

function FilterChip({ active, color, onClick, children }: { active: boolean; color: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      style={active ? { borderColor: color, color } : undefined}
      className={`rounded-md border px-1.5 py-0.5 text-[11px] font-medium ${active ? "bg-surface-2" : "border-line text-tx3 hover:text-tx"}`}
    >
      {children}
    </button>
  );
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
}

export function EventFeed({ events, loading, error, onRetry, selected, onSelect, processing, recent }: Props) {
  const [q, setQ] = useState("");
  const [cats, setCats] = useState<Set<EventCategory>>(new Set());
  const [stats, setStats] = useState<Set<Status>>(new Set());
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

  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (events ?? [])
      .map((e) => ({ ...e, status: (processing.has(e.event_id) ? "processing" : e.status) as Status }))
      .filter(
        (e) =>
          (cats.size === 0 || (e.category && cats.has(e.category))) &&
          (stats.size === 0 || stats.has(e.status)) &&
          (!needle || `${e.event_id} ${e.text} ${e.source}`.toLowerCase().includes(needle)),
      )
      .sort(newestFirst); // judge input first (highest C-nn on top), then the preset events in E-01..E-15 order
  }, [events, q, cats, stats, processing]);

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

  const present = useMemo(() => {
    const c = new Set<EventCategory>();
    const s = new Set<Status>();
    for (const e of events ?? []) {
      if (e.category) c.add(e.category);
      s.add(processing.has(e.event_id) ? "processing" : e.status);
    }
    for (const x of cats) c.add(x); // an active filter chip must stay visible even when nothing matches it any more
    for (const x of stats) s.add(x);
    return { c: [...c], s: [...s] };
  }, [events, processing, cats, stats]);
  const filtered = q !== "" || cats.size > 0 || stats.size > 0;
  const clearFilters = () => {
    setQ("");
    setCats(new Set());
    setStats(new Set());
  };

  return (
    <div data-feed className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b border-line p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-[13px] font-semibold tracking-tight">Event feed</h2>
          <span className="text-[11px] text-tx3">
            {rows.length}/{events?.length ?? 0} · <kbd className="mono">j</kbd>/<kbd className="mono">k</kbd> to move
          </span>
        </div>
        <CustomEventCard onCreated={onSelect} />
        <label className="relative block">
          <span className="sr-only">Search events</span>
          <Search size={14} className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-tx3" aria-hidden />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search id, text, source"
            className="w-full rounded-md border border-line bg-surface-2 py-1.5 pl-7 pr-2 text-[13px] text-tx placeholder:text-tx3"
          />
        </label>
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter by category">
          <span className="w-12 text-[10px] uppercase tracking-wide text-tx3" aria-hidden>Type</span>
          {present.c.map((c) => (
            <FilterChip key={c} active={cats.has(c)} color={CATEGORY_META[c].color} onClick={() => setCats(toggle(cats, c))}>
              {CATEGORY_META[c].label}
            </FilterChip>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-1" role="group" aria-label="Filter by status">
          <span className="w-12 text-[10px] uppercase tracking-wide text-tx3" aria-hidden>Status</span>
          {present.s.map((s) => (
            <FilterChip key={s} active={stats.has(s)} color={STATUS_META[s].color} onClick={() => setStats(toggle(stats, s))}>
              {STATUS_META[s].label}
            </FilterChip>
          ))}
        </div>
      </div>

      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {loading && <Loading label="Loading events" />}
        {error && <ErrorBox message={error.message} onRetry={onRetry} />}
        {!loading && !error && rows.length === 0 && (
          <Empty title="No events match" hint={events?.length ? "Clear the filters or search." : "The feed is empty."} />
        )}
        {!loading && !error && filtered && (
          <div className="border-b border-line p-2">
            <button onClick={clearFilters} className="rounded-md border border-line px-2 py-1 text-[11px] text-tx2 hover:border-brand-bright hover:text-tx">
              Clear filters
            </button>
          </div>
        )}
        <ul ref={listRef} role="list" className="divide-y divide-line">
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
                    <div className="flex flex-wrap items-center gap-1.5">
                      <CategoryBadge category={e.category} />
                      <StatusChip status={e.status} />
                      {e.custom && <Chip color="var(--cat-compound)">Sandbox</Chip>}
                    </div>
                  </div>
                  <ConfidenceRing value={e.confidence} />
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
