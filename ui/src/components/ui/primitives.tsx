import type { ReactNode } from "react";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import type { EventCategory, Status } from "../../api/types";
import { CATEGORY_META, STATUS_META } from "../../lib/meta";

const tint = (color: string) => ({
  color,
  background: `color-mix(in srgb, ${color} 14%, transparent)`,
  borderColor: `color-mix(in srgb, ${color} 45%, transparent)`,
});

export function Chip({ color, children, title, className = "" }: { color: string; children: ReactNode; title?: string; className?: string }) {
  return (
    <span
      title={title}
      style={tint(color)}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md border px-1.5 py-0.5 text-[11px] font-medium leading-4 ${className}`}
    >
      {children}
    </span>
  );
}

export function CategoryBadge({ category }: { category: EventCategory | null }) {
  if (!category) return <Chip color="var(--text-3)">Pending</Chip>;
  const m = CATEGORY_META[category];
  return <Chip color={m.color}>{m.label}</Chip>;
}

export function StatusChip({ status }: { status: Status }) {
  const m = STATUS_META[status];
  return (
    <Chip color={m.color}>
      {status === "processing" && <span className="anim-pulse inline-block h-1.5 w-1.5 rounded-full bg-brand-bright" />}
      {m.label}
    </Chip>
  );
}

export function OkChip({ ok, label }: { ok: boolean | null | undefined; label: string }) {
  if (ok == null) return <Chip color="var(--text-3)">{label}: n/a</Chip>;
  return (
    <Chip color={ok ? "var(--ok)" : "var(--fail)"}>
      {label} {ok ? "ok" : "failed"}
    </Chip>
  );
}

/** Small SVG ring showing a 0..1 confidence. Warn color below 0.7 (the act gate). */
export function ConfidenceRing({ value, size = 28 }: { value: number | null; size?: number }) {
  const r = (size - 4) / 2;
  const c = 2 * Math.PI * r;
  const v = value ?? 0;
  const color = value == null ? "var(--text-3)" : v >= 0.7 ? "var(--ok)" : "var(--warn)";
  return (
    <svg
      width={size}
      height={size}
      role="img"
      aria-label={value == null ? "confidence not available" : `confidence ${Math.round(v * 100)} percent`}
      className="shrink-0"
    >
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--border)" strokeWidth={3} />
      {value != null && (
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={3}
          strokeDasharray={`${c * v} ${c}`}
          strokeLinecap="round"
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      )}
      <text x="50%" y="50%" dy="0.35em" textAnchor="middle" fontSize={size * 0.32} fill="var(--text-2)" className="mono">
        {value == null ? "-" : Math.round(v * 100)}
      </text>
    </svg>
  );
}

/** `fill`: at xl the panel takes the height its parent gives it; the header stays pinned and only the body scrolls. */
export function Panel({ title, action, children, className = "", fill = false, attrs }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; fill?: boolean; attrs?: Record<string, string> }) {
  return (
    <section {...attrs} className={`rounded-lg border border-line bg-surface ${fill ? "flex flex-col xl:min-h-0" : ""} ${className}`}>
      {(title || action) && (
        <header className="@container flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
          <h3 className="min-w-0 text-[13px] font-semibold tracking-tight text-tx">{title}</h3>
          {action}
        </header>
      )}
      <div className={`p-3 ${fill ? "scroll-shadow-y xl:min-h-0 xl:flex-1 xl:overflow-y-auto" : ""}`}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, sub, color }: { label: string; value: ReactNode; sub?: ReactNode; color?: string }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-tx3">{label}</div>
      <div className={`mono text-[28px] font-medium leading-9 ${color ? "" : value === 0 || value === "0" ? "text-tx3" : "text-tx"}`} style={color ? { color } : undefined}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-tx3">{sub}</div>}
    </div>
  );
}

export function Empty({ title, hint, icon }: { title: string; hint?: string; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1.5 px-4 py-10 text-center text-tx3">
      {icon ?? <Inbox size={22} aria-hidden />}
      <div className="text-[13px] font-medium text-tx2">{title}</div>
      {hint && <div className="max-w-sm text-xs">{hint}</div>}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 px-4 py-10 text-xs text-tx3">
      <Loader2 size={16} className="animate-spin" aria-hidden /> {label}…
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="m-3 flex items-start gap-2 rounded-lg border border-fail/50 bg-fail/10 p-3 text-xs text-tx2">
      <AlertTriangle size={16} className="mt-0.5 shrink-0 text-fail" aria-hidden />
      <div className="flex-1">
        <div className="font-medium text-tx">Could not load</div>
        <div className="mono break-words">{message}</div>
      </div>
      {onRetry && (
        <button onClick={onRetry} className="rounded-md border border-line px-2 py-1 text-tx hover:border-brand-bright">
          Retry
        </button>
      )}
    </div>
  );
}

export const Mono = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <span className={`mono text-[12px] ${className}`}>{children}</span>
);
