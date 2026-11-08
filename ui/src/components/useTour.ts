import { useEffect, useRef } from "react";
import { hintFor, showRunFailure, showRunHint, startOrientation, startRunPhase, stopTour, tourActive, type TourDetail } from "../lib/tour";
import { getTour, setTour, useTourState } from "../lib/tourStore";

/**
 * Mounted once in App. Decides when each tutorial phase starts:
 *  1. orientation: first visit, nothing selected, feed loaded;
 *  2. a quiet hint on "Run this event" once per selected event (not after three dismissals);
 *  3. the run tour, when a single-event run or a judge event is started (the `ct-tour` run-started signal).
 */
export function useTour({ tower, selectedId, feedReady, runState, arrivedCount }: { tower: boolean; selectedId: string | null; feedReady: boolean; runState: string | null | undefined; arrivedCount: number }) {
  const t = useTourState();
  const shown = useRef(new Set<string>());

  // leaving the tower page ends whatever is showing
  useEffect(() => {
    if (!tower && tourActive()) stopTour();
  }, [tower]);

  // phase 1
  useEffect(() => {
    if (!tower || !feedReady || !t.enabled || t.orientation !== "pending" || selectedId || tourActive()) return;
    const h = window.setTimeout(() => {
      if (!tourActive() && getTour().enabled && getTour().orientation === "pending" && !selectedId) startOrientation();
    }, 700);
    return () => window.clearTimeout(h);
  }, [tower, feedReady, t.enabled, t.orientation, selectedId]);

  // phase 2
  useEffect(() => {
    // nothing to select yet (the feed is quiet): the hint points at Run feed; otherwise at Run this event
    const key = selectedId ?? (arrivedCount === 0 ? "feed" : null);
    if (tourActive() === "hint" && hintFor() !== key) stopTour();
    const quiet = !tower || !key || !t.enabled || t.run !== "pending" || t.orientation !== "done" || t.dismissals >= 3;
    if (quiet) {
      if (tourActive() === "hint") stopTour();
      return;
    }
    if (shown.current.has(key) || tourActive()) return;
    const h = window.setTimeout(() => {
      if (tourActive()) return;
      shown.current.add(key);
      showRunHint(key, () => setTour({ dismissals: getTour().dismissals + 1 }), key === "feed" ? "feed" : "event");
    }, 700);
    return () => window.clearTimeout(h);
  }, [tower, selectedId, arrivedCount, t.enabled, t.run, t.orientation, t.dismissals]);

  // phase 3
  useEffect(() => {
    const on = (e: Event) => {
      const d = (e as CustomEvent<TourDetail>).detail;
      if (d.type !== "run-started") return;
      const st = getTour();
      if (!st.enabled || st.run !== "pending" || tourActive() === "orientation" || tourActive() === "run") return;
      startRunPhase(d.id ?? null);
    };
    window.addEventListener("ct-tour", on);
    return () => window.removeEventListener("ct-tour", on);
  }, []);

  // the run died: say where to look, do not mark the tutorial done
  useEffect(() => {
    if (tourActive() === "run" && (runState === "aborted" || runState === "failed")) showRunFailure();
  }, [runState]);
}
