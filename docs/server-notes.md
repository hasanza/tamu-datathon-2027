# Enterprise server notes (task 0.5)

Observed behaviour of `hack_the_highway/enterprise_server.py` + `enterprise.py`, probed live on 2026-11-07 with
`--out runs/dev --port 8000 --overwrite`. Every error string below was captured from a real response, not read off the code.
Probe data: PO-0031 (P_TX, RANGER, 2027-03-08), CO-00001 (D27, C1252), VIN AUR0000002 (in_stock at D45), LOT-0001.

## 1. Transport

```bash
uv run python hack_the_highway/enterprise_server.py --data hack_the_highway/data \
  --events hack_the_highway/data/events.json --out runs/dev --port 8000 --overwrite
```

- Binds `127.0.0.1` only. Stdlib `ThreadingHTTPServer`; a lock serialises `/act`. Responses are HTTP/1.0 JSON.
- Without `--overwrite` it refuses to start if `<out>/action_log.jsonl` is non-empty. The world is in memory, so a restart resets it.
- No CORS headers (a browser cannot call it directly; go through FastAPI or MCP).
- No auth.

| Request | Status | Body |
|---|---|---|
| `GET /events` | 200 | list of 15 `{event_id, received_at, source, text}` |
| `GET /tools` | 200 | list of `{tool, desc, args}` (no `writes` flag is exposed, see §4) |
| any other `GET` | 404 | `{"error": "use /events, /tools or POST /act"}` |
| `POST` to any path but `/act` | 404 | `{"error": "use POST /act"}` |

### `POST /act` envelope

Body: `{"event_id": str, "tool": str, "args": object}`. `args` defaults to `{}` if the key is absent.

| Situation | Status | Error | Logged? |
|---|---|---|---|
| Body not JSON, empty, a JSON list, or missing `event_id`/`tool` | 400 | `body must be {"event_id", "tool", "args"}` | no |
| `event_id` not one of the 15 (case-sensitive: `e-01` fails) | 404 | `unknown event_id` | no |
| `tool` not in the catalogue (case-sensitive) | 400 | `unknown tool` | **yes, ok:false** |
| `args` is not an object (list, string, `null`) | 400 | `args must be an object` | **yes, ok:false** |
| `event_id` or `tool` is a JSON list/object (unhashable) | none: connection closed, `curl` exit 52 | handler raises `TypeError`; server stays up | no |
| Tool raises `ToolError` | 400 | `{"error": "<message>"}` (messages below) | **yes, ok:false** |
| Success | 200 | tool response | yes, ok:true |

Success = HTTP 200, failure = HTTP 400 with `{"error": ...}`. Never retry blindly: a failed call changes nothing but is logged and counted.

### Action log

`<out>/action_log.jsonl`, one line per call that got past the envelope checks:
`{"event_id", "tool", "args", "ok"}`. `args` is logged verbatim (can be `[]`, `null`, a string). **Read tools are logged too, and a failing
read is logged `ok:false`.** Our probe run: 103 lines, 27 ok, 76 failed.

### World state

