# ruff: noqa: F811
"""PLAN_V2 section 4.1: one test per escalation circumstance (1..7) plus the must-not-escalate guard.

The scenarios (scripted fake LLM, real tools/validators/twin) live in test_coordinator.py; this module is the named,
auditable index of them, so a missing circumstance shows up as a missing test here. Each test also asserts the common
contract: one `escalate`, a reason that says what would make it actionable (or what failed), and no write that
belongs to the escalated incident.
"""

from __future__ import annotations

import pytest

from tests.unit import test_coordinator as tc
from tests.unit.test_coordinator import (  # noqa: F401  (fixtures are used by name)
    E01_RAW,
    UNCONFIRMED,
    T,
    esc,
    ev,
    register,
    rig,
    tool_results,
    writes,
)


def test_c1_unconfirmed_report_escalates(rig):
    rig.script([
        register(UNCONFIRMED),
        T("escalate", {"incident_id": "E-02#1", "reason": "a rumor, no ids or dates",
                       "what_would_make_it_actionable": "the shipment or lot id, the plant and the dates"}),
        T("finish", {}),
    ])  # fmt: skip
    t = rig.run(ev("E-02", "Rumor: something may be off with a seat material."))
    assert t.status == "escalated" and len(esc(t)) == 1 and not writes(t)
    assert "make it actionable" in esc(t)[0].args["reason"].lower()


def test_c2_unresolved_entity_or_low_confidence_escalates(rig):
    tc.test_needs_human_incident_cannot_be_delegated(rig)


def test_c2b_low_confidence_escalates(rig):
    tc.test_low_confidence_escalates(rig)


def test_c3_noise_that_names_a_record_escalates(rig):
    tc.test_drop_noise_refused_when_a_shipment_is_named(rig)


def test_c3b_brochure_naming_a_city_stays_noise(rig):
    tc.test_brochure_that_mentions_a_city_stays_noise(rig)


def test_c4_plan_failing_validators_twice_escalates(rig):
    tc.test_two_failed_rounds_escalate(rig)


def test_c5a_failed_rehearsal_escalates_with_no_writes(rig, monkeypatch, twin):
    tc.test_rehearsal_failure_escalates_with_no_writes(rig, monkeypatch, twin)


def test_c5b_blocking_auditor_concern_escalates_with_no_writes(rig, monkeypatch):
    tc.test_auditor_blocking_concern_escalates_with_no_writes(rig, monkeypatch)


def test_c6a_failed_write_escalates_the_partial_completion(rig, world, graph):
    tc.test_failed_move_skips_dependents_and_escalates_once(rig, world, graph)


def test_c6b_unknown_outcome_stops_the_event_and_escalates(rig):
    tc.test_unknown_outcome_stops_the_whole_event(rig)


def test_c7_stale_server_world_escalates_before_any_write(rig):
    tc.test_stale_live_world_escalates_before_any_write(rig)


@pytest.mark.parametrize("plant", ["the Texas plant", "San Antonio"])
def test_must_not_escalate_a_nickname_for_a_plant(rig, plant):
    tc.test_nicknames_resolve_by_alias_and_are_not_escalated(rig, plant)


def test_must_not_escalate_nicknames_and_date_phrases_in_a_compound_event(rig):
    """Plant, part and supplier nicknames plus relative dates: every incident resolves and none needs a human."""
    rig.script([register(*E01_RAW), T("nonexistent_tool")])  # stop after registration; only the resolution matters
    t = rig.run(ev("E-01"))
    incs = tool_results(t, "register_incidents")[0]["incidents"]
    assert len(incs) == 2
    assert all(i["needs_human"] is False and i["actionable"] is True for i in incs)
