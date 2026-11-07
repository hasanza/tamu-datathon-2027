"""Run extraction + resolution on every event and print what the understanding layer concluded (no actions)."""

import json
import sys

from control_tower.data.loader import KIT_DIR, load_world
from control_tower.llm.adapter import LEDGER
from control_tower.understanding.extract import extract
from control_tower.understanding.resolve import EntityIndex, build_incident


def main() -> None:
    only = set(sys.argv[1:])
    world = load_world()
    index = EntityIndex(world)
    events = json.loads((KIT_DIR / "data" / "events.json").read_text())
    for ev in events:
        if only and ev["event_id"] not in only:
            continue
        res, call = extract(ev["source"], ev["received_at"], ev["text"])
        print(
            f"\n=== {ev['event_id']} ({call.model}, {call.input_tokens}+{call.output_tokens} tok{', cached' if call.cached else ''})"
        )
        print("   ", ev["text"][:110].replace("\n", " "))
        for n, raw in enumerate(res.incidents, 1):
            r = build_incident(world, index, raw, event_id=ev["event_id"], n=n, event_text=ev["text"])
            s = r.spec
            bits = {
                k: v
                for k, v in {
                    "plant": s.plant_id, "part": s.part_id, "sup": s.supplier_id, "ship": s.shipment_id, "lot": s.lot_id,
                    "orig": s.orig_eta, "new": s.new_eta, "from": s.outage_start, "to": s.outage_end,
                    "win": (s.build_window_start, s.build_window_end) if s.build_window_start else None,
                }.items()
                if v
            }  # fmt: skip
            print(f"  #{n} {s.category:15} conf={s.confidence:.2f} human={r.needs_human} {bits}")
            for a in s.ambiguities:
                print(f"       ! {'BLOCK ' if a.blocking else ''}{a.field}: {a.issue}")
    print(f"\ntotal LLM calls {len(LEDGER.calls)}, cached {sum(c.cached for c in LEDGER.calls)}, tokens in/out "
          f"{sum(c.input_tokens for c in LEDGER.calls)}/{sum(c.output_tokens for c in LEDGER.calls)}")  # fmt: skip


if __name__ == "__main__":
    main()
