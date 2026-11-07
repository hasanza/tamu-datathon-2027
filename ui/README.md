# Control Tower UI

Vite + React 18 + TypeScript + Tailwind CSS v4 + TanStack Query + Cytoscape.js. Tokens come from `docs/BRAND.md`
(dark default, light via the top-bar toggle).

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api -> http://localhost:8001 (SSE unbuffered)
npm run typecheck  # tsc --noEmit
npm run build      # typecheck + production bundle in dist/
```

API (from the repo root): `uv run uvicorn api.app:app --port 8001`
(use `TRACES_DIR=traces/snapshot` to browse the snapshot run; `RUN_DIR` points at `action_log.jsonl` / `events.ndjson`).

## Layout

| Area | Where |
|---|---|
| Top bar, KPI strip, Run feed | `src/components/TopBar.tsx` |
| Event feed (filters, j/k, arrows) | `src/components/EventFeed.tsx` |
| Escalation inbox, Activity log (SSE) | `src/components/RightRail.tsx` |
| Event tabs: Summary, Agents, Graph, Actions, Audit | `src/views/*Tab.tsx`, `EventDetail.tsx` |
| Ontology, About pages | `src/views/OntologyPage.tsx`, `AboutPage.tsx` |
| Typed API client, hooks, SSE | `src/api/` |
| Cytoscape wrapper, deterministic layered layout | `src/components/CytoGraph.tsx`, `src/lib/layout.ts` |

Routing is hash based: `#/` , `#/E-03`, `#/ontology`, `#/about`.

## Notes and deviations

- `POST /api/run` returning 501 shows the toast "Pipeline runner not wired yet".
- `--text-3` is `#8a8a8a` in dark mode (BRAND says `#747474`) and `#6b6b6b` in light, to keep body-size muted text above 4.5:1.
- `compound` events use a teal `--cat-compound` (`#14b8a6`); BRAND.md has no color for them. `Day` nodes use `#4d6a8a`.
- Collapsed `grp:` nodes are drawn as dashed `+N ...` badges. The trace stores only their count, so they cannot be expanded
  into members; the node panel says so.
- Acknowledging an escalation and the theme are stored in `localStorage` only (UI-only, per browser).
- In dev, the Cytoscape instance is exposed as `window.__cy` for debugging and UI tests.
