# SPEC — Hack the Highway: Event-Driven Multi-Agent Control Tower

Distilled from `HackTheHighway_Datathon_Challenge.docx`, `data/policy_handbook.md`, `enterprise.py`,
`enterprise_server.py` and the data tables. This file states what we must build, in testable terms.
Anything marked **[decision]** is a choice we made where the brief is ambiguous; anything marked
**[derived]** is a number we computed from the data ourselves (not an official expected answer).

---

## 1. Goal in one sentence

Read 15 free-text operational events, decide what each one is, find everything it touches in the company
data via a knowledge graph, and execute exactly the corrective actions the policy handbook prescribes
through the local enterprise server, with a graph path and reasoning trace per event and a control-tower UI.

## 2. What is scored (and therefore what matters)

| Weight | Criterion | What it concretely means for us |
|---|---|---|
| 50% | Event handling accuracy | `action_log.jsonl` is replayed on a fresh world and compared to the expected outcome. Right POs moved, right dealers/customers told, right loaners, right lot/vehicles, nothing on noise, escalate on rumors, **no extra actions**. |
| 20% | Knowledge graph & reasoning | Ontology quality, correct traversal, a cited graph path per event. |
| 10% | Agent architecture & guardrails | 1 coordinator + 3 specialists with clear roles; explicit LLM-vs-code split; validation before acting; failed-call handling; escalation. |
| 10% | Efficiency | Few wasted/failed tool calls; small/cheap models; **cite the model**. |
| 10% | UX & explainability | Control-tower view: event feed, graph viz, action log, audit trail, per-event summary + reason. |

Implication: the deterministic correctness of the planner is worth more than everything else combined.
The LLM should touch only the parts that need language understanding.

## 3. Inputs we are given

### 3.1 World data (`data/*.csv`, ~17k rows)

| Table | Key columns | Notes |
|---|---|---|
| `plants.csv` (6) | plant_id, name, city, slots_per_day=5 | P_TX San Antonio, P_KY Lexington, P_MS Jackson, P_IN Princeton, P_AL Huntsville, P_NC Greensboro |
| `plant_models.csv` (18) | plant_id, model | Which plant can build which model (3 models per plant). Needed for transfers. |
| `models.csv` (6) | model, segment | PIONEER, SUMMIT, RANGER, NOVA, TERRA, VOYAGER |
| `parts.csv` (20) | part_id, name, category | |
| `bom.csv` (47) | model, part_id | Model → parts. A PO "needs" a part iff its model's BOM lists it. |
| `suppliers.csv` (18) | supplier_id, name, city | Short names ("Quanta", "Orbit") are in aliases. |
| `inbound_shipments.csv` (364) | shipment_id, supplier_id, part_id, plant_id, eta_date, covers_days=5 | One shipment per (part, plant) per week, ETA on Mondays. Each supplier serves specific plants for a part (e.g. CHIP-IVI: SUP-06 → P_TX/P_MS/P_AL, SUP-12 → P_KY/P_IN/P_NC). |
| `production_orders.csv` (540) | production_order_id, plant_id, build_date, model, units | Day index −10..19. 180 already built (past), 360 future. **Every plant uses 3 of 5 slots every day → exactly 2 free slots/day/plant [derived].** |
| `customer_orders.csv` (3263) | customer_order_id, production_order_id, dealer_id, customer_id, model, promised_date | ~6 COs per PO. |
| `customers.csv` (7000) | customer_id, name, tier | Standard 5329 / Gold 1247 / Platinum 424 |
| `dealers.csv` (50) | dealer_id, name, city, region, transit_days | |
| `loaners.csv` (50) | dealer_id, loaners_available | Pools are small (2–3). |
| `part_lots.csv` (364) | lot_id, part_id, supplier_id, plant_id, first_build_date, last_build_date | Lot = the batch of a part installed at a plant over a build-date range (past dates). |
| `finished_vehicles.csv` (5348) | vin, production_order_id, model, plant_id, build_date, dealer_id, status(sold/in_stock), customer_id | Past builds only. |
| `aliases.csv` (61) | alias, entity_type, entity_id | Plant nicknames, part nicknames, supplier short names. Not exhaustive ("Volt" is listed; "Kentucky plant" is listed; "battery packs" alone is not). |
| `calendar.csv` (30) | day_index, date, weekday | Working days only, Mon–Fri, 2027-02-22 .. 2027-04-02. **Today = Monday 2027-03-08 = index 0.** |

