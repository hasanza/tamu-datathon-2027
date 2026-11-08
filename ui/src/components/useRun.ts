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

/** POST /api/run in the mode picked in the top bar (Dry = in-process twin, Server = fresh organizers' server). */
export function useRun() {
  const toast = useToast();
  const qc = useQueryClient();
  const { mode, order } = useRunMode();
  return useMutation({
    // one event has nothing to run beside, so Parallel only applies to the whole feed
    mutationFn: (opts: { eventId?: string; all?: boolean }) => api.run({ ...opts, mode, parallel: opts.all && order === "parallel" ? PARALLEL_WORKERS : undefined }),
    onSuccess: (_d, v) => {
      const where = `${mode === "dry" ? "twin" : "fresh server"}${v.all ? `, ${order}` : ""}`;
      toast(v.all ? `Run started for the whole feed (${where})` : `Run started for ${v.eventId} (${where})`, "ok");
      dropRunData(qc);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 409) toast("A run is already in progress", "info");
      else toast(e instanceof Error ? `Run failed: ${e.message}` : "Run failed", "error");
    },
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
