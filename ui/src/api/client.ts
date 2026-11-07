import type { FeedEvent, GraphPath, Kpis, LogRow, RunMode, RunStatus, Trace } from "./types";

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
  run: (opts: { eventId?: string; all?: boolean; mode: RunMode }) =>
    request<RunStatus>(
      `/api/run?${opts.all ? "all=true" : `event_id=${encodeURIComponent(opts.eventId ?? "")}`}&mode=${opts.mode}`,
      { method: "POST" },
    ),
  runStatus: () => request<RunStatus>("/api/run/status"),
  reset: () => request<RunStatus>("/api/reset", { method: "POST" }),
};
