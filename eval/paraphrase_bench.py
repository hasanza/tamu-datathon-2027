"""Task 4.4 (v2): robustness bench. A strong model rewrites each event in several messy styles; each candidate model, playing
the COORDINATOR, must still understand the same facts. Ground truth = the resolved signature of the ORIGINAL event under
the reference model (the first of --models).

  PYTHONPATH=. uv run python eval/paraphrase_bench.py --models gemini/gemini-3.8-flash gemini/gemini-3.5-flash-lite [--per-event 6]

What is measured is the coordinator's understanding as the pipeline really does it: the hub agent loop runs live with its
real system prompt and calls `register_incidents`; the signature is read from the incidents AFTER resolution (aliases,
date snapping, closed-set tie-break) plus the needs_human flag. The old single-shot extract() path is not used. Only
register_incidents is offered (no delegation, no writes), so a run costs a couple of model calls.

Paraphrases are regenerated live on every run (no cache). The bench reports accuracy by model and style
and lists every disagreement, because a paraphrase that altered a fact is a bench bug, not a model bug: read the failures.
Report: eval/reports/paraphrase_bench.md
"""

import argparse
import dataclasses
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

from control_tower.data.loader import KIT_DIR, REPO_ROOT, load_world
from control_tower.llm.adapter import _backend, complete_json
from control_tower.orchestration.context import EventContext
from control_tower.orchestration.coordinator_agent import PROMPT
from control_tower.orchestration.coordinator_tools import cs
from control_tower.orchestration.runtime import AgentSpec, run_agent
from control_tower.orchestration.tools import REGISTRY
from control_tower.trace import Sink, Timeline
from control_tower.understanding.resolve import EntityIndex

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


class Done(BaseModel):
    ok: bool = True


BENCH_TASK = (
    "BENCHMARK TASK: understand the message. Call register_incidents exactly once with your reading of INPUT.text, "
    'then return final {"ok": true}. Do not try to gate, delegate or execute: only register_incidents is available.'
)


def signature(world, index, ev_id, text, source):
    """Run the coordinator agent (model = 'provider/model' or a bare model) on the text up to register_incidents and
    return the sorted resolved signatures of its non-noise incidents."""
    captured: dict = {}
    reg = REGISTRY["register_incidents"]

    def fn(ctx, args):
        out = reg.fn(ctx, args)
        captured["ctx"] = ctx
        return out

    spec = AgentSpec("coordinator", "Coordinator", PROMPT, [dataclasses.replace(reg, fn=fn)], Done)
    tl = Timeline(ev_id, "2027-03-08T08:00:00", Sink(None))
    ctx = EventContext(
        world=world, event_id=ev_id, index=index, event={"id": ev_id, "text": text, "source": source}, timeline=tl
    )
    ctx.state["opts"] = {"use_tiebreak": True}
    payload = {"event_id": ev_id, "source": source, "received_at": "2027-03-08T08:00:00", "text": text}
    res = run_agent(spec, BENCH_TASK, payload, ctx, tl)  # the model comes from CT_MODEL_COORDINATOR (set by use_model)
    if "ctx" not in captured:
        raise RuntimeError(res.error or "register_incidents was never called")
    st = cs(ctx)
    sigs = []
    for iid, s in ctx.incidents.items():
        if s.category == "noise":
            continue
        sigs.append(
            (
                s.category, s.plant_id, s.part_id, s.shipment_id, s.lot_id, str(s.orig_eta), str(s.new_eta),
                str(s.outage_start), str(s.outage_end), st.needs_human.get(iid, False),
            )
        )  # fmt: skip
    return sorted(sigs, key=str)


def use_model(model: str) -> None:
    """Point the coordinator agent at `model` ('provider/model') for the calls that follow (process-wide override)."""
    os.environ["CT_MODEL_COORDINATOR"] = model


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="+", default=["gemini/gemini-3.8-flash", "gemini/gemini-3.5-flash-lite"])
    ap.add_argument("--writer", default="gemini-3.8-flash", help="paraphrase writer model (provider from LLM_PROVIDER)")
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

    use_model(a.models[0])
    with ThreadPoolExecutor(max_workers=6) as pool:
        truth = dict(
            pool.map(
                lambda ev: (ev["event_id"], signature(world, index, ev["event_id"], ev["text"], ev["source"])), events
            )
        )
    lines = [
        f"# Paraphrase robustness bench\n\n{len(variants)} rewrites ({len(events)} events x {a.per_event} styles), writer {a.writer}. Ground truth: original event under {a.models[0]}.\n"
    ]
    for model in a.models:
        use_model(model)

        def run(v):
            ev, style, text = v
            try:
                return v, signature(world, index, ev["event_id"], text, ev["source"])
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
