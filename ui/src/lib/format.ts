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
