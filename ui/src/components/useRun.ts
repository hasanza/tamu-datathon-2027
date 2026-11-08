import { useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { PARALLEL_WORKERS, useRunMode, useToast } from "../state";

/** Everything that depends on which run is on screen. Removed (not just invalidated) so a trace from the
 *  previous run can never be shown while the new run has not produced one yet. */
export function dropRunData(qc: QueryClient) {
  for (const key of ["trace", "graph", "actions"]) qc.removeQueries({ queryKey: [key] });
  void qc.invalidateQueries({ queryKey: ["events"] });
  void qc.invalidateQueries({ queryKey: ["kpis"] });
  void qc.invalidateQueries({ queryKey: ["runstatus"] });
}

/** POST /api/run. Feed events always go to the scored organizers' server (the API default); only Sequential | Parallel is chosen here. */
export function useRun() {
  const toast = useToast();
  const qc = useQueryClient();
  const { order } = useRunMode();
  return useMutation({
    // one event has nothing to run beside, so Parallel only applies to the whole feed
    mutationFn: (opts: { eventId?: string; all?: boolean }) => api.run({ ...opts, parallel: opts.all && order === "parallel" ? PARALLEL_WORKERS : undefined }),
    onSuccess: (_d, v) => {
      const where = v.all ? ` (${order})` : "";
      toast(v.all ? `Run started for the whole feed${where}` : `Run started for ${v.eventId}`, "ok");
      dropRunData(qc);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) toast("A run is already in progress", "info");
      else toast(e instanceof Error ? `Run failed: ${e.message}` : "Run failed", "error");
    },
  });
}

/** localStorage keys that "Reset everything" clears. `ct-tour` (the tutorial) is deliberately not one of them. */
export const RESET_KEYS = ["ct-acked", "ct-feed-filters", "ct-summary-impact"];

/** POST /api/reset?scope=all: delete the judge events and the live run from disk, and clear this browser's session state. */
export function useResetAll() {
  const toast = useToast();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.resetAll(),
    onSuccess: () => {
      for (const k of RESET_KEYS) {
        try {
          localStorage.removeItem(k);
        } catch {
          /* storage blocked: nothing to clear */
        }
      }
      window.dispatchEvent(new Event("ct-feed-reset")); // feed filters
      window.dispatchEvent(new Event("ct-reset-all")); // acknowledgements, Activity, selection
      window.location.hash = "/";
      toast("Reset: judge events, the live run and this session's state are gone", "ok");
      dropRunData(qc);
      void qc.invalidateQueries();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) toast("Wait for the running pipeline to finish, or cancel it first", "info");
      else toast(e instanceof Error ? `Reset failed: ${e.message}` : "Reset failed", "error");
    },
  });
}

/** POST /api/run/cancel: stop the live run (and the enterprise server it started). */
export function useCancelRun() {
  const toast = useToast();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.cancelRun(),
    onSuccess: () => {
      toast("Run cancelled", "info");
      dropRunData(qc);
    },
    onError: (e) => toast(e instanceof Error ? `Could not cancel: ${e.message}` : "Could not cancel", "error"),
  });
}

/** POST /api/reset: back to the committed 15-event snapshot. */
export function useReset() {
  const toast = useToast();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.reset(),
    onSuccess: () => {
      toast("Back to the snapshot of all 15 events", "ok");
      dropRunData(qc);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) toast("Wait for the running pipeline to finish", "info");
      else toast(e instanceof Error ? `Reset failed: ${e.message}` : "Reset failed", "error");
    },
  });
}
