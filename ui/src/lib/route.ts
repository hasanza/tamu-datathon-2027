import { useCallback, useEffect, useState } from "react";

export type Page = "tower" | "ontology" | "about";
export interface Route {
  page: Page;
  eventId: string | null;
}

function parse(): Route {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (h === "ontology" || h === "about") return { page: h, eventId: null };
  return { page: "tower", eventId: /^[EC]-\d{2}$/.test(h) ? h : null };
}

/** Tiny hash router: #/ (tower), #/E-03 or #/C-01 (tower with an event selected; C- = sandbox custom event), #/ontology, #/about. */
export function useRoute() {
  const [route, setRoute] = useState<Route>(parse);
  useEffect(() => {
    const on = () => setRoute(parse());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  const go = useCallback((to: Page | string) => {
    window.location.hash = to === "tower" ? "/" : `/${to}`;
  }, []);
  return { route, go };
}