### 3.2 Events (`data/events.json`, 15)

Fields: `event_id`, `received_at`, `source` (daily digest / ops chat / quality bulletin / news wire / plant alert / supplier email), `text`.
Our reading of the 15 [derived, to be confirmed by the system, never hard-coded]:

| Event | Category | Entities the text implies |
|---|---|---|
| E-01 | **Compound**: Plant Outage + Supplier Delay | (1) P_TX dark "next Friday" (Mar 19) through Mon Mar 22. (2) Quanta (SUP-12) infotainment chip (CHIP-IVI) to Princeton (P_IN): due "next Monday" (Mar 15) → "next Friday" (Mar 19). |
| E-02 | Unconfirmed | "something may be off with a seat material", no dates. |
| E-03 | Quality Hold | Kestrel (SUP-06) CHIP-IVI to Jackson (P_MS), built Thu Feb 25 → "last Monday" (Mar 1) ⇒ LOT-0130. |
| E-04 | Plant Outage | Kentucky plant (P_KY) "next Tuesday through next Thursday" ⇒ Mar 16–18. |
| E-05/06/07 | Noise | Dealers asking for brochure PDF. |
| E-08 | Plant Outage | P_KY 2027-03-24..25, clean. |
| E-09 | Supplier Delay | Orbit (SUP-11) surround-view cameras (CAM-360) to Huntsville (P_AL): Mar 29 → Apr 1. |
| E-10 | Supplier Delay | Lumen (SUP-18) 60 kWh battery packs (BATT-60) to Huntsville (P_AL): Mar 29 → Apr 1. |
| E-11 | Plant Outage | Jackson (P_MS) Fri Mar 26 → Tue Mar 30. |
| E-12 | Supplier Delay | SH-0182 CAM-360 to P_IN: 2027-03-15 → 2027-03-18, clean. |
| E-13 | Unconfirmed | "possible shortage of something electronic sometime soon". |
| E-14 | Quality Hold | Atlas (SUP-07) heavy-duty wiring harness (HARN-B) to Texas plant (P_TX), built Feb 22–24 ⇒ LOT-0017. |
| E-15 | Quality Hold | LOT-0191 (CHIP-IVI, SUP-12) at P_IN built Mar 2–3, clean. |

Relative-date convention observed in the data [derived]: with today = Mon Mar 8, "next Monday" = Mar 15,
"next Friday" = Mar 19, "next Tuesday..Thursday" = Mar 16–18, "last Monday" = Mar 1. "Next <weekday>" means
that weekday of **next week**, not the coming one. This is cross-checkable against the data: resolved shipment
dates must land on an actual `eta_date`, and resolved lot windows must match an actual lot's first/last build date.

### 3.3 Enterprise server (`enterprise_server.py`, stdlib HTTP on 127.0.0.1:8000)

```
python enterprise_server.py --data data --events data/events.json --out runs/run1 --port 8000 [--overwrite]
GET  /events          -> list of events
GET  /tools           -> tool catalogue
POST /act {"event_id","tool","args"} -> result | 400 {"error"}  (every call appended to <out>/action_log.jsonl)
```

Each event has its own fresh world state (keyed by event_id). Log line format: `{"event_id","tool","args","ok"}`.
Failed calls are logged with `ok:false` and **count against us**.

### 3.4 Tools (from `enterprise.py` `TOOLS`) and their failure conditions

| Tool | Writes | Args | Fails when |
|---|---|---|---|
| `mes.get_schedule` | no | plant_id, date | unknown plant; date not a weekday in [today, 2027-04-02] |
| `mes.reschedule` | yes | production_order_id, new_date | PO unknown/already built; same slot; day full (≥5) |
| `mes.transfer` | yes | production_order_id, to_plant_id, new_date | plant doesn't build model; same plant (must use reschedule); day full |
| `dealer.notify` | yes | dealer_id, customer_order_ids[], message | any CO not belonging to that dealer; empty list |
| `dealer.stop_sale` | yes | dealer_id, vins[] | any VIN not `in_stock` at that dealer |
| `crm.loaner_availability` | no | dealer_id | unknown dealer |
| `crm.assign_loaner` | yes | customer_order_id | CO already has loaner; dealer pool at 0 |
| `crm.notify_customer` | yes | customer_id, message | unknown customer |
| `quality.hold_lot` | yes | lot_id | unknown lot |
| `escalate` | no | reason | — |

