import type { FeedEvent, GraphPath, Kpis, LogRow, ResetPreview, RunMode, RunStatus, Trace } from "./types";

export interface CustomResult {
  event_id: string;
  status: string;
  category: string;
  parent_id?: string | null;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "API unreachable (is uvicorn running on :8001?)");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") detail = body.detail;
      else if (Array.isArray(body?.detail))
        detail = body.detail.map((d: { msg?: string }) => d.msg).filter(Boolean).join("; ") || detail; // FastAPI validation errors
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, detail);
  }
  return (await res.json()) as T;
}

export const api = {
  events: () => request<FeedEvent[]>("/api/events"),
  trace: (id: string) => request<Trace>(`/api/traces/${id}`),
  actions: (id?: string) => request<LogRow[]>(`/api/actions${id ? `?event_id=${id}` : ""}`),
  graph: (id: string) => request<GraphPath>(`/api/graph/${id}`),
  kpis: () => request<Kpis>("/api/kpis"),
  /** `parallel` = number of events handled side by side; omitted = sequential (the API default). */
  run: (opts: { eventId?: string; all?: boolean; mode?: RunMode; parallel?: number }) =>
    request<RunStatus>(
      `/api/run?${opts.all ? "all=true" : `event_id=${encodeURIComponent(opts.eventId ?? "")}`}${opts.mode ? `&mode=${opts.mode}` : ""}${opts.parallel ? `&parallel=${opts.parallel}` : ""}`,
      { method: "POST" },
    ),
  custom: (text: string, source?: string) =>
    request<CustomResult>("/api/custom", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(source ? { text, source } : { text }),
    }),
  /** Follow-up to an escalated event: the API appends the operator's details to the parent's text and re-runs it in the sandbox. */
  followUp: (parentId: string, details: string) =>
    request<CustomResult>("/api/custom", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent_id: parentId, details }),
    }),
  runStatus: () => request<RunStatus>("/api/run/status"),
  reset: () => request<RunStatus>("/api/reset", { method: "POST" }),
  resetAll: () => request<RunStatus>("/api/reset?scope=all", { method: "POST" }),
  resetPreview: () => request<ResetPreview>("/api/reset/preview"),
  cancelRun: () => request<RunStatus>("/api/run/cancel", { method: "POST" }),
};
