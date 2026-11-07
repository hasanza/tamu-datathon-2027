"""Do cheaper models reach the same understanding? Runs extraction + resolution with each model and compares the
resolved incident signatures with a reference model. Prints agreement, token use and latency.

  uv run python eval/model_compare.py gemini-3.8-flash gemini-3.5-flash-lite gemini-3.1-flash-lite
"""

import json
import sys
import time

from control_tower.data.loader import KIT_DIR, load_world
from control_tower.llm.adapter import LEDGER
from control_tower.understanding.extract import extract
from control_tower.understanding.resolve import EntityIndex, build_incident


def signature(world, index, ev, model):
    res, call = extract(ev["source"], ev["received_at"], ev["text"], model=model)
    sigs = []
    for n, raw in enumerate(res.incidents, 1):
        r = build_incident(world, index, raw, event_id=ev["event_id"], n=n, event_text=ev["text"])
        s = r.spec
        sigs.append(
            (
                s.category,
                s.plant_id,
                s.part_id,
                s.shipment_id,
                s.lot_id,
                s.orig_eta,
                s.new_eta,
                s.outage_start,
                s.outage_end,
                r.needs_human,
            )
        )
    return sorted(sigs, key=str), call


def main() -> None:
    models = sys.argv[1:] or ["gemini-3.8-flash", "gemini-3.5-flash-lite"]
    world, events = load_world(), json.loads((KIT_DIR / "data" / "events.json").read_text())
    index = EntityIndex(world)
    results = {}
    for m in models:
        t0, tin, tout, sigs = time.perf_counter(), 0, 0, {}
        for ev in events:
            sigs[ev["event_id"]], c = signature(world, index, ev, m)
            tin, tout = tin + c.input_tokens, tout + c.output_tokens
        results[m] = (sigs, tin, tout, time.perf_counter() - t0)
    ref = models[0]
    print(f"reference: {ref}")
    for m in models:
        sigs, tin, tout, dt = results[m]
        agree = sum(sigs[e] == results[ref][0][e] for e in sigs)
        print(f"{m:28} agrees with reference on {agree}/{len(sigs)} events | tokens {tin}/{tout} | {dt:.1f}s")
        for e in sigs:
            if sigs[e] != results[ref][0][e]:
                print(f"    {e}: {sigs[e]}  !=  {results[ref][0][e]}")
    print("LLM calls:", len(LEDGER.calls))


if __name__ == "__main__":
    main()
