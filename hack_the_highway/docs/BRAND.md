# BRAND — UI theme tokens (Hitachi-inspired palette)

Source: colors and fonts extracted from the stylesheet of hitachids.com (theme `unoProject/style.css`) on 2026-11-07.
Hitachi Sans is proprietary; we use **Noto Sans** (which the site itself loads as fallback) and **JetBrains Mono** for ids/dates.

> The hackathon is Hitachi-sponsored (confirmed 2026-11-07), so the Hitachi logo and "powered by Hitachi Digital Services"
> wording are allowed in the UI chrome and the design card. Keep the product name **Wacky Wheels Control Tower** as the
> headline; place the Hitachi mark small, top-right, with clear space. Check the event rules for any logo-usage clause.

## Core tokens (CSS variables, Tailwind `theme.extend.colors`)

| Token | Dark (default) | Light | Use |
|---|---|---|---|
| `--brand` | `#b30000` | `#b30000` | primary accent: top-bar rule, active tab, primary button, selected feed item |
| `--brand-bright` | `#e31b23` | `#e31b23` | hover/focus on brand elements, live "processing" pulse |
| `--bg` | `#0a0a0b` | `#ffffff` | page background |
| `--surface` | `#141416` | `#f7f7f7` | cards, panels |
| `--surface-2` | `#1c1c1f` | `#f4f4f4` | nested panels, table header |
| `--border` | `#2a2a2e` | `#c9cac8` | hairlines |
| `--text` | `#ffffff` | `#000000` | primary text |
| `--text-2` | `#c9cac8` | `#4d4d4d` | secondary text |
| `--text-3` | `#747474` | `#747474` | muted labels, timestamps |

## Semantic / category colors (kept distinct from brand red so red keeps meaning)

| Token | Hex | Use |
|---|---|---|
| `--cat-delay` | `#e6a100` | Supplier delay |
| `--cat-outage` | `#ff5a36` | Plant outage |
| `--cat-quality` | `#8b5cf6` | Quality hold |
| `--cat-noise` | `#747474` | Noise |
| `--cat-unconfirmed` | `#3b82f6` | Unconfirmed → escalated |
| `--ok` | `#2fa66a` | rehearsal passed, call ok |
| `--warn` | `#e6a100` | low confidence |
| `--fail` | `#e31b23` | failed call (should never appear) |

Graph node colors by type: Plant `#ff5a36`, Supplier `#3b82f6`, Part `#8b5cf6`, Model `#c9cac8`, Shipment `#e6a100`,
Lot `#8b5cf6`, ProductionOrder `#ffffff` (dark) / `#000` (light), CustomerOrder `#2fa66a`, Dealer `#b30000`, Customer `#e6a100`, Vehicle `#747474`.
Highlighted path edges: `--brand-bright`, 2px; non-path edges at 30% opacity.

## Typography
- UI: `"Noto Sans", system-ui, sans-serif`; weights 400/500/700. Headlines 600, tight tracking.
- Data: `"JetBrains Mono", ui-monospace` for ids (PO-0253), dates, VINs.
- Sizes: 12 / 13 (tables) / 14 (body) / 18 (panel titles) / 28 (KPI numbers).

## Layout language
Dense, operational, calm. Thin brand-red rule under the top bar, 1px borders, 8px radius, no gradients, no shadows except the
detail drawer. Motion only where it carries meaning: new event slides in, processing pulse, path highlight on hover.
