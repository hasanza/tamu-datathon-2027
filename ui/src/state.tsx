import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, Info, XCircle } from "lucide-react";
import { safeStorage } from "./lib/format";

/* ---------- theme ---------- */
type Theme = "dark" | "light";
const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({ theme: "dark", toggle: () => {} });
export const useTheme = () => useContext(ThemeCtx);

/* ---------- run order (Sequential | Parallel). Feed events always go to the scored server: there is no mode to pick. ---------- */
export type RunOrder = "sequential" | "parallel";
/** Events are independent worlds, so a run can handle them one by one (default, used for the final run) or side by side. */
export const PARALLEL_WORKERS = 4;
const RunModeCtx = createContext<{ order: RunOrder; setOrder: (o: RunOrder) => void }>({ order: "sequential", setOrder: () => {} });
export const useRunMode = () => useContext(RunModeCtx);

/* ---------- toasts ---------- */
type ToastKind = "info" | "ok" | "error";
export interface ToastAction {
  label: string;
  onClick: () => void;
}
interface Toast {
  id: number;
  kind: ToastKind;
  text: string;
  action?: ToastAction;
}
const ToastCtx = createContext<(text: string, kind?: ToastKind, action?: ToastAction) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function AppProviders({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === "light" ? "light" : "dark"));
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    safeStorage("ct-theme", theme);
  }, [theme]);
  const themeValue = useMemo(() => ({ theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) }), [theme]);

  const [order, setOrderState] = useState<RunOrder>(() => (safeStorage("ct-run-order") === "parallel" ? "parallel" : "sequential"));
  const setOrder = useCallback((o: RunOrder) => {
    setOrderState(o);
    safeStorage("ct-run-order", o);
  }, []);
  const modeValue = useMemo(() => ({ order, setOrder }), [order, setOrder]);

  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: ToastKind = "info", action?: ToastAction) => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text, action }]);
    // a toast with an action stays a little longer: there is something to click
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), action ? 9000 : 5000);
  }, []);

  return (
    <ThemeCtx.Provider value={themeValue}>
      <RunModeCtx.Provider value={modeValue}>
      <ToastCtx.Provider value={push}>
        {children}
        <div aria-live="polite" className="pointer-events-none fixed bottom-10 right-4 z-50 flex flex-col gap-2">
          {toasts.map((t) => (
            <div
              key={t.id}
              role="status"
              className="anim-slide-in pointer-events-auto flex max-w-sm items-start gap-2 rounded-lg border border-line bg-surface-2 px-3 py-2 text-[13px] text-tx shadow-lg"
            >
              {t.kind === "ok" ? (
                <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-ok" aria-hidden />
              ) : t.kind === "error" ? (
                <XCircle size={16} className="mt-0.5 shrink-0 text-fail" aria-hidden />
              ) : (
                <Info size={16} className="mt-0.5 shrink-0 text-tx2" aria-hidden />
              )}
              <span className="min-w-0">{t.text}</span>
              {t.action && (
                <button
                  onClick={() => {
                    t.action?.onClick();
                    setToasts((all) => all.filter((x) => x.id !== t.id));
                  }}
                  className="ml-1 shrink-0 rounded font-medium text-brand-bright underline-offset-2 hover:underline focus-visible:outline-2"
                >
                  {t.action.label}
                </button>
              )}
            </div>
          ))}
        </div>
      </ToastCtx.Provider>
      </RunModeCtx.Provider>
    </ThemeCtx.Provider>
  );
}
