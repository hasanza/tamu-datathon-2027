"""Task 4.4: robustness bench. A strong model rewrites each event in several messy styles; each candidate extraction model
must still resolve the same facts. Ground truth = the resolved signature of the ORIGINAL event under the reference model.

  PYTHONPATH=. uv run python eval/paraphrase_bench.py --models gemini-3.8-flash gemini-3.5-flash-lite [--per-event 6]

Paraphrases are generated once and cached (cache/llm), so reruns are free. The bench reports accuracy by model and style
and lists every disagreement, because a paraphrase that altered a fact is a bench bug, not a model bug: read the failures.
"""

import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

from control_tower.data.loader import KIT_DIR, REPO_ROOT, load_world
from control_tower.llm.adapter import _backend, complete_json
from control_tower.understanding.extract import extract
from control_tower.understanding.resolve import EntityIndex, build_incident
from control_tower.understanding.tiebreak import make_tiebreak

STYLES = [
    "a terse chat message with typos, abbreviations and no punctuation",
    "a formal email with greeting, subject line and signature",
    "a forwarded message with a long irrelevant legal disclaimer footer",
    "uses synonyms and nicknames for plants, parts and suppliers, and writes dates in a different but exactly equivalent way (for example 'the 19th', 'Mar 19', 'Fri 3/19')",
    "all-lowercase quick chat shorthand, as typed on a phone",
    "a daily-digest bullet list that also contains one unrelated item (cafeteria menu or parking notice)",
]
SYSTEM = (
    "You rewrite short operational messages from a car maker. Today is Monday 2027-03-08. Keep EVERY fact exactly: the same "
    "plants, parts, suppliers, ids, quantities, causes and dates. You may change style, wording, order and how dates are "
    "written, but each date must stay exactly equivalent (next Friday = 2027-03-19). Never add new operational incidents "
    "and never remove one. If the original is unconfirmed or irrelevant, keep it unconfirmed or irrelevant."
)


class Rewrite(BaseModel):
    text: str = Field(description="The rewritten message")


def signature(world, index, ev_id, text, source, model):
    res, _ = extract(source, "2027-03-08T08:00:00", text, model=model)
    sigs = []
    tb = make_tiebreak(world, [], model=model)
    for n, raw in enumerate(res.incidents, 1):
        r = build_incident(world, index, raw, event_id=ev_id, n=n, event_text=text, tiebreak=tb)
        s = r.spec
        if s.category == "noise":
            continue
        sigs.append(
            (
                s.category,
                s.plant_id,
                s.part_id,
                s.shipment_id,
                s.lot_id,
                str(s.orig_eta),
                str(s.new_eta),
                str(s.outage_start),
                str(s.outage_end),
                r.needs_human,
            )
        )
    return sorted(sigs, key=str)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["gemini-3.8-flash", "gemini-3.5-flash-lite"])
    ap.add_argument("--writer", default="gemini-3.8-flash")
    ap.add_argument("--per-event", type=int, default=len(STYLES))
    ap.add_argument("--report", type=Path, default=REPO_ROOT / "eval" / "reports" / "paraphrase_bench.md")
    a = ap.parse_args()
    world, index = load_world(), None
    index = EntityIndex(world)
    events = json.loads((KIT_DIR / "data" / "events.json").read_text())
    _backend("gemini")

    def write(job):
        ev, style = job
        user = f"Rewrite this message as {style}.\n\nOriginal ({ev['source']}):\n{ev['text']}"
        out, _ = complete_json(Rewrite, SYSTEM, user, "paraphrase", model=a.writer)
        return ev, style, out.text

    jobs = [(ev, st) for ev in events for st in STYLES[: a.per_event]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        variants = list(pool.map(write, jobs))
    print(f"{len(variants)} paraphrases written by {a.writer}")

    truth = {
        ev["event_id"]: signature(world, index, ev["event_id"], ev["text"], ev["source"], a.models[0]) for ev in events
    }
    lines = [
        f"# Paraphrase robustness bench\n\n{len(variants)} rewrites ({len(events)} events x {a.per_event} styles), writer {a.writer}. Ground truth: original event under {a.models[0]}.\n"
    ]
    for model in a.models:

        def run(v, model=model):
            ev, style, text = v
            try:
                return v, signature(world, index, ev["event_id"], text, ev["source"], model)
            except Exception as e:  # a model that fails to answer is a failure, not a crash
                return v, [("ERROR", str(e)[:80])]

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(run, variants))
        ok = [r for r in results if r[1] == truth[r[0][0]["event_id"]]]
        by_style: dict[str, list[int]] = {}
        for (ev, style, _), sig in results:
            by_style.setdefault(style, []).append(int(sig == truth[ev["event_id"]]))
        lines.append(f"\n## {model}: {len(ok)}/{len(results)} = {100 * len(ok) / len(results):.0f}%\n")
        for style, v in by_style.items():
            lines.append(f"- {sum(v)}/{len(v)}  {style[:70]}")
        fails = [r for r in results if r[1] != truth[r[0][0]["event_id"]]]
        for (ev, style, text), sig in fails[:25]:
            lines.append(
                f"\n**{ev['event_id']}** ({style[:40]}...)\n> {text[:300].replace(chr(10), ' ')}\n- got {sig}\n- want {truth[ev['event_id']]}"
            )
        print(f"{model:28} {len(ok)}/{len(results)} = {100 * len(ok) / len(results):.0f}%")
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text("\n".join(lines) + "\n")
    print("report:", a.report.relative_to(REPO_ROOT))


if __name__ == "__main__":
    main()
