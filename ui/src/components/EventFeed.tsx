import { useEffect, useMemo, useRef, useState } from "react";
import { Bell, ClipboardCheck, ListChecks, Mail, MessageSquare, Newspaper, Radio, Search, Siren } from "lucide-react";
import type { EventCategory, FeedEvent, Status } from "../api/types";
import { CATEGORY_META, sourceIconName, STATUS_META } from "../lib/meta";
import { clip } from "../lib/format";
import { CategoryBadge, ConfidenceRing, Empty, ErrorBox, Loading, StatusChip } from "./ui/primitives";

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
      );
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
    return { c: [...c], s: [...s] };
  }, [events, processing]);

  return (
    <div data-feed className="flex h-full min-h-0 flex-col">
      <div className="space-y-2 border-b border-line p-3">
        <div className="flex items-center justify-between">
          <h2 className="text-[13px] font-semibold tracking-tight">Event feed</h2>
          <span className="text-[11px] text-tx3">
            {rows.length}/{events?.length ?? 0} · <kbd className="mono">j</kbd>/<kbd className="mono">k</kbd> to move
          </span>
        </div>
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
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by category">
          {present.c.map((c) => (
            <FilterChip key={c} active={cats.has(c)} color={CATEGORY_META[c].color} onClick={() => setCats(toggle(cats, c))}>
              {CATEGORY_META[c].label}
            </FilterChip>
          ))}
        </div>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Filter by status">
          {present.s.map((s) => (
            <FilterChip key={s} active={stats.has(s)} color={STATUS_META[s].color} onClick={() => setStats(toggle(stats, s))}>
              {STATUS_META[s].label}
            </FilterChip>
          ))}
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {loading && <Loading label="Loading events" />}
        {error && <ErrorBox message={error.message} onRetry={onRetry} />}
        {!loading && !error && rows.length === 0 && (
          <Empty title="No events match" hint={events?.length ? "Clear the filters or search." : "The feed is empty."} />
        )}
        <ul ref={listRef} role="list" className="divide-y divide-line">
          {rows.map((e) => {
            const sel = e.event_id === selected;
            const flash = recent[e.event_id];
            return (
              <li key={e.event_id} className="relative">
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
                    </div>
                  </div>
                  <ConfidenceRing value={e.confidence} />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
