# Demo script (3 to 4 minutes)

Written for whoever records the video. Every number below is from the final run (`runs/final/`, tag `final-run-1`) and is on screen
in the UI. `media/screenshots/` holds one still per beat as a backup if the live demo misbehaves.

## Before you press record
1. `scripts/dev.sh` (API on :8001, UI on http://localhost:5173). The UI opens on the committed final run, all 15 events done.
2. Mode selector in the top bar on **Dry (twin)**. If "Back to snapshot" is visible, click it so the page shows 15/15.
3. Browser at 1440x900, dark theme, notifications off. Close the Activity panel's old lines with the bin icon.
4. Optional beat 9 needs a Gemini key on this machine (`.env`). Without it, skip that beat.

## Beats

| # | Time | On screen | Say | Still |
|---|---|---|---|---|
| 1 | 0:00 | Control tower, KPI strip | "Wacky Wheels gets 15 free-text operational events. One coordinator and three specialists read them, find what each one touches, plan exactly what the policy handbook prescribes, rehearse it on a digital twin, and only then act. 797 calls on the real server, none failed." | 01 |
| 2 | 0:25 | Click **Run feed** (Dry) and watch the feed fill | "Events arrive one by one. The right rail shows each agent step as it happens, not a summary afterwards." It takes about 15 s and the KPI strip counts up to 15/15; then click **Back to snapshot**. | 13, 14 |
| 3 | 0:55 | **E-01**, Summary | "One digest, two incidents: San Antonio is down, and a chip shipment to Princeton is late. The model split it; code did the rest. 122 customers touched, 41 dealers told once each." | 02 |
| 4 | 1:15 | Scroll to **Blast radius** | "This is what we prevented: how far each order slipped, and loaners. 30 customers were entitled, 26 got one, because the dealers' pools ran out. Platinum first, then Gold, then the earliest promise." | 03 |
| 5 | 1:40 | **E-11**, tab **Graph** | "Why these records? Plant to production orders to customer orders to dealers. Large sets collapse into counted groups; every action cites its path." | 04 |
| 6 | 2:00 | Tab **Agents** | "Four agents with one job each. You can see the rehearsal on the twin, the second model auditing the plan, and the execution." | 05 |
| 7 | 2:20 | **E-03**, tab **Actions**, then **Audit** | "A quality hold is 188 calls: one lot hold, 37 stop-sales, 150 owners contacted, all made by code, none by the LLM. Audit shows the policy checks and the LLM cost." | 06, 07 |
| 8 | 2:50 | **E-02**, then **E-05** | "Rumours are handed to a human with the exact question to ask, and change nothing. Noise does nothing, with the reason." | 08, 09 |
| 9 | 3:15 | **Try your own event** (needs key): click the *Plant outage* chip, Submit | "Anything a judge types goes through the full pipeline in a sandbox: rehearsed on the twin, never touching the real server." Show the Sandbox badge. | none |
| 10 | 3:40 | Footer / design card | "Two models, Gemini 3.5 Flash-Lite and Gemini 3.8 Flash as auditor, 40 calls, five cents for the whole run. The same log reproduces offline from the cache." | none |

## Lines worth having ready for questions
- **LLM or code?** The model only reads text (category, entities, dates, confidence) and audits; ids, dates, slots, loaners and actions are code. See `docs/design_card.md`.
- **Why no failed calls?** Every plan is rehearsed on the organizers' own `Enterprise` class first; a plan that fails rehearsal is escalated instead of sent.
- **What if the model misreads a date?** Dates are recomputed from 2027-03-08 and snapped to real shipment ETAs and lot windows; a mismatch lowers confidence and escalates.
- More: `docs/qa-notes.md`.

## If something breaks live
- UI frozen or API down: restart `scripts/dev.sh`; the page shows the committed run again.
- No key or no network: skip beat 9. Everything else runs offline (`Dry (twin)`, committed cache).
- A dry **Run feed** takes about 15 s. **Back to snapshot** appears when it ends and returns the page to the committed run (it is hidden while a run is going).
