"""Resolver: relative dates, aliases, fuzzy matching and data snapping. Synthetic phrasings, offline, no LLM."""

from datetime import date

import pytest

from control_tower.understanding.resolve import CONFIDENCE_GATE, EntityIndex, build_incident, parse_date_phrase
from control_tower.understanding.schemas import DateMention, RawIncident


@pytest.fixture(scope="module")
def index(world):
    return EntityIndex(world)


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("next Monday", date(2027, 3, 15)),
        ("next Friday", date(2027, 3, 19)),  # next WEEK's Friday, not the coming one
        ("next Wednesday", date(2027, 3, 17)),
        ("last Monday", date(2027, 3, 1)),
        ("last Thursday", date(2027, 3, 4)),
        ("Thursday Feb 25", date(2027, 2, 25)),
        ("Monday, March 22", date(2027, 3, 22)),
        ("Apr 1", date(2027, 4, 1)),
        ("1st of April", date(2027, 4, 1)),
        ("2027-03-24", date(2027, 3, 24)),
        ("tomorrow", date(2027, 3, 9)),
    ],
)
def test_date_phrases(phrase, expected):
    assert parse_date_phrase(phrase).value == expected


def test_weekday_mismatch_is_flagged_not_silently_fixed():
    p = parse_date_phrase("Friday Mar 22")  # Mar 22 2027 is a Monday
    assert p.value == date(2027, 3, 22) and p.weekday_mismatch


def test_bare_weekday_direction():
    assert parse_date_phrase("Friday", direction="future").value == date(2027, 3, 12)
    assert parse_date_phrase("Friday", direction="past").value == date(2027, 3, 5)


def test_garbage_date_fails_cleanly():
    assert parse_date_phrase("sometime soon").value is None


@pytest.mark.parametrize(
    ("mention", "etype", "expected"),
    [
        ("the Texas plant", "plant", "P_TX"),
        ("our Huntsville line", "plant", "P_AL"),
        ("Wacky Wheels Lexington (P_KY)", "plant", "P_KY"),
        ("San Antonio", "plant", "P_TX"),
        ("heavy-duty wiring harness", "part", "HARN-B"),
        ("infotainment chips", "part", "CHIP-IVI"),
        ("60 kWh battery packs", "part", "BATT-60"),
        ("surround view cameras", "part", "CAM-360"),
        ("Quanta", "supplier", "SUP-12"),
        ("Orbit Optics", "supplier", "SUP-11"),
        ("SUP-07", "supplier", "SUP-07"),
    ],
)
def test_entity_resolution(index, mention, etype, expected):
    assert index.resolve(mention, etype).chosen == expected


def test_vague_part_stays_unresolved(index):
    step = index.resolve("some seat material", "part")
    assert step.chosen is None or step.method == "fuzzy"  # never silently exact on a vague phrase


def test_scan_finds_named_ids(index):
    found = index.scan("Shipment SH-0182 of CAM-360 for Princeton (P_IN) from Orbit")
    assert found["shipment"] == ["SH-0182"] and "P_IN" in found["plant"] and "CAM-360" in found["part"]
    assert "SUP-11" in found["supplier"]


def _delay(**kw):
    base = dict(
        category="supplier_delay",
        evidence="x",
        reason="r",
        confidence=0.95,
        plant="Princeton",
        part="surround-view cameras",
        supplier="Orbit",
        original_eta=DateMention(text="next Monday", iso="2027-03-15"),
        new_eta=DateMention(text="Thursday Mar 18", iso="2027-03-18"),
    )
    base.update(kw)
    return RawIncident(**base)


def test_delay_snaps_to_exactly_one_shipment(world, index):
    r = build_incident(world, index, _delay(), event_id="T-1", n=1, event_text="x")
    s = r.spec
    assert (s.plant_id, s.part_id, s.supplier_id, s.shipment_id) == ("P_IN", "CAM-360", "SUP-11", "SH-0182")
    assert (s.orig_eta, s.new_eta) == (date(2027, 3, 15), date(2027, 3, 18))
    assert not r.needs_human and s.confidence >= CONFIDENCE_GATE
    assert any(st.method == "data_snap" for st in s.resolution_steps)