The server does **not** check whether a record is "affected"; that is entirely our responsibility (rule 10).

## 4. Functional requirements

### FR-1 Event understanding (LLM + code)
- Classify each event into exactly one of: `supplier_delay`, `plant_outage`, `quality_hold`, `noise`, `unconfirmed`, `compound`.
- Compound events are split into N `IncidentSpec`s, each with its own category.
- Extract per incident: plant, part, supplier, shipment_id (if given), lot_id (if given), original ETA, new ETA, outage start/end, build window start/end, free-text reason.
- Resolve names → ids using `aliases.csv` first, then table names (plants/parts/suppliers), then fuzzy match. Unresolvable required entity ⇒ confidence drop ⇒ escalate.
- Resolve relative dates deterministically relative to 2027-03-08 using the convention in §3.2; cross-validate against shipment ETAs / lot windows.
- Produce a confidence score and a list of unresolved ambiguities per incident.

### FR-2 Knowledge graph / ontology (code)
Node types: Supplier, Part, Model, Plant, Shipment, ProductionOrder, CustomerOrder, Customer, Dealer, Lot, Vehicle, Day.
Edge types (directed, typed): Supplier-SUPPLIES→Part, Shipment-OF_PART→Part, Shipment-TO_PLANT→Plant, Shipment-FROM→Supplier,
Model-USES_PART→Part (BOM), Plant-BUILDS_MODEL→Model, ProductionOrder-AT_PLANT→Plant, ProductionOrder-OF_MODEL→Model,
ProductionOrder-ON_DAY→Day, CustomerOrder-FULFILLED_BY→ProductionOrder, CustomerOrder-SOLD_BY→Dealer, CustomerOrder-FOR→Customer,
Lot-OF_PART→Part, Lot-AT_PLANT→Plant, Lot-FROM→Supplier, Vehicle-BUILT_BY→ProductionOrder, Vehicle-AT_DEALER→Dealer,
Vehicle-OWNED_BY→Customer, Dealer-HAS_LOANER_POOL (attribute).
Requirements:
- Build once from CSVs at startup (in memory). Traversals return the **path** (nodes + edges) that justify each affected record.
- Export: ontology diagram (Mermaid/PNG) + graph export (GraphML or JSON) for submission.
- Required cited paths: Shipment→Part→Model(BOM)→PO→CO→Dealer/Customer; Plant→PO→CO→Dealer/Customer; Lot→PO→Vehicle→Dealer/Customer.

### FR-3 Impact analysis (code, exact handbook rules)
- **Supplier delay**: affected POs = POs at the receiving plant whose model's BOM includes the part, with build_date in [orig_eta, new_eta) (new ETA exclusive). Disruption end = new_eta.
- **Plant outage**: affected POs = all POs of the plant with build_date in [start, end] (inclusive). Disruption end = next working day after `end`.
- **Quality hold**: lot = the `part_lots` row matching (part, plant, build window); affected vehicles = finished vehicles at that plant with build_date in [first, last] whose model's BOM includes the part. Split into `in_stock` (grouped by dealer) and `sold` (unique owners).
- Only future POs (build_date ≥ today) can be moved; the server rejects past ones.

### FR-4 Rescheduling planner (code)
- For each affected PO, in a fixed deterministic order **[decision: by original build_date, then PO id]**:
  1. Earliest same-plant working day ≥ disruption end with a free slot (capacity 5, counting moves already planned in this event) → `mes.reschedule`.
  2. Else earliest free slot at another plant that builds the model (`plant_models`) **[decision: any working day from today through 2027-04-02; ties broken by date then plant id]** → `mes.transfer`.
  3. Else escalate (no capacity) — should not happen in this dataset.
- Shared state across incidents within a compound event (slots and loaner pools are a single world per event).
- Never move an unaffected PO.

