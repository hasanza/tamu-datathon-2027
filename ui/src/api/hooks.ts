import { useQueries, useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./client";
import type { RunMode, Trace } from "./types";

const noRetry404 = (count: number, err: unknown) => !(err instanceof ApiError && err.status === 404) && count < 2;

export const useEvents = () => useQuery({ queryKey: ["events"], queryFn: api.events, refetchInterval: 15000 });
export const useKpis = () => useQuery({ queryKey: ["kpis"], queryFn: api.kpis, refetchInterval: 15000 });

/** A 404 means "no trace yet" (queued); callers treat `isError && error.status === 404` as queued. */
export const isNotFound = (err: unknown) => err instanceof ApiError && err.status === 404;

/** React Query keeps the last good `data` when a refetch fails; a 404 must read as absent, never as a stale trace. */
function dropStaleOn404<T extends { data: unknown; error: unknown; isError: boolean }>(q: T): T {
  return q.isError && isNotFound(q.error) ? { ...q, data: undefined } : q;
}

export const useTrace = (id: string | null) =>
  dropStaleOn404(
    useQuery({
      queryKey: ["trace", id],
      queryFn: () => api.trace(id as string),
      enabled: !!id,
      retry: noRetry404,
    }),
  );

export const useLog = (id: string | null) =>
  useQuery({ queryKey: ["actions", id], queryFn: () => api.actions(id as string), enabled: !!id });

export const useGraph = (id: string | null, enabled: boolean) =>
  dropStaleOn404(
    useQuery({
      queryKey: ["graph", id],
      queryFn: () => api.graph(id as string),
      enabled: !!id && enabled,
      retry: noRetry404,
    }),
  );

/** Run state from the API. Polled quickly while a run is going so the UI reconciles even if SSE misses a line. */
export const useRunStatus = () =>
  useQuery({
    queryKey: ["runstatus"],
    queryFn: api.runStatus,
    refetchInterval: (q) => (q.state.data?.running ? 1500 : 15000),
  });

/** Where the numbers on screen came from: the committed snapshot was produced against the real server,
 *  a run started from this UI in dry mode ran against the in-process twin. */
export function useExecTarget(): "twin" | "server" {
  const mode: RunMode | null | undefined = useRunStatus().data?.mode;
  return mode === "dry" ? "twin" : "server";
}

/** Traces for a set of event ids (used by the escalation inbox). Missing (404) traces are simply absent. */
export function useTraces(ids: string[]): { traces: Trace[]; loading: boolean; failed: boolean } {
  const results = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["trace", id],
      queryFn: () => api.trace(id),
      retry: noRetry404,
    })),
  });
  return {
    traces: results.flatMap((r) => (r.data && !(r.isError && isNotFound(r.error)) ? [r.data] : [])),
    loading: results.some((r) => r.isLoading),
    failed: results.some((r) => r.isError && !isNotFound(r.error)),
  };
}
