import { useEffect, useState } from "react";

/** The current time, refreshed every `ms`, so relative times ("3 min ago") keep moving. */
export function useNow(ms = 30000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(t);
  }, [ms]);
  return now;
}