### FR-5 Dealer & customer care planner (code)
- Affected COs = COs whose PO was moved. Group by dealer → exactly one `dealer.notify` per dealer with exactly those CO ids.
- Loaners: entitled = Platinum or Gold. Sort by (tier rank Platinum<Gold, promised_date asc, customer_order_id asc) per dealer; assign up to `loaners_available` from `crm.loaner_availability` (read, free) minus already assigned in this event. **Never call assign when pool is exhausted** (avoids a counted failure). Standard customers: no loaner, no customer notification.
- Quality hold: `quality.hold_lot` once; `dealer.stop_sale` once per dealer with all its in-stock affected VINs; `crm.notify_customer` once per owner of a sold affected vehicle.

### FR-6 Guardrails (code + LLM)
- Noise ⇒ zero write calls, with a stated reason.
- Unconfirmed/unclear ⇒ exactly one `escalate` with a specific reason, zero write calls.
- Every planned action is validated against the graph before execution (record exists, belongs to the dealer, is in_stock, PO is future, plant builds model, slot free).
- Every plan is rehearsed on an in-process twin of the world (import `enterprise.Enterprise`) before any call reaches the server; a plan with any failing step is not executed and is escalated instead.
- Real incidents must end with ≥3 distinct action kinds (rule 9); if the plan cannot reach 3 (e.g. no eligible loaner customers), log why.
- Failed server call at runtime: capture error, do not retry blindly, mark the event, escalate with the error text.
- Confidence gate: below threshold → escalate instead of act.

### FR-7 Multi-agent orchestration
Exactly one coordinator and three specialists, with written responsibilities (see PLAN.md §4). Each agent emits a trace of its steps.

### FR-8 Tool execution (MCP-style)
Actions are executed through an MCP server that wraps `POST /act` (and read tools). The same MCP server is usable from Claude Code during development.

### FR-9 Explainability outputs (per event)
- `traces/<event_id>.json`: classification, extracted incidents, resolution steps, graph paths, plan, rehearsal result, executed actions with results, final summary + reason.
- Human-readable summary and "why we did / did not act".

### FR-10 Control-tower UI
Panels: live event feed; per-event category + confidence; graph path visualization (highlighted subgraph); agents' activity/trace timeline; action log; audit trail (what changed vs. baseline); escalation inbox.

### FR-11 Submission artifacts
`runs/final/action_log.jsonl` (15 events, one server run), source code, ontology diagram + graph export, `traces/*.json`, demo video or screenshots, one-page design card (architecture, LLM vs code, guardrails, evaluation, improvements), **model citation**.

## 5. Policy rules as algorithms (authoritative reference for the planner)

```
TODAY = 2027-03-08 ; WINDOW = working days idx 0..19 ; CAP = 5 slots/plant/day

affected_pos(supplier_delay):  {po | po.plant==plant and part in BOM[po.model] and orig_eta <= po.date < new_eta}
affected_pos(plant_outage):    {po | po.plant==plant and start <= po.date <= end}
disruption_end(delay)=new_eta ; disruption_end(outage)=next_working_day(end)

for po in sorted(affected, key=(date, id)):
    d = first day >= disruption_end with used[plant,d] < CAP      -> reschedule(po, d)
    else (p2, d2) = min over p2 in builders(model)\{plant}, d2 in WINDOW with used[p2,d2] < CAP, key=(d2, p2) -> transfer(po, p2, d2)
    used[...] += 1

affected_cos = {co | co.po in moved}
for dealer, cos in group(affected_cos): notify(dealer, [co.id...])
for dealer: n = pool[dealer]; for co in sorted(entitled(cos), key=(tier_rank, promised, id))[:n]: assign_loaner(co)

quality: lot = match(part, plant, first, last); hold(lot)
  vehicles = {v | v.plant==plant and first <= v.date <= last and part in BOM[v.model]}
  for dealer, vins in group(in_stock): stop_sale(dealer, vins)
  for cust in unique(sold.customer): notify_customer(cust)

noise: nothing.   unconfirmed: escalate(reason) only.
```

## 6. Incident magnitudes [derived — for sizing and self-checks, not to be hard-coded]

