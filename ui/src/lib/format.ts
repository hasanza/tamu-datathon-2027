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

const EFFORT_KEYS = new Set(["turns", "llm_calls", "cost", "cost_usd", "model", "attempts", "tokens", "input_tokens", "output_tokens"]);
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
    .filter(([k]) => !EFFORT_KEYS.has(k)) // turns, LLM calls and cost live in the Audit tab and the Run menu, not in the narrative
    .filter(([, v]) => v !== null && v !== undefined && v !== "" && v !== false)
    .map(([k, v], i) => ({ i, w: weight(v), text: part(k, v) }))
    .sort((a, b) => a.w - b.w || a.i - b.i)
    .map((x) => x.text);
  return parts.slice(0, max).join(" · ") + (parts.length > max ? ` · +${parts.length - max} more` : "");
}

const unquote = (v: string) => v.trim().replace(/^(['"])(.*)\1$/s, "$2");

/**
 * Traces written before the pipeline text fix embed Python dicts and JSON in sentences
 * ("Resolved incident: {'category': 'noise', 'confidence': 0.99}"). Rewrite those into plain words:
 * `{'k': 'v', 'n': 3}` -> `k v - n 3`, `['a', 'b']` -> `a, b`. Text without braces passes through untouched.
 */
export function prettifyRepr(text: string): string {
  let out = text;
  for (let i = 0; i < 6 && /\{[^{}]*\}/.test(out); i++) {
    out = out.replace(/\{([^{}]*)\}/g, (_m, body: string) => {
      const pairs = [...body.matchAll(/['"]?([A-Za-z_][\w ]*)['"]?\s*:\s*('[^']*'|"[^"]*"|\[[^\]]*\]|[^,]+)/g)];
      if (pairs.length === 0) return "";
      return pairs
        .map(([, k, v]) => {
          const val = unquote(v ?? "").replace(/^\[|\]$/g, "").replace(/['"]/g, "");
          return val === "None" || val === "null" || val === "" ? null : `${(k ?? "").trim()} ${val}`;
        })
        .filter(Boolean)
        .join(" - ");
    });
  }
  // a dict cut off by truncation never closes ("{'error': {'code': 429, 'message': 'You exceeded"): drop its braces and key quotes
  while (/\{\s*['"]?\w+['"]?\s*:/.test(out)) out = out.replace(/\{\s*['"]?(\w+)['"]?\s*:\s*/, "$1 ");
  out = out.replace(/['"](\w+)['"]\s*:\s*/g, "$1 ").replace(/\s*[}]+/g, "");
  return out.replace(/\[((?:'[^']*'|"[^"]*")(?:\s*,\s*(?:'[^']*'|"[^"]*"))*)\]/g, (_m, items: string) => items.replace(/['"]/g, ""));
}

/**
 * "just now", "12 s ago", "3 min ago", "2 h ago", "yesterday", "5 d ago". `at` is an ISO string or epoch ms.
 * Returns null when the time is unusable or in the future (the 2027 feed timestamps): the caller then shows the absolute time.
 */
export function timeAgo(at: string | number, now = Date.now()): string | null {
  const t = typeof at === "number" ? at : Date.parse(at);
  if (!Number.isFinite(t)) return null;
  const s = Math.round((now - t) / 1000);
  if (s < -60) return null;
  if (s < 10) return "just now";
  if (s < 60) return `${s} s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  return d === 1 ? "yesterday" : `${d} d ago`;
}
