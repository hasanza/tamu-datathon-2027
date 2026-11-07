import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, Info, XCircle } from "lucide-react";
import { safeStorage } from "./lib/format";

/* ---------- theme ---------- */
type Theme = "dark" | "light";
const ThemeCtx = createContext<{ theme: Theme; toggle: () => void }>({ theme: "dark", toggle: () => {} });
export const useTheme = () => useContext(ThemeCtx);

/* ---------- toasts ---------- */
type ToastKind = "info" | "ok" | "error";
interface Toast {
  id: number;
  kind: ToastKind;
  text: string;
}
const ToastCtx = createContext<(text: string, kind?: ToastKind) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function AppProviders({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === "light" ? "light" : "dark"));
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    safeStorage("ct-theme", theme);
  }, [theme]);
  const themeValue = useMemo(() => ({ theme, toggle: () => setTheme((t) => (t === "dark" ? "light" : "dark")) }), [theme]);

  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, kind: ToastKind = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, kind, text }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 5000);
  }, []);

  return (
    <ThemeCtx.Provider value={themeValue}>
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
              {t.text}
            </div>
          ))}
        </div>
      </ToastCtx.Provider>
    </ThemeCtx.Provider>
  );
}