| Incident | Affected POs | COs | Dealers | Loaner-eligible | Pool shortfall | Notes |
|---|---|---|---|---|---|---|
| E-01a P_TX outage Mar 19–22 | 6 | 55 | 27 | 8 | 0 | restart Mar 23 |
| E-01b P_IN CHIP-IVI Mar 15→19 | 8 (NOVA, VOYAGER) | 67 | 29 | 22 | 2 | shares world with E-01a |
| E-04 P_KY Mar 16–18 | 9 | 79 | 32 | 22 | 4 | priority rule matters |
| E-08 P_KY Mar 24–25 | 6 | 56 | 25 | 15 | 0 | |
| E-11 P_MS Mar 26–30 | 9 | 79 | 36 | 18 | 1 | only 6 same-plant slots left (Mar 31–Apr 2) ⇒ **3 transfers required** |
| E-09 P_AL CAM-360 Mar 29→Apr 1 | 6 (SUMMIT, VOYAGER) | 54 | 26 | 12 | 2 | |
| E-10 P_AL BATT-60 Mar 29→Apr 1 | 3 (NOVA) | 29 | 18 | 7 | 0 | |
| E-12 P_IN CAM-360 Mar 15→18 | 3 (VOYAGER) | 26 | 14 | 10 | 0 | |

| Quality incident | Lot | Vehicles | Sold (owners) | In stock (dealers) | Write calls |
|---|---|---|---|---|---|
| E-03 P_MS CHIP-IVI Feb 25–Mar 1 | LOT-0130 | 260 | 150 | 110 (37) | 1 + 37 + 150 = 188 |
| E-14 P_TX HARN-B Feb 22–24 | LOT-0017 | 180 | 94 | 86 (36) | 131 |
| E-15 P_IN CHIP-IVI Mar 2–3 | LOT-0191 | 116 | 76 | 40 (25) | 102 |

Total expected write calls across the run: roughly 700. The LLM must not be in the loop per action.

## 7. Ambiguities and our decisions

| # | Ambiguity | Decision | Risk / mitigation |
|---|---|---|---|
| A1 | Order in which affected POs claim scarce slots (changes which PO gets which day, and which get transferred in E-11). | Sort by (original build_date, PO id); greedy earliest slot. | Make the policy a single configurable function; document in design card. |
| A2 | Transfer target day: "any day with a free slot" — from today, or only on/after the disruption end? | **`today` (decided 2026-11-08, flipped after an independent Codex read rated it ~80% likely):** earliest free slot at another plant from day 0, per the literal text of rule 3 ("on any day with a free slot", earliest feasible slot). Affects only E-09 (2 orders) and E-11 (3 orders), all landing Mar 8. `--transfer-min-day disruption_end` restores the later, parts-safe reading (E-11 lands Mar 31). | One flag; stated in the design card. |
| A3 | Tie-break among transfer plants on the same day. | Plant id order. | Config. |
| A4 | "Next Friday" on a Monday. | Next week's Friday (Mar 19). Cross-validated by "through Monday Mar 22" and by shipment ETA Mondays. | If the resolved date doesn't land on a real ETA/lot boundary, lower confidence; if two readings both fit, escalate. |
| A5 | Quality hold on past builds: should the loaner/dealer-notify logic also run? | No. Rule 6 lists exactly hold, stop_sale, notify owners. | — |
| A6 | Loaner priority is stated globally ("Platinum before Gold, then promised date, then id") but pools are per dealer. | Apply the ordering within each dealer's pool. | — |
| A7 | Customer with multiple affected COs at one dealer. | One loaner per CO is what the tool allows; the rule says "a customer ... gets one loaner". Assign per CO but cap one per customer. | Config flag. |
| A8 | `dealer.notify` message and `crm.notify_customer` message content. | Templated, specific (ids, old/new dates). LLM polish optional. | Templates are deterministic and cheap. |
| A9 | Whether to call `mes.get_schedule`/`crm.loaner_availability` (free) before writes. | Yes, read tools are free and make the trace auditable; also reconciles our twin with the server. | — |
| A10 | E-01 compound shares slots across P_TX transfers and P_IN reschedules. | Single world state per event; incidents planned sequentially in text order. | — |

## 8. Non-functional requirements
- Runs on one laptop; the only network dependency is the LLM API (or none, with a local model).
- Whole 15-event run < 5 minutes; LLM spend for a full run < $0.25 at Haiku 5.5 prices.
- Deterministic planner: same inputs ⇒ same plan (unit-testable without an LLM).
- Model(s) used cited in README and design card, with per-run token/cost totals in the trace.

## 9. Out of scope
Changing `enterprise.py`/server; any cloud deployment; training models; handling events not in the feed format.
