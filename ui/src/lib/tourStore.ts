import { useSyncExternalStore } from "react";
import { safeStorage } from "./format";

/** Tutorial progress, kept in `ct-tour`. "Reset everything" never touches this key. */
export interface TourState {
  orientation: "done" | "pending";
  run: "done" | "pending";
  enabled: boolean;
  /** how many times the "Run this event" hint was dismissed (quiet after three, until the toggle is turned on again) */
  dismissals: number;
}

const KEY = "ct-tour";
const FRESH: TourState = { orientation: "pending", run: "pending", enabled: true, dismissals: 0 };

function read(): TourState {
  try {
    const raw = JSON.parse(safeStorage(KEY) ?? "null") as Partial<TourState> | null;
    if (!raw || typeof raw !== "object") return { ...FRESH };
    return {
      orientation: raw.orientation === "done" ? "done" : "pending",
      run: raw.run === "done" ? "done" : "pending",
      enabled: typeof raw.enabled === "boolean" ? raw.enabled : true,
      dismissals: typeof raw.dismissals === "number" ? raw.dismissals : 0,
    };
  } catch {
    return { ...FRESH };
  }
}

let state = read();
const listeners = new Set<() => void>();

export const getTour = () => state;
export function setTour(patch: Partial<TourState>) {
  state = { ...state, ...patch };
  safeStorage(KEY, JSON.stringify(state));
  listeners.forEach((l) => l());
}
export const freshTour = (): TourState => ({ ...FRESH });
const subscribe = (l: () => void) => {
  listeners.add(l);
  return () => listeners.delete(l);
};
export const useTourState = () => useSyncExternalStore(subscribe, getTour);