Each `event_id` gets its own lazily created copy of the world on first call, including read calls (verified: moving PO-0394 under E-02
did not show in E-03's schedule). Initial state per event: 360 future POs (idx >= 0) in slots, loaner pools from `loaners.csv`, nothing held,
stopped, notified. Within one event, state accumulates across calls, so the planner and replay must send calls in order.

## 2. Common validation (every tool, runs first, in argument order)

| Condition | Error |
|---|---|
| required string arg missing, `""`, or not a string (e.g. `5`) | `<name> must be a non-empty string` |
| required list arg missing, `[]`, not a list, or contains a non-string | `<name> must be a non-empty list of strings` |

**Checks run in argument order and stop at the first failure.** E.g. `dealer.notify` with an unknown dealer, empty list and empty message reports
the list error, not `unknown dealer_id`, because `customer_order_ids` is validated before the dealer lookup.

### Date validation (`mes.get_schedule`, `mes.reschedule`, `mes.transfer`)

| Condition | Error |
|---|---|
| not parseable as `YYYY-MM-DD`, or a weekend (`2027-03-13`, `03/09/2027`, `garbage`) | `date must be a weekday formatted YYYY-MM-DD` |
| valid weekday outside idx 0..19 (`2027-03-05` past, `2027-04-05` after) | `date must be a working day from today through the end of the planning window` |

The message says `date` even when the argument is `new_date`. Valid range: **2027-03-08 .. 2027-04-02** inclusive, Mon-Fri.

## 3. Tools

Arguments in the table are all required. Extra arguments are silently ignored (`escalate` with `"extra": 1` returns ok).

### `mes.get_schedule` (read)
Args: `plant_id`, `date`.
Success 200:
```json
{"plant_id": "P_TX", "date": "2027-03-09", "orders": [{"production_order_id": "PO-0034", "model": "RANGER"}, ...], "free_slots": 2}
```
`orders` is sorted by PO id and reflects moves made in this event's world. Baseline is 3 orders / 2 free slots on every plant-day.
Errors (in check order): `plant_id must be a non-empty string`, then date errors (§2) **before** the plant lookup, then `unknown plant_id`.
Quirk: `P_XX` + a weekend date reports the date error, not the plant error.

### `mes.reschedule` (write)
Args: `production_order_id`, `new_date`. Success 200: `{"ok": true, "production_order_id": "PO-0031", "plant_id": "P_TX", "date": "2027-03-12"}`.
Errors, in order:
1. `production_order_id must be a non-empty string`
2. `unknown or already built production order` (unknown id **and** past POs such as PO-0001 give the same text)
3. `new_date must be a non-empty string`, then the date errors (§2)
4. `order is already there` (same plant and same day)
5. `no free slot at P_TX on that day` (day already has 5 orders; the plant id is in the message)

Verified: filling P_TX 2027-03-12 (3 baseline + 2 moves) made the third move fail with error 5.

### `mes.transfer` (write)
Args: `production_order_id`, `to_plant_id`, `new_date`. Success 200: `{"ok": true, "production_order_id": "PO-0031", "plant_id": "P_IN", "date": "2027-03-10"}`.
Errors, in order:
1. `production_order_id must be a non-empty string`, then `to_plant_id must be a non-empty string`
2. `unknown or already built production order`
3. `that plant does not build this model` (**also** the message for an unknown plant such as `P_XX`; no separate unknown-plant error)
4. `use mes.reschedule inside the same plant` (target equals the PO's **current** plant, which changes after a transfer: repeating a successful transfer gives this, not `order is already there`)
5. `new_date must be a non-empty string`, then date errors (§2)
6. `no free slot at <plant> on that day`

Note the model-compat and same-plant checks run **before** the date check, and `new_date` presence is checked last of the argument checks.

### `dealer.notify` (write)
Args: `dealer_id`, `customer_order_ids` (list), `message`. Success 200: `{"ok": true}`.
Errors, in order:
1. `dealer_id must be a non-empty string`
2. `customer_order_ids must be a non-empty list of strings`
3. `message must be a non-empty string`
4. `unknown dealer_id`
5. `not customer orders of D02: ['CO-00001']` (lists at most the **first 3** offending ids; unknown ids and ids of another dealer give the same text)

Duplicate calls with the same dealer and ids succeed (ok:true), so the server will not stop us double-notifying; rule 4 "exactly one notify" is ours to enforce.
The validation is all-or-nothing: one bad id rejects the whole call.

### `dealer.stop_sale` (write)
Args: `dealer_id`, `vins` (list). Success 200: `{"ok": true}`.
Errors, in order: `dealer_id must be a non-empty string`, `vins must be a non-empty list of strings`, `unknown dealer_id`,
`not unsold vehicles at D45: ['AUR0000001']` (first 3 offenders; covers unknown VINs, VINs at a different dealer, and `sold` VINs).
All-or-nothing (mixed in_stock + sold list is rejected entirely). Duplicates succeed.

### `crm.loaner_availability` (read)
Args: `dealer_id`. Success 200: `{"dealer_id": "D27", "available": 1}` (live value, drops after `crm.assign_loaner`).
Errors: `dealer_id must be a non-empty string`, `unknown dealer_id`.

### `crm.assign_loaner` (write)
Args: `customer_order_id`. Success 200: `{"ok": true, "dealer_id": "D27"}`; decrements that dealer's pool by 1.
Errors, in order: `customer_order_id must be a non-empty string`, `unknown customer_order_id`, `already has a loaner`, `no loaners left at D27`.
`already has a loaner` wins over pool exhaustion (verified with pool = 0). **The server does not check tier or whether the CO is affected**:
a Standard customer's CO got a loaner (ok:true) and consumed a pool unit. Entitlement and affectedness are entirely ours (rules 5, 10).
The pool is per dealer, per event world; D27 started with 1.

### `crm.notify_customer` (write)
Args: `customer_id`, `message`. Success 200: `{"ok": true}`.
Errors, in order: `customer_id must be a non-empty string`, `message must be a non-empty string`, `unknown customer_id`. Duplicates succeed.

### `quality.hold_lot` (write)
Args: `lot_id`. Success 200: `{"ok": true}`. Errors: `lot_id must be a non-empty string`, `unknown lot_id`. Duplicates succeed.
The server does not check that the lot matches the event.

### `escalate` (no world effect, but listed `writes: false`)
Args: `reason`. Success 200: `{"ok": true}`. Errors: `reason must be a non-empty string` (missing, `""`, or non-string).
Sets an `escalated` flag; repeated escalations succeed. Logged like any other call.

## 4. Things the other side should know

- **No idempotency anywhere except moves.** Duplicate `dealer.notify`, `stop_sale`, `notify_customer`, `hold_lot` and `escalate` all return ok:true and
  are all logged; the grader sees every duplicate line. Only `mes.*` and `crm.assign_loaner` reject repeats.
- **`GET /tools` omits the `writes` flag** that `enterprise.TOOLS` has. A client that needs read/write classification (the MCP wrapper, 1.5; the UI)
  must hard-code `{mes.get_schedule, crm.loaner_availability}` plus `escalate` as non-writes, or import `enterprise.WRITE_TOOLS`.
- **Error messages carry ids** (`no free slot at P_TX`, `no loaners left at D27`, first 3 offending ids), so they are useful to show verbatim in
  the trace, but the text is the only machine-readable signal: there are no error codes. Match on HTTP status (400 vs 200) first.
- **Transport-level failures are not in the log** (bad envelope, unknown event_id, crash on unhashable ids). Only the 400s from `ent.call` are.
- **Unhashable `event_id`/`tool` kills the connection with no reply.** Make clients send strings only (a Pydantic model upstream is enough).
- Everything is single-process in memory: restarting the server resets all worlds, and with `--overwrite` also truncates the log.
