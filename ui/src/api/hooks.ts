import { useQueries, useQuery } from "@tanstack/react-query";
import { api, ApiError } from "./client";
import type { Trace } from "./types";

const noRetry404 = (count: number, err: unknown) => !(err instanceof ApiError && err.status === 404) && count < 2;

export const useEvents = () => useQuery({ queryKey: ["events"], queryFn: api.events, refetchInterval: 15000 });
export const useKpis = () => useQuery({ queryKey: ["kpis"], queryFn: api.kpis, refetchInterval: 15000 });

/** A 404 means "no trace yet" (queued); callers treat `isError && error.status === 404` as queued. */
export const useTrace = (id: string | null) =>
  useQuery({
    queryKey: ["trace", id],
    queryFn: () => api.trace(id as string),
    enabled: !!id,
    retry: noRetry404,
  });

export const useLog = (id: string | null) =>
  useQuery({ queryKey: ["actions", id], queryFn: () => api.actions(id as string), enabled: !!id });

export const useGraph = (id: string | null, enabled: boolean) =>
  useQuery({
    queryKey: ["graph", id],
    queryFn: () => api.graph(id as string),
    enabled: !!id && enabled,
    retry: noRetry404,
  });

/** Traces for a set of event ids (used by the escalation inbox). Missing traces are simply absent. */
export function useTraces(ids: string[]): Trace[] {
  const results = useQueries({
    queries: ids.map((id) => ({
      queryKey: ["trace", id],
      queryFn: () => api.trace(id),
      retry: noRetry404,
    })),
  });
  return results.flatMap((r) => (r.data ? [r.data] : []));
}

export const isNotFound = (err: unknown) => err instanceof ApiError && err.status === 404;
