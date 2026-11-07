---
paths:
  - "src/control_tower/agents/**"
  - "src/control_tower/graph/**"
  - "src/control_tower/world/**"
  - "eval/oracle.py"
---
# Planner rules (deterministic zone)

- No LLM imports here (no `anthropic`, `google`, `control_tower.understanding.extract`). Pure functions over the graph and dates.
- Implement `hack_the_highway/data/policy_handbook.md` rules 1–10 literally; cite the rule number in a docstring or comment.
- Today is Monday 2027-03-08 (working-day index 0). Working days only, window index 0..19 (2027-04-02). Use `calendar.csv`.
- Supplier delay: affected POs at the receiving plant, model's BOM includes the part, `orig_eta <= build_date < new_eta`.
- Plant outage: affected POs at the plant with `start <= build_date <= end`; restart = next working day after `end`.
- Reschedule: earliest same-plant day >= disruption end with a free slot (5/day, counting moves already planned in this event);
  else transfer to another plant that builds the model (`plant_models.csv`) at the earliest free slot; never move unaffected POs.
- Dealer notify: exactly one per dealer with exactly the affected customer order ids. Loaners: Platinum/Gold only, priority
  (Platinum, earlier promised_date, lower CO id), within the dealer's pool; never call assign when the pool is exhausted.
- Quality: hold the matched lot; affected vehicles = finished vehicles at that plant, build_date in the lot window, model uses the part;
  `in_stock` → `dealer.stop_sale` grouped by dealer; `sold` → `crm.notify_customer` once per owner.
- Every affected record carries its graph path. Policy choices for ambiguities A1–A3 (docs/SPEC.md §7) live in one config object.
- Every planner function has a unit test that uses the real CSVs and the twin, and runs offline.
