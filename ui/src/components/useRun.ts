import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import { useToast } from "../state";

/** POST /api/run. A 501 (runner not wired yet) is reported as an informational toast, not an error. */
export function useRun() {
  const toast = useToast();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (opts: { eventId?: string; all?: boolean }) => api.run(opts),
    onSuccess: (_d, v) => {
      toast(v.all ? "Run started for the whole feed" : `Run started for ${v.eventId}`, "ok");
      void qc.invalidateQueries();
    },
    onError: (e) => {
      if (e instanceof ApiError && e.status === 501) toast("Pipeline runner not wired yet", "info");
      else toast(e instanceof Error ? `Run failed: ${e.message}` : "Run failed", "error");
    },
  });
}
