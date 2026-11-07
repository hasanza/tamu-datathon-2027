"""Does the auditor catch planted mistakes without objecting to correct plans?

Builds the coordinator's REAL digests for a few events, then audits each unmodified (must agree) and with one planted
mistake (must raise a blocking concern).   PYTHONPATH=. uv run python eval/auditor_bench.py gemini-3.8-flash
"""

import json
import pathlib
import sys
import tempfile

from control_tower.agents import coordinator as cm
from control_tower.agents.auditor import audit as real_audit
from control_tower.agents.coordinator import Coordinator
from control_tower.data.loader import KIT_DIR, load_world
from control_tower.graph.ontology import build_graph
from control_tower.trace import Sink
from control_tower.understanding.resolve import EntityIndex
from control_tower.world.executor import TwinExecutor
from control_tower.world.twin import Twin

CASES = [  # (event, label, mutation or None, should_block)
    ("E-04", "unmodified", None, False), ("E-04", "wrong plant", lambda d: d.replace("plant P_KY", "plant P_MS"), True),
    ("E-04", "dates a week early", lambda d: d.replace("2027-03-16 to 2027-03-18", "2027-03-09 to 2027-03-11"), True),
    ("E-04", "dealers notified twice", lambda d: d.replace("one per dealer: True", "one per dealer: False"), True),
    ("E-12", "unmodified", None, False), ("E-12", "wrong due date", lambda d: d.replace("due 2027-03-15", "due 2027-03-22"), True),
    ("E-12", "wrong part", lambda d: d.replace("part CAM-360", "part CHIP-IVI"), True),
    ("E-14", "unmodified", None, False), ("E-14", "wrong lot", lambda d: d.replace("lot LOT-0017", "lot LOT-0018"), True),
    ("E-14", "wrong plant", lambda d: d.replace("plant P_TX", "plant P_KY"), True),
    ("E-11", "unmodified", None, False), ("E-08", "unmodified", None, False), ("E-09", "unmodified", None, False),
    ("E-01", "unmodified", None, False), ("E-03", "unmodified", None, False), ("E-15", "unmodified", None, False),
    ("E-10", "unmodified", None, False),
]  # fmt: skip


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else None
    world = load_world()
    events = {e["event_id"]: e for e in json.loads((KIT_DIR / "data" / "events.json").read_text())}
    captured: dict[str, str] = {}
    cm.audit = lambda source, text, digest, calls, **k: captured.setdefault(text, digest) and None
    tmp = pathlib.Path(tempfile.mkdtemp())
    c = Coordinator(world, build_graph(world), EntityIndex(world), Twin(), TwinExecutor(tmp / "l.jsonl"), traces_dir=tmp / "t", sink=Sink(None), use_tiebreak=True, use_audit=True)  # fmt: skip
    for eid in {e for e, *_ in CASES}:
        c.handle(events[eid])
    good = bad_caught = bad = false_alarm = 0
    for eid, label, mut, should_block in CASES:
        text = events[eid]["text"]
        digest = captured[text] if mut is None else mut(captured[text])
        assert digest != captured[text] or mut is None, f"mutation did nothing for {eid} {label}"
        v = real_audit(events[eid]["source"], text, digest, [], model=model)
        blocking = [x for x in v.concerns if x.severity == "blocking"]
        ok = bool(blocking) == should_block
        if should_block:
            bad += 1
            bad_caught += ok
        else:
            good += 1
            false_alarm += not ok
        print(
            f"{'OK  ' if ok else 'MISS'} {eid} {label:24} blocking={len(blocking)} {(blocking[0].issue[:80] if blocking else '')}"
        )
    print(
        f"\n{model or 'default'}: caught {bad_caught}/{bad} planted mistakes, {false_alarm} false alarms on {good} correct plans"
    )


if __name__ == "__main__":
    main()