def test_delay_with_wrong_supplier_is_blocked(world, index):
    r = build_incident(world, index, _delay(supplier="Atlas"), event_id="T-1", n=1, event_text="x")
    assert r.needs_human and any(a.field == "supplier_id" and a.blocking for a in r.spec.ambiguities)


def test_delay_with_date_that_matches_no_shipment_is_blocked(world, index):
    raw = _delay(original_eta=DateMention(text="Wednesday Mar 17", iso="2027-03-17"))
    r = build_incident(world, index, raw, event_id="T-1", n=1, event_text="x")
    assert r.needs_human and r.spec.shipment_id is None


def test_model_vs_rule_date_disagreement_trusts_the_rule_and_lowers_confidence(world, index):
    raw = _delay(original_eta=DateMention(text="next Monday", iso="2027-03-22"))
    r = build_incident(world, index, raw, event_id="T-1", n=1, event_text="x")
    assert r.spec.orig_eta == date(2027, 3, 15) and r.spec.confidence < 0.95
    assert any("differ" in a.issue for a in r.spec.ambiguities)


def test_outage_resolves_range(world, index):
    raw = RawIncident(
        category="plant_outage", evidence="x", reason="r", confidence=0.9, plant="the Kentucky plant",
        outage_start=DateMention(text="next Tuesday"), outage_end=DateMention(text="next Thursday"),
    )  # fmt: skip
    r = build_incident(world, index, raw, event_id="T-2", n=1, event_text="x")
    assert (r.spec.plant_id, r.spec.outage_start, r.spec.outage_end) == ("P_KY", date(2027, 3, 16), date(2027, 3, 18))
    assert not r.needs_human


def test_outage_without_plant_is_blocked(world, index):
    raw = RawIncident(
        category="plant_outage", evidence="x", reason="r", confidence=0.9,
        outage_start=DateMention(text="next Tuesday"), outage_end=DateMention(text="next Thursday"),
    )  # fmt: skip
    r = build_incident(world, index, raw, event_id="T-2", n=1, event_text="x")
    assert r.needs_human


def test_quality_hold_finds_the_lot_from_part_plant_window(world, index):
    raw = RawIncident(
        category="quality_hold", evidence="x", reason="r", confidence=0.9, plant="the Texas plant",
        part="heavy-duty wiring harness", supplier="Atlas",
        build_window_start=DateMention(text="Monday Feb 22"), build_window_end=DateMention(text="Wednesday Feb 24"),
    )  # fmt: skip
    r = build_incident(world, index, raw, event_id="T-3", n=1, event_text="x")
    assert r.spec.lot_id == "LOT-0017" and r.spec.supplier_id == "SUP-07" and not r.needs_human


def test_quality_hold_wrong_supplier_for_lot_is_blocked(world, index):
    raw = RawIncident(
        category="quality_hold", evidence="x", reason="r", confidence=0.9, plant="the Texas plant",
        part="heavy-duty wiring harness", supplier="Quanta",
        build_window_start=DateMention(text="Monday Feb 22"), build_window_end=DateMention(text="Wednesday Feb 24"),
    )  # fmt: skip
    assert build_incident(world, index, raw, event_id="T-3", n=1, event_text="x").needs_human


def test_quality_hold_with_lot_id_only(world, index):
    raw = RawIncident(category="quality_hold", evidence="x", reason="r", confidence=0.9, lot_id="LOT-0191")
    r = build_incident(world, index, raw, event_id="T-3", n=1, event_text="LOT-0191")
    assert r.spec.lot_id == "LOT-0191" and r.spec.plant_id == "P_IN" and not r.needs_human


def test_unconfirmed_always_needs_a_human(world, index):
    raw = RawIncident(category="unconfirmed", evidence="x", reason="r", confidence=0.9, part="seat material")
    r = build_incident(world, index, raw, event_id="T-4", n=1, event_text="x")
    assert r.needs_human and any(a.blocking for a in r.spec.ambiguities)
