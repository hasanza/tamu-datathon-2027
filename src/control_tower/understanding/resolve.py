"""Deterministic resolution and validation of what the LLM extracted (docs/SPEC.md FR-1, PLAN §5.2).

The LLM proposes phrases; this module turns them into ids and working-day dates, snaps them to the data
(real shipments, real lots), records every step, and computes the confidence. Nothing here calls a model.

Relative-date convention (verified against the data, docs/SPEC.md §3.2): weeks run Monday-Friday and today is Monday
2027-03-08, so "next <weekday>" is that weekday of NEXT week and "last <weekday>" is that weekday of LAST week.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from rapidfuzz import fuzz, process

from control_tower.data.loader import TODAY, World
from control_tower.graph.traverse import find_lots
from control_tower.schemas.incident import Ambiguity, IncidentSpec, ResolutionStep
from control_tower.understanding.schemas import DateMention, RawIncident

WEEKDAYS = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}  # fmt: skip
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4, "may": 5,
    "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}  # fmt: skip
_WD = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_MO = "|".join(sorted(MONTHS, key=len, reverse=True))
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_MD = re.compile(
    rf"\b(?:(?P<wd>{_WD})\.?,?\s+)?(?P<mo>{_MO})\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y>\d{{4}}))?\b", re.I
)
_DM = re.compile(
    rf"\b(?:(?P<wd>{_WD})\.?,?\s+)?(?P<d>\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?(?P<mo>{_MO})\b\.?(?:,?\s+(?P<y>\d{{4}}))?",
    re.I,
)
_NUM = re.compile(rf"\b(?:(?P<wd>{_WD})\.?,?\s+)?(?P<m>\d{{1,2}})/(?P<d>\d{{1,2}})(?:/(?P<y>\d{{2,4}}))?\b", re.I)
_REL = re.compile(rf"\b(?P<rel>next|nxt|nx|last|lst|this|coming|previous)\s+(?P<wd>{_WD})\b", re.I)
_BARE_WD = re.compile(rf"\b(?P<wd>{_WD})\b", re.I)
_ID_PATTERNS = {
    "plant": re.compile(r"\bP_[A-Z]{2}\b"),
    "supplier": re.compile(r"\bSUP-\d{2}\b"),
    "shipment": re.compile(r"\bSH-\d{4}\b"),
    "lot": re.compile(r"\bLOT-\d{4}\b"),
    "part": re.compile(r"\b(?:TIRE|WHEEL|SEAT|HARN|CHIP|BATT|BRAKE|AIRBAG|DOOR|DISPLAY|CAM)-[A-Z0-9]+\b"),
}


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


@dataclass(frozen=True)
class ParsedDate:
    value: date | None
    note: str  # how it was derived, or why it failed
    weekday_mismatch: bool = False


def parse_date_phrase(text: str, *, today: date = TODAY, direction: str = "future") -> ParsedDate:
    """Phrase -> date. `direction` only matters for a bare weekday ("Friday"): future = next on/after today."""
    t = " ".join(text.strip().split())
    if m := _ISO.search(t):
        return ParsedDate(date(int(m[1]), int(m[2]), int(m[3])), "iso date")
    if m := _NUM.search(t):
        try:
            y = int(m["y"]) if m["y"] else today.year
            d = date(y + 2000 if y < 100 else y, int(m["m"]), int(m["d"]))
        except ValueError:
            return ParsedDate(None, f"invalid calendar date in {t!r}")
        if m["wd"] and d.weekday() != WEEKDAYS[m["wd"].lower()]:
            return ParsedDate(d, f"numeric date; weekday word disagrees ({d:%A})", weekday_mismatch=True)
        return ParsedDate(d, "numeric month/day" + (" with matching weekday" if m["wd"] else ""))
    for pat in (_MD, _DM):
        if m := pat.search(t):
            try:
                year = int(m["y"]) if m["y"] else today.year
                d = date(year, MONTHS[m["mo"].lower()], int(m["d"]))
            except ValueError:
                return ParsedDate(None, f"invalid calendar date in {t!r}")
            if m["wd"]:
                wd = WEEKDAYS[m["wd"].lower()]
                if d.weekday() != wd:
                    return ParsedDate(d, f"explicit date; weekday word disagrees ({d:%A})", weekday_mismatch=True)
            return ParsedDate(d, "explicit month/day" + (" with matching weekday" if m["wd"] else ""))
    if m := _REL.search(t):
        off = WEEKDAYS[m["wd"].lower()]
        rel = m["rel"].lower()
        if rel in {"next", "nxt", "nx"}:
            return ParsedDate(_monday(today) + timedelta(days=7 + off), "'next <weekday>' = that weekday of next week")
        if rel in {"last", "lst", "previous"}:
            return ParsedDate(_monday(today) - timedelta(days=7 - off), "'last <weekday>' = that weekday of last week")
        return ParsedDate(_monday(today) + timedelta(days=off), "'this <weekday>' = that weekday of this week")
    low = t.lower()
    if low in {"today", "now"}:
        return ParsedDate(today, "today")
    if low == "tomorrow":
        return ParsedDate(today + timedelta(days=1), "tomorrow")
    if low == "yesterday":
        return ParsedDate(today - timedelta(days=1), "yesterday")
    leftover = _BARE_WD.sub(" ", t.lower())
    leftover = re.sub(r"\b(on|the|this|coming|upcoming|by|at|end|of|day)\b|[^a-z0-9]", " ", leftover).split()
    if (m := _BARE_WD.search(t)) and leftover:
        return ParsedDate(None, f"weekday with extra words/digits not understood: {t!r}")
    if m:
        off = WEEKDAYS[m["wd"].lower()]
        cand = _monday(today) + timedelta(days=off)
        if direction == "future" and cand < today:
            cand += timedelta(days=7)
        if direction == "past" and cand > today:
            cand -= timedelta(days=7)
        return ParsedDate(cand, f"bare weekday resolved to the nearest {direction} occurrence")
    return ParsedDate(None, f"could not parse date phrase {t!r}")


def _norm(s: str) -> str:
    s = s.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9\-_ ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[4:] if s.startswith("the ") else s


class EntityIndex:
    """alias / id / name -> (entity_type, id). Built from aliases.csv plus the canonical tables."""

    def __init__(self, world: World) -> None:
        self.by_type: dict[str, dict[str, str]] = defaultdict(dict)
        self.source: dict[tuple[str, str], str] = {}

        def add(etype: str, key: str, eid: str, source: str) -> None:
            k = _norm(key)
            if k and k not in self.by_type[etype]:
                self.by_type[etype][k] = eid
                self.source[(etype, k)] = source

        for a in world.aliases:
            add(a.entity_type, a.alias, a.entity_id, "alias")
        for p in world.plants.values():
            add("plant", p.plant_id, p.plant_id, "exact")
            add("plant", p.name, p.plant_id, "name")
            add("plant", p.city, p.plant_id, "name")
            add("plant", p.city.split(",")[0], p.plant_id, "name")
        for p in world.parts.values():
            add("part", p.part_id, p.part_id, "exact")
            add("part", p.name, p.part_id, "name")
        for s in world.suppliers.values():
            add("supplier", s.supplier_id, s.supplier_id, "exact")
            add("supplier", s.name, s.supplier_id, "name")
        for m in world.models:
            add("model", m, m, "exact")
        for sid in world.shipments:
            add("shipment", sid, sid, "exact")
        for lid in world.lots:
            add("lot", lid, lid, "exact")
        self._scan_re = {
            t: re.compile(
                r"(?<![a-z0-9])(" + "|".join(re.escape(k) for k in sorted(d, key=len, reverse=True)) + r")(?![a-z0-9])",
                re.I,
            )
            for t, d in self.by_type.items()
            if t in {"plant", "part", "supplier"}
        }

    def resolve(self, mention: str, etype: str) -> ResolutionStep:
        raw = mention.strip()
        table = self.by_type[etype]
        if m := _ID_PATTERNS.get(etype, re.compile("$^")).search(raw.upper()):
            if m[0] in table.values():
                return ResolutionStep(
                    mention=mention, entity_type=etype, candidates=[m[0]], chosen=m[0], method="exact"
                )
        key = _norm(raw)
        if key in table:
            return ResolutionStep(
                mention=mention,
                entity_type=etype,
                candidates=[table[key]],
                chosen=table[key],
                method=self.source[(etype, key)],
            )
        # longest alias/name contained in the mention ("the Texas plant today" -> "texas plant")
        contained = sorted(
            (k for k in table if k and re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", key)),
            key=len,
            reverse=True,
        )
        if contained:
            ids = list(dict.fromkeys(table[k] for k in contained))
            if len(ids) == 1 or len(contained[0]) > len(contained[1]):
                best = table[contained[0]]
                return ResolutionStep(
                    mention=mention,
                    entity_type=etype,
                    candidates=ids,
                    chosen=best,
                    method="alias",
                    note=f"contains {contained[0]!r}",
                )
        scored = process.extract(key, list(table), scorer=fuzz.WRatio, score_cutoff=82, limit=4)
        ids = list(dict.fromkeys(table[k] for k, _, _ in scored))
        if scored and len(ids) == 1:
            return ResolutionStep(
                mention=mention,
                entity_type=etype,
                candidates=ids,
                chosen=ids[0],
                method="fuzzy",
                note=f"score {scored[0][1]:.0f}",
            )
        if scored and scored[0][1] - (scored[1][1] if len(scored) > 1 else 0) >= 8:
            return ResolutionStep(
                mention=mention,
                entity_type=etype,
                candidates=ids,
                chosen=table[scored[0][0]],
                method="fuzzy",
                note=f"score {scored[0][1]:.0f}",
            )
        return ResolutionStep(mention=mention, entity_type=etype, candidates=ids, chosen=None, method="unresolved")

    def scan(self, text: str) -> dict[str, list[str]]:
        """Every plant/part/supplier/shipment/lot id that the text names, in order of appearance (cross-check)."""
        found: dict[str, list[str]] = defaultdict(list)
        for etype, rx in self._scan_re.items():
            for m in rx.finditer(text):
                eid = self.by_type[etype][_norm(m[1])]
                if eid not in found[etype]:
                    found[etype].append(eid)
        for etype in ("shipment", "lot", "plant", "supplier", "part"):
            for m in _ID_PATTERNS[etype].finditer(text.upper()):
                if m[0] in self.by_type[etype].values() and m[0] not in found[etype]:
                    found[etype].append(m[0])
        return dict(found)


@dataclass
class Resolved:
    spec: IncidentSpec
    needs_human: bool  # blocking ambiguity or confidence below the gate


CONFIDENCE_GATE = 0.7
TIEBREAK_MIN_CONFIDENCE = 0.9


def _date(
    world: World,
    mention: DateMention | None,
    *,
    field: str,
    steps: list[ResolutionStep],
    ambs: list[Ambiguity],
    penalties: list[float],
    direction: str = "future",
    required: bool = True,
) -> date | None:
    if mention is None or not mention.text.strip():
        if required:
            ambs.append(Ambiguity(field=field, issue="date missing", blocking=True))
        return None
    parsed = parse_date_phrase(mention.text, direction=direction)
    llm_iso: date | None = None
    if mention.iso:
        try:
            llm_iso = date.fromisoformat(mention.iso)
        except ValueError:
            llm_iso = None
    value, method, note = parsed.value, "exact", parsed.note
    if value is None and llm_iso is not None:
        ambs.append(
            Ambiguity(
                field=field,
                issue=f"code could not parse the date {mention.text!r} (model read it as {llm_iso}); the model does not decide dates",
                blocking=True,
            )
        )
        steps.append(
            ResolutionStep(
                mention=mention.text,
                entity_type="date",
                method="unresolved",
                note=f"model reading {llm_iso} not trusted",
            )
        )
        return None
    elif value is None:
        ambs.append(Ambiguity(field=field, issue=f"cannot interpret date {mention.text!r}", blocking=True))
        steps.append(ResolutionStep(mention=mention.text, entity_type="date", method="unresolved", note=note))
        return None
    elif llm_iso is not None and llm_iso != value:
        note += f"; model read it as {llm_iso}, code trusts its own rule"
        penalties.append(0.9)
        ambs.append(
            Ambiguity(
                field=field,
                issue=f"model and rule-based reading differ ({llm_iso} vs {value})",
                options=[str(value), str(llm_iso)],
            )
        )
    if parsed.weekday_mismatch:
        penalties.append(0.85)
        ambs.append(Ambiguity(field=field, issue=note, options=[str(value)]))
    if value is not None and not world.calendar.is_working_day(value):
        nxt = world.calendar.on_or_after(value)
        ambs.append(
            Ambiguity(
                field=field,
                issue=f"{value} is not a working day in the planning calendar",
                options=[str(nxt)] if nxt else [],
            )
        )
        penalties.append(0.9)
    steps.append(
        ResolutionStep(
            mention=mention.text,
            entity_type="date",
            candidates=[str(value)] if value else [],
            chosen=str(value) if value else None,
            method=method,
            note=note,
        )
    )
    return value


def build_incident(
    world: World,
    index: EntityIndex,
    raw: RawIncident,
    *,
    event_id: str,
    n: int,
    event_text: str,
    tiebreak=None,
) -> Resolved:
    """`tiebreak(etype, mention, event_text) -> (id | None, confidence, why)` is an optional closed-set language-model
    fallback used ONLY when the deterministic tables cannot resolve a mention. It can only pick from our own entities."""
    steps: list[ResolutionStep] = []
    ambs: list[Ambiguity] = []
    pen: list[float] = []
    mentions = {
        k: v
        for k, v in {
            "plant": raw.plant, "part": raw.part, "supplier": raw.supplier, "shipment": raw.shipment_id, "lot": raw.lot_id,
        }.items()
        if v
    }  # fmt: skip
    spec = IncidentSpec(
        incident_id=f"{event_id}#{n}",
        event_id=event_id,
        category=raw.category,
        confidence=raw.confidence,
        raw_mentions={k: v for k, v in mentions.items()},
        reason=raw.reason,
    )

    use_tiebreak = tiebreak is not None and raw.category not in {"noise", "unconfirmed"}  # nothing acts on those

    def ent(field: str, etype: str, mention: str | None) -> str | None:
        if not mention:
            return None
        step = index.resolve(mention, etype)
        if step.chosen is None and use_tiebreak and etype in {"plant", "part", "supplier"}:
            pick, conf, why = tiebreak(etype, mention, event_text)
            if pick is not None and conf >= TIEBREAK_MIN_CONFIDENCE:
                step = ResolutionStep(
                    mention=mention,
                    entity_type=etype,
                    candidates=[pick],
                    chosen=pick,
                    method="llm",
                    note=f"not in the alias tables; closed-set model pick at {conf:.2f}: {why}",
                )
                pen.append(0.85)
                ambs.append(
                    Ambiguity(
                        field=field,
                        issue=f"{mention!r} resolved to {pick} by the language model, not by the alias table",
                        options=[pick],
                    )
                )
        steps.append(step)
        if step.chosen is None:
            ambs.append(
                Ambiguity(field=field, issue=f"cannot resolve {mention!r}", options=step.candidates, blocking=True)
            )
        elif step.method == "fuzzy":
            pen.append(0.9)
        if step.chosen and len(step.candidates) > 1 and step.method not in {"exact"}:
            ambs.append(
                Ambiguity(field=field, issue=f"{mention!r} could also mean {step.candidates}", options=step.candidates)
            )
            pen.append(0.9)
        return step.chosen

    if raw.category in {"noise", "unconfirmed"}:
        # Nothing to act on. Record what could be resolved so the trace shows why it was not actionable.
        spec.plant_id = ent("plant_id", "plant", raw.plant) if raw.plant else None
        spec.part_id = ent("part_id", "part", raw.part) if raw.part else None
        has_date = any(
            getattr(raw, f) is not None
            for f in ("original_eta", "new_eta", "outage_start", "outage_end", "build_window_start", "build_window_end")
        )
        if raw.category == "noise" and (raw.shipment_id or raw.lot_id or (raw.plant and has_date)):
            ambs.append(
                Ambiguity(
                    field="specificity",
                    issue="labelled noise but names a shipment, lot, or a plant with dates: a human should look",
                    blocking=True,
                )
            )
            steps.append(
                ResolutionStep(
                    mention=raw.evidence,
                    entity_type="note",
                    method="unresolved",
                    note="noise guard: specific record named",
                )
            )
            spec.resolution_steps, spec.ambiguities = steps, ambs
            return Resolved(spec=spec, needs_human=True)
        if raw.category == "unconfirmed":
            for field, val in (("part_id", raw.part), ("supplier_id", raw.supplier)):
                if val and getattr(spec, field) is None:
                    ambs.append(
                        Ambiguity(field=field, issue="named only vaguely; not a specific record", blocking=True)
                    )
            ambs.append(
                Ambiguity(field="specificity", issue="no confirmed shipment, lot, plant or dates", blocking=True)
            )
        spec.resolution_steps, spec.ambiguities = steps, ambs
        return Resolved(spec=spec, needs_human=raw.category == "unconfirmed")

    spec.plant_id = ent("plant_id", "plant", raw.plant)
    spec.part_id = ent("part_id", "part", raw.part)
    spec.supplier_id = ent("supplier_id", "supplier", raw.supplier)
    spec.shipment_id = ent("shipment_id", "shipment", raw.shipment_id)
    spec.lot_id = ent("lot_id", "lot", raw.lot_id)

    if raw.category in {"supplier_delay", "plant_outage", "quality_hold"}:
        seen = index.scan(event_text)
        for field, etype in (("plant_id", "plant"), ("part_id", "part"), ("supplier_id", "supplier")):
            named = seen.get(etype, [])
            needed = field == "plant_id" or (field == "part_id" and raw.category != "plant_outage")
            if (
                getattr(spec, field) is None
                and needed
                and len(named) == 1
                and not any(a.field == field and a.blocking and "ambig" in a.issue for a in ambs)
            ):
                setattr(spec, field, named[0])
                steps.append(
                    ResolutionStep(
                        mention=f"(not extracted) text names {named[0]}",
                        entity_type=etype,
                        candidates=named,
                        chosen=named[0],
                        method="alias",
                        note="the model left it blank but the message names exactly one",
                    )
                )
                pen.append(0.9)
                ambs = [a for a in ambs if not (a.field == field and a.blocking)]

    if raw.category == "supplier_delay":
        spec.orig_eta = _date(world, raw.original_eta, field="orig_eta", steps=steps, ambs=ambs, penalties=pen)
        spec.new_eta = _date(world, raw.new_eta, field="new_eta", steps=steps, ambs=ambs, penalties=pen)
        sh = world.shipments.get(spec.shipment_id) if spec.shipment_id else None
        if sh:  # the shipment row is authoritative for plant, part, supplier and the original ETA
            for field, have, want in (
                ("plant_id", spec.plant_id, sh.plant_id),
                ("part_id", spec.part_id, sh.part_id),
                ("supplier_id", spec.supplier_id, sh.supplier_id),
            ):
                if have and have != want:
                    ambs.append(
                        Ambiguity(
                            field=field,
                            issue=f"text says {have} but {sh.shipment_id} is {want}",
                            options=[have, want],
                            blocking=True,
                        )
                    )
                setattr(spec, field, have or want)
            if spec.orig_eta and spec.orig_eta != sh.eta_date:
                ambs.append(
                    Ambiguity(
                        field="orig_eta",
                        issue=f"text says {spec.orig_eta} but {sh.shipment_id} is due {sh.eta_date}",
                        options=[str(spec.orig_eta), str(sh.eta_date)],
                        blocking=True,
                    )
                )
            spec.orig_eta = spec.orig_eta or sh.eta_date
            steps.append(
                ResolutionStep(
                    mention=sh.shipment_id,
                    entity_type="shipment",
                    candidates=[sh.shipment_id],
                    chosen=sh.shipment_id,
                    method="data_snap",
                    note="shipment row confirms plant, part, supplier and original ETA",
                )
            )
        elif spec.plant_id and spec.part_id and spec.orig_eta:
            match = [
                s
                for s in world.shipments.values()
                if s.plant_id == spec.plant_id and s.part_id == spec.part_id and s.eta_date == spec.orig_eta
            ]
            if len(match) == 1:
                spec.shipment_id = match[0].shipment_id
                if spec.supplier_id and spec.supplier_id != match[0].supplier_id:
                    ambs.append(
                        Ambiguity(
                            field="supplier_id",
                            issue=f"text names {spec.supplier_id} but {match[0].shipment_id} is from {match[0].supplier_id}",
                            options=[spec.supplier_id, match[0].supplier_id],
                            blocking=True,
                        )
                    )
                spec.supplier_id = spec.supplier_id or match[0].supplier_id
                steps.append(
                    ResolutionStep(
                        mention=f"{spec.part_id}→{spec.plant_id} due {spec.orig_eta}",
                        entity_type="shipment",
                        candidates=[match[0].shipment_id],
                        chosen=match[0].shipment_id,
                        method="data_snap",
                        note="exactly one shipment matches plant, part and original ETA",
                    )
                )
            elif not match:
                nearby = sorted(
                    (s for s in world.shipments.values() if s.plant_id == spec.plant_id and s.part_id == spec.part_id),
                    key=lambda s: s.eta_date,
                )
                ambs.append(
                    Ambiguity(
                        field="orig_eta",
                        issue=f"no shipment of {spec.part_id} to {spec.plant_id} is due on {spec.orig_eta}",
                        options=[f"{s.shipment_id} {s.eta_date}" for s in nearby[:4]],
                        blocking=True,
                    )
                )
        for field in ("plant_id", "part_id", "orig_eta", "new_eta"):
            if getattr(spec, field) is None and not any(a.field == field for a in ambs):
                ambs.append(Ambiguity(field=field, issue="required for a supplier delay", blocking=True))
        if spec.orig_eta and spec.new_eta and spec.new_eta <= spec.orig_eta:
            ambs.append(Ambiguity(field="new_eta", issue="new ETA is not later than the original ETA", blocking=True))
    elif raw.category == "plant_outage":
        spec.outage_start = _date(world, raw.outage_start, field="outage_start", steps=steps, ambs=ambs, penalties=pen)
        spec.outage_end = _date(world, raw.outage_end, field="outage_end", steps=steps, ambs=ambs, penalties=pen)
        if spec.plant_id is None and not any(a.field == "plant_id" for a in ambs):
            ambs.append(Ambiguity(field="plant_id", issue="plant required for an outage", blocking=True))
        if spec.outage_start and spec.outage_end and spec.outage_end < spec.outage_start:
            ambs.append(Ambiguity(field="outage_end", issue="outage ends before it starts", blocking=True))
    elif raw.category == "quality_hold":
        spec.build_window_start = _date(
            world,
            raw.build_window_start,
            field="build_window_start",
            steps=steps,
            ambs=ambs,
            penalties=pen,
            direction="past",
            required=not raw.lot_id,
        )
        spec.build_window_end = _date(
            world,
            raw.build_window_end,
            field="build_window_end",
            steps=steps,
            ambs=ambs,
            penalties=pen,
            direction="past",
            required=not raw.lot_id,
        )
        lot = world.lots.get(spec.lot_id) if spec.lot_id else None
        if lot is None and spec.part_id and spec.plant_id:
            lots = find_lots(
                world,
                part_id=spec.part_id,
                plant_id=spec.plant_id,
                first=spec.build_window_start,
                last=spec.build_window_end,
            )
            if len(lots) == 1:
                lot = lots[0]
                spec.lot_id = lot.lot_id
                exact = lot.first_build_date == spec.build_window_start and lot.last_build_date == spec.build_window_end
                steps.append(
                    ResolutionStep(
                        mention=f"{spec.part_id} at {spec.plant_id} built {spec.build_window_start}..{spec.build_window_end}",
                        entity_type="lot",
                        candidates=[lot.lot_id],
                        chosen=lot.lot_id,
                        method="data_snap",
                        note="exact lot window match" if exact else "only overlapping lot",
                    )
                )
                if not exact:
                    pen.append(0.85)
                    ambs.append(
                        Ambiguity(
                            field="lot_id",
                            issue="stated window differs from the lot's own build dates; lot dates are used (rule 6)",
                            options=[lot.lot_id],
                        )
                    )
            elif len(lots) > 1:
                ambs.append(
                    Ambiguity(
                        field="lot_id",
                        issue="the stated window overlaps several lots",
                        options=[f"{x.lot_id} {x.first_build_date}..{x.last_build_date}" for x in lots],
                        blocking=True,
                    )
                )
            else:
                ambs.append(
                    Ambiguity(field="lot_id", issue="no lot matches this part, plant and window", blocking=True)
                )
        elif lot is None:
            ambs.append(
                Ambiguity(
                    field="lot_id", issue="need a lot id, or a part and a plant, to identify the lot", blocking=True
                )
            )
        if lot is not None:
            spec.plant_id = spec.plant_id or lot.plant_id
            spec.part_id = spec.part_id or lot.part_id
            if spec.plant_id != lot.plant_id or spec.part_id != lot.part_id:
                ambs.append(
                    Ambiguity(
                        field="lot_id",
                        issue=f"{lot.lot_id} is {lot.part_id} at {lot.plant_id}, text says {spec.part_id} at {spec.plant_id}",
                        blocking=True,
                    )
                )
            if spec.supplier_id and spec.supplier_id != lot.supplier_id:
                ambs.append(
                    Ambiguity(
                        field="supplier_id",
                        issue=f"text names {spec.supplier_id} but {lot.lot_id} is from {lot.supplier_id}",
                        options=[spec.supplier_id, lot.supplier_id],
                        blocking=True,
                    )
                )
            spec.supplier_id = spec.supplier_id or lot.supplier_id

    # a mention the tables did not know is harmless when the data identifies the same field (shipment / lot row)
    for field in ("plant_id", "part_id", "supplier_id"):
        if getattr(spec, field) is not None:
            derived = [a for a in ambs if a.field == field and a.blocking and a.issue.startswith("cannot resolve")]
            if derived:
                ambs = [a for a in ambs if a not in derived]
                ambs.append(
                    Ambiguity(
                        field=field,
                        issue=f"{derived[0].issue.split('cannot resolve ')[1]} not recognised; value taken from the matching shipment/lot",
                    )
                )
                pen.append(0.9)

    # a lot id supplied by the model must be named in the text or match the stated build window
    if raw.category == "quality_hold" and spec.lot_id and spec.lot_id in world.lots:
        named_lots = index.scan(event_text).get("lot", [])
        lot_ = world.lots[spec.lot_id]
        w0, w1 = spec.build_window_start, spec.build_window_end
        if spec.lot_id not in named_lots and w0 and w1 and (lot_.first_build_date, lot_.last_build_date) != (w0, w1):
            ambs.append(
                Ambiguity(
                    field="lot_id",
                    issue=f"{spec.lot_id} is not named in the message and its window {lot_.first_build_date}..{lot_.last_build_date} differs from the stated {w0}..{w1}",
                    blocking=True,
                )
            )

    # cross-check: ids the text itself names but the LLM did not use
    seen = index.scan(event_text)
    for etype, field in (("shipment", "shipment_id"), ("lot", "lot_id")):
        named = seen.get(etype, [])
        if len(named) == 1 and getattr(spec, field) not in (None, named[0]):
            ambs.append(
                Ambiguity(
                    field=field,
                    issue=f"text names {named[0]} but extraction resolved {getattr(spec, field)}",
                    options=named,
                    blocking=True,
                )
            )

    conf = spec.confidence
    for p in pen:
        conf *= p
    blocking = any(a.blocking for a in ambs)
    if blocking:
        conf = min(conf, 0.4)
    spec.confidence = round(conf, 3)
    spec.resolution_steps, spec.ambiguities = steps, ambs
    return Resolved(spec=spec, needs_human=blocking or conf < CONFIDENCE_GATE)
