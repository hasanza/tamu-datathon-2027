export const pct = (x: number) => `${Math.round(x * 100)}%`;

export function usd(x: number): string {
  if (x === 0) return "$0";
  return x < 0.01 ? `$${x.toFixed(4)}` : `$${x.toFixed(2)}`;
}

export function clock(iso: string): string {
  const d = iso.split("T")[1] ?? iso;
  return d.slice(0, 12);
}

export function dateTime(iso: string): string {
  const [d, t] = iso.split("T");
  return `${d} ${(t ?? "").slice(0, 5)}`;
}

export function durationMs(a: string, b: string | null): string {
  if (!b) return "-";
  const ms = new Date(b).getTime() - new Date(a).getTime();
  if (!Number.isFinite(ms)) return "-";
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(2)} s`;
}

export function offsetMs(from: string, to: string): string {
  const ms = new Date(to).getTime() - new Date(from).getTime();
  return Number.isFinite(ms) ? `+${ms} ms` : "";
}

/** `{plant_id: "P_AL", date: "2027-03-08"}` -> `plant_id=P_AL date=2027-03-08` */
export function compactArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`)
    .join(" ");
}

export const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

export function safeStorage(key: string, value?: string): string | null {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
    return value;
  } catch {
    return null;
  }
}

const HINT_KEYS = ["category", "kind", "type", "tool", "name"];
/** `incidents` -> `incident`, `po_ids` -> `po_id` (only for a count of exactly one). */
const singular = (k: string) => (k.endsWith("s") && k.length > 2 ? k.slice(0, -1) : k);

function part(k: string, v: unknown): string {
  if (Array.isArray(v)) {
    // a list of objects: name what kind of things they are (e.g. the categories of the incidents)
    const hintKey = HINT_KEYS.find((h) => v.some((x) => x && typeof x === "object" && typeof (x as Record<string, unknown>)[h] === "string"));
    const kinds = hintKey ? [...new Set(v.map((x) => (x as Record<string, unknown>)?.[hintKey]).filter((x): x is string => typeof x === "string"))].slice(0, 2) : [];
    return `${v.length} ${v.length === 1 ? singular(k) : k}${kinds.length ? ` (${kinds.join(", ")})` : ""}`;
  }
  if (typeof v === "string") return /^h:\S+$/.test(v) ? `${k}: list` : `${k}=${clip(v, 24)}`; // "h:..." is an opaque handle for a long list
  if (v && typeof v === "object") return `${k}: ${Object.keys(v).length} fields`;
  return `${k}=${String(v)}`;
}

/**
 * One short line for a tool call's arguments or result: counts for lists, a few scalars, never nested JSON.
 * `{incidents: [{category: "plant_outage", ...}]}` -> `1 incident (plant_outage)`. The full value stays under "details".
 */
export function summarize(value: Record<string, unknown>, max = 3): string {
  // counts and lists say more than identifiers do (`affected_count=9` over `plant_id=P_MS`): show those first
  const weight = (v: unknown) => (typeof v === "number" || Array.isArray(v) ? 0 : 1);
  const parts = Object.entries(value)
    .filter(([, v]) => v !== null && v !== undefined && v !== "" && v !== false)
    .map(([k, v], i) => ({ i, w: weight(v), text: part(k, v) }))
    .sort((a, b) => a.w - b.w || a.i - b.i)
    .map((x) => x.text);
  return parts.slice(0, max).join(" · ") + (parts.length > max ? ` · +${parts.length - max} more` : "");
}
