import { Disclosure } from "./Disclosure";
import { Mono } from "./primitives";
import { clip, compactArgs, summarize } from "../../lib/format";

const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const present = ([, v]: [string, unknown]) => v !== null && v !== undefined && v !== "";

/** One value as short text: scalars as they are, a list as "3 vins", a nested object as "2 fields", a "h:..." handle as "list". */
export function shortValue(key: string, v: unknown): string {
  if (Array.isArray(v)) return `${v.length} ${v.length === 1 ? key.replace(/s$/, "") : key}`;
  if (isObj(v)) return `${Object.keys(v).length} fields`;
  if (typeof v === "string") return /^h:\S+$/.test(v) ? "list" : clip(v, 28);
  return String(v);
}

// a list item that is itself an object reads as a few words ("plant_id=P_TX · date=2027-03-19"), never as JSON
const itemText = (x: unknown) => (typeof x === "object" && x && !Array.isArray(x) ? summarize(x as Record<string, unknown>) : Array.isArray(x) ? `${x.length} items` : String(x));

/** Inline "key value" chips (up to `max`), lists and nested objects summarised, the rest as "+N more". The whole value is in the tooltip. */
export function KV({ value, max = 4 }: { value: Record<string, unknown> | null | undefined; max?: number }) {
  const entries = Object.entries(value ?? {}).filter(present);
  if (entries.length === 0) return <span className="text-tx3">-</span>;
  const shown = entries.slice(0, max);
  return (
    <span className="flex flex-wrap items-center gap-1" data-kv>
      {shown.map(([k, v]) => (
        <span
          key={k}
          title={Array.isArray(v) ? v.map(itemText).join(", ") : isObj(v) ? compactArgs(v) : undefined}
          className="mono inline-flex max-w-full items-baseline gap-1 rounded border border-line bg-surface-2 px-1 py-px text-[11px]"
        >
          <span className="text-tx3">{k}</span>
          <span className="truncate text-tx2">{shortValue(k, v)}</span>
        </span>
      ))}
      {entries.length > max && <span className="text-[11px] text-tx3" title={entries.slice(max).map(([k]) => k).join(", ")}>+{entries.length - max} more</span>}
    </span>
  );
}

/** A list as chips, capped at `limit` ("+N more" opens the rest). */
export function ChipItems({ items, limit = 20 }: { items: unknown[]; limit?: number }) {
  const shown = items.slice(0, limit);
  return (
    <span className="flex flex-wrap gap-1">
      {shown.map((x, i) => (
        <span key={i} className="mono rounded border border-line bg-surface-2 px-1 py-px text-[11px] text-tx2">{clip(itemText(x), 40)}</span>
      ))}
      {items.length > limit && <span className="text-[11px] text-tx3" title={items.slice(limit).map(itemText).join(", ")}>+{items.length - limit} more</span>}
    </span>
  );
}

/** Key/value grid: scalars as text, lists as chips, nested objects as an indented grid (one level; deeper is "N fields"). */
export function KVGrid({ value, depth = 0 }: { value: Record<string, unknown> | null | undefined; depth?: number }) {
  const entries = Object.entries(value ?? {}).filter(present);
  if (entries.length === 0) return null;
  return (
    <dl className="grid grid-cols-[7rem_1fr] gap-x-2 gap-y-0.5 text-xs" data-kvgrid>
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="mono truncate text-tx3" title={k}>{k}</dt>
          <dd className="min-w-0 break-words text-tx2">
            {Array.isArray(v) ? (
              <ChipItems items={v} />
            ) : isObj(v) ? (
              depth === 0 ? <KVGrid value={v} depth={1} /> : `${Object.keys(v).length} fields`
            ) : (
              <Mono className="break-all">{typeof v === "string" && /^h:\S+$/.test(v) ? "list" : String(v)}</Mono>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** The raw value, for people who want it: always behind a labelled trigger, never in the first view. */
export function RawJson({ value }: { value: unknown }) {
  return (
    <Disclosure summary="JSON" className="mt-1">
      <pre className="mono max-h-60 overflow-auto rounded-md border border-line bg-bg p-2 text-[11px] text-tx2">{JSON.stringify(value, null, 2)}</pre>
    </Disclosure>
  );
}
