"""Tests for engine/capture.py — landing-page lead submission (audit 2026-09-27).

This is the public, unauthenticated write path (POST /api/capture/lead), so the
tests pin the things that would corrupt a customer's lead table if they broke:
validation order and messages, name/email/phone normalisation, the address ->
location derivation, the 300-char snippet cap, the row written to the leads
table, and the fact that a routing/persistence failure never loses a lead or
lies to the caller.

`LeadCaptureProcessor` takes an `engine` duck-type, so the fixtures below build a
minimal stand-in (a dict of leads plus a SmartRouter) rather than importing main.
The database is redirected to a temp file per test.
"""
import asyncio
import logging
import sqlite3

import pytest

import engine.capture as capture
from engine.capture import (
    LeadCaptureProcessor,
    _CaptureLead,
    _extract_location,
    _SimpleScore,
    _truncate,
)
from engine.database import Database
from engine.router import SmartRouter


class _FakeEngine:
    """The duck-type LeadCaptureProcessor actually uses: _leads and _router."""

    def __init__(self, router=None):
        self._leads = {}
        self._router = router


@pytest.fixture
def db(tmp_path):
    """An isolated, initialized database; restores the suite DB afterwards."""
    original = Database.db_file
    Database.set_db_file(str(tmp_path / "capture.db"))
    Database.initialize()
    try:
        yield Database.db_file
    finally:
        Database.set_db_file(original)


@pytest.fixture
def proc(db):
    return LeadCaptureProcessor(_FakeEngine())


def _row(db_path, lead_id):
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()


# ── _extract_location ───────────────────────────────────────────────────────
def test_extract_location_of_empty_address_is_empty():
    assert _extract_location("") == ""


def test_extract_location_takes_the_last_line_of_a_multi_line_address():
    assert _extract_location("123 Main St\nAustin, TX 78701") == "Austin, TX 78701"


def test_extract_location_ignores_blank_lines():
    assert _extract_location("123 Main St\n\nAustin, TX 78701\n") == "Austin, TX 78701"


def test_extract_location_takes_the_text_after_the_last_comma():
    assert _extract_location("123 Main St, Austin, TX") == "TX"


def test_extract_location_returns_the_address_itself_when_there_is_nothing_to_parse():
    assert _extract_location("Austin TX") == "Austin TX"


# ── _truncate ───────────────────────────────────────────────────────────────
def test_truncate_of_empty_is_empty():
    assert _truncate("") == ""


def test_truncate_passes_through_anything_at_or_below_the_limit():
    assert _truncate("abc", 300) == "abc"
    assert _truncate("z" * 300) == "z" * 300


def test_truncate_cuts_to_exactly_max_len_including_the_ellipsis():
    out = _truncate("z" * 301)
    assert len(out) == 300
    assert out.endswith("...")


def test_truncate_strips_trailing_whitespace_before_appending_the_ellipsis():
    out = _truncate("a" * 296 + " " * 20)
    assert out == "a" * 296 + "..."  # not "a"*296 + "     ..."
    assert len(out) == 299


def test_truncate_honours_a_custom_max_len():
    assert _truncate("abcdefghij", 8) == "abcde..."


# ── _SimpleScore / _CaptureLead ─────────────────────────────────────────────
def test_simple_score_defaults_every_dimension_to_50():
    assert _SimpleScore().as_dict() == {
        "total": 50.0, "contact_completeness": 50.0, "business_presence": 50.0,
        "industry_relevance": 50.0, "location_match": 50.0, "enrichment_potential": 50.0,
    }


def test_simple_score_rounds_the_total_to_one_decimal():
    assert _SimpleScore(63.456).as_dict()["total"] == 63.5


def test_capture_lead_requires_id_and_title():
    with pytest.raises(KeyError, match="id"):
        _CaptureLead({"title": "No id"})


def test_capture_lead_fills_optional_fields_with_the_documented_defaults():
    lead = _CaptureLead({"id": "x", "title": "T"})
    assert lead.url == "" and lead.snippet == ""
    assert lead.industry == "home improvement"
    assert lead.source == "landing_page"
    assert lead.status == "new"
    assert lead.score.total == 50.0


def test_capture_lead_score_can_be_overridden_by_a_plain_number():
    assert _CaptureLead({"id": "x", "title": "T", "score": 77.0}).as_dict()["score"] == 77.0


def test_capture_lead_prefers_an_explicit_score_object_over_the_plain_number():
    """`_score_obj` wins, so a caller can pass a real LeadScore and have its
    sub-dimensions flow into the breakdown."""
    lead = _CaptureLead({"id": "x", "title": "T", "score": 1.0,
                         "_score_obj": _SimpleScore(9.0)})
    d = lead.as_dict()
    assert d["score"] == 9.0
    assert d["contact_score"] == 50.0


def test_capture_lead_as_dict_truncates_the_snippet_to_300():
    assert len(_CaptureLead({"id": "x", "title": "T", "snippet": "y" * 400}).as_dict()["snippet"]) == 300


def test_capture_lead_as_dict_carries_the_capture_source():
    lead = _CaptureLead({"id": "x", "title": "T"})
    lead._capture_source = "pg-1"
    assert lead.as_dict()["_capture_source"] == "pg-1"
    # Absent the attribute it is an empty string, never an AttributeError.
    assert _CaptureLead({"id": "y", "title": "T"}).as_dict()["_capture_source"] == ""


# ── validation ──────────────────────────────────────────────────────────────
def test_missing_name_is_rejected(proc):
    assert proc.process_submission({}) == {"ok": False, "error": "Name is required"}


def test_whitespace_only_name_is_rejected(proc):
    assert proc.process_submission({"name": "   \n "})["error"] == "Name is required"
    assert proc.process_submission({"name": None})["error"] == "Name is required"


def test_name_is_required_but_email_and_phone_are_not(proc):
    r = proc.process_submission({"name": "Jane Doe"})
    assert r["ok"] is True
    assert r["score"] == 50.0


def test_invalid_email_is_rejected(proc):
    for bad in ["not-an-email", "a@b", "@example.com", "jane@.com"]:
        r = proc.process_submission({"name": "Jane", "email": bad})
        assert r == {"ok": False, "error": "Invalid email format"}, bad


def test_valid_email_forms_are_accepted(proc):
    for good in ["jane@acme.com", "jane.doe+tag@sub.acme.co.uk", "jane_doe@acme.museum"]:
        assert proc.process_submission({"name": "Jane", "email": good})["ok"] is True, good


def test_phone_with_fewer_than_ten_digits_is_rejected(proc):
    r = proc.process_submission({"name": "Jane", "phone": "512-555-123"})
    assert r == {"ok": False, "error": "Phone number must have at least 10 digits"}


def test_phone_is_counted_in_digits_not_characters(proc):
    """Punctuation must not count toward the 10-digit floor, and extra digits
    must not be rejected."""
    # Nine digits spread over 17 characters is still too few.
    assert proc.process_submission(
        {"name": "J", "phone": "1-2-3-4-5-6-7-8-9"}
    )["error"] == "Phone number must have at least 10 digits"
    assert proc.process_submission({"name": "J", "phone": "512-555-1234"})["ok"] is True
    assert proc.process_submission({"name": "J", "phone": "+1 (512) 555-1234 x99"})["ok"] is True


def test_validation_runs_in_order_name_then_email_then_phone(proc):
    """A submission that is wrong in every way reports the first failure, so the
    form shows one error at a time instead of a pile."""
    assert proc.process_submission({"name": "", "email": "bad", "phone": "1"})["error"] == "Name is required"
    assert proc.process_submission({"name": "J", "email": "bad", "phone": "1"})["error"] == "Invalid email format"


def test_a_rejected_submission_writes_nothing(proc, db):
    proc.process_submission({"name": "  ", "email": "jane@acme.com"})
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0


# ── normalisation ───────────────────────────────────────────────────────────
def test_submission_is_title_cased_into_title_and_first_last_name(proc):
    r = proc.process_submission({"name": "  jane DOE  "})
    lead = proc._engine._leads[r["lead_id"]]
    assert lead.title == "Jane Doe"
    assert lead.first_name == "Jane"
    assert lead.last_name == "Doe"


def test_a_single_word_name_leaves_last_name_empty(proc):
    lead = proc._engine._leads[proc.process_submission({"name": "cher"})["lead_id"]]
    assert lead.title == "Cher"
    assert lead.first_name == "Cher"
    assert lead.last_name == ""


def test_email_is_lowercased_and_whitespace_trimmed(proc):
    lead = proc._engine._leads[proc.process_submission(
        {"name": "J", "email": "  Jane.DOE@Acme.COM  "})["lead_id"]]
    assert lead.email == "jane.doe@acme.com"


def test_whitespace_around_phone_address_and_description_is_trimmed(proc):
    lead = proc._engine._leads[proc.process_submission({
        "name": "J", "phone": "  512-555-1234 ",
        "address": "  123 Main St  ",
        "project_description": "  Need a roof  ",
    })["lead_id"]]
    assert lead.phone == "512-555-1234"
    assert lead.address == "123 Main St"
    assert lead.project_description == "Need a roof"


def test_location_is_derived_from_the_address_tail(proc):
    lead = proc._engine._leads[proc.process_submission(
        {"name": "J", "address": "123 Main St, Austin, TX"})["lead_id"]]
    assert lead.location == "TX"


def test_location_is_empty_when_no_address_was_given(proc):
    assert proc._engine._leads[proc.process_submission({"name": "J"})["lead_id"]].location == ""


def test_utm_parameters_are_carried_through_verbatim(proc):
    lead = proc._engine._leads[proc.process_submission({
        "name": "J", "utm_source": "google", "utm_medium": "cpc", "utm_campaign": "q3-roofs",
    })["lead_id"]]
    assert (lead.utm_source, lead.utm_medium, lead.utm_campaign) == ("google", "cpc", "q3-roofs")


def test_missing_utm_parameters_default_to_empty_strings(proc):
    lead = proc._engine._leads[proc.process_submission({"name": "J"})["lead_id"]]
    assert (lead.utm_source, lead.utm_medium, lead.utm_campaign) == ("", "", "")


def test_long_project_description_is_truncated_in_the_snippet_only(proc):
    description = "Need a new " + "roof " * 100
    lead = proc._engine._leads[proc.process_submission(
        {"name": "J", "project_description": description})["lead_id"]]
    assert len(lead.snippet) == 300
    # The full text is still kept in the dedicated column, minus the trailing
    # whitespace that `.strip()` in process_submission removes.
    assert lead.project_description == description.strip()
    assert lead.notes == description.strip()


def test_captured_lead_is_typed_as_a_landing_page_lead_at_score_50(proc):
    r = proc.process_submission({"name": "J"})
    d = proc._engine._leads[r["lead_id"]].as_dict()
    assert d["source"] == "landing_page"
    assert d["status"] == "new"
    assert d["score"] == 50.0
    assert d["url"] == ""


def test_industry_always_resolves_to_home_improvement(proc):
    lead = proc._engine._leads[proc.process_submission(
        {"name": "J"}, source_page_id="pg-1")["lead_id"]]
    assert lead.industry == "home improvement"


def test_every_submission_gets_a_distinct_hex_id(proc):
    ids = {proc.process_submission({"name": f"Lead {i}"})["lead_id"] for i in range(20)}
    assert len(ids) == 20
    assert all(len(i) == 12 and all(c in "0123456789abcdef" for c in i) for i in ids), ids


def test_found_at_is_an_iso_timestamp(proc):
    from datetime import datetime

    lead = proc._engine._leads[proc.process_submission({"name": "J"})["lead_id"]]
    assert datetime.fromisoformat(lead.found_at)


# ── persistence ─────────────────────────────────────────────────────────────
def test_captured_lead_is_written_to_the_leads_table(proc, db):
    r = proc.process_submission({
        "name": "jane doe", "email": "JANE@Acme.com", "phone": "512-555-1234",
        "address": "123 Main St, Austin, TX", "project_description": "Need a roof",
        "utm_source": "google",
    })
    row = _row(db, r["lead_id"])
    assert row["id"] == r["lead_id"]
    assert row["title"] == "Jane Doe"
    assert row["first_name"] == "Jane"
    assert row["last_name"] == "Doe"
    assert row["email"] == "jane@acme.com"
    assert row["phone"] == "512-555-1234"
    # The address is stored whole; only the `location` column is derived from it.
    assert row["address"] == "123 Main St, Austin, TX"
    assert row["location"] == "TX"
    assert row["project_description"] == "Need a roof"
    assert row["notes"] == "Need a roof"
    assert row["snippet"] == "Need a roof"
    assert row["url"] == ""
    assert row["industry"] == "home improvement"
    assert row["source"] == "landing_page"
    assert row["status"] == "new"
    assert row["score"] == 50.0
    assert row["utm_source"] == "google"


def test_the_persisted_score_breakdown_is_valid_json(proc, db):
    import json

    r = proc.process_submission({"name": "J"})
    breakdown = json.loads(_row(db, r["lead_id"])["score_breakdown"])
    assert breakdown["total"] == 50.0
    assert breakdown["contact_completeness"] == 50.0


def test_persisted_snippet_is_capped_at_300_like_the_in_memory_lead(proc, db):
    r = proc.process_submission({"name": "J", "project_description": "x" * 500})
    assert len(_row(db, r["lead_id"])["snippet"]) == 300


def test_a_persistence_failure_still_returns_ok_and_keeps_the_lead_in_memory(proc, monkeypatch):
    """A full disk must not tell the visitor their enquiry was lost — the lead
    stays in the engine's registry, and the error is logged, not raised."""
    monkeypatch.setattr(
        Database, "get_connection",
        classmethod(lambda cls: (_ for _ in ()).throw(OSError("disk full"))),
    )
    r = proc.process_submission({"name": "Jane Doe"})
    assert r["ok"] is True
    assert r["lead_id"] in proc._engine._leads
    assert proc.get_submissions()[0]["title"] == "Jane Doe"


def test_a_persistence_failure_is_logged_as_an_error(proc, monkeypatch, caplog):
    monkeypatch.setattr(
        Database, "get_connection",
        classmethod(lambda cls: (_ for _ in ()).throw(OSError("disk full"))),
    )
    with caplog.at_level(logging.ERROR, logger="engine.capture"):
        proc.process_submission({"name": "Jane Doe"})
    assert "Failed to persist captured lead" in caplog.text


# ── routing ─────────────────────────────────────────────────────────────────
def test_no_router_at_all_is_logged_and_does_not_break_capture(proc, caplog):
    with caplog.at_level(logging.ERROR, logger="engine.capture"):
        r = proc.process_submission({"name": "Jane Doe"})
    assert r["ok"] is True
    assert "Lead routing error" in caplog.text


def test_a_router_with_every_step_disabled_never_calls_route_leads(db, monkeypatch):
    router = SmartRouter({"steps": [
        {"name": "dedup", "label": "d", "description": "x", "enabled": False, "config": {}}]})
    engine = _FakeEngine(router)
    proc = LeadCaptureProcessor(engine)
    monkeypatch.setattr(router, "route_leads", _boom("route_leads must not be called"))
    assert proc.process_submission({"name": "Jane Doe"})["ok"] is True
    assert router.get_routing_history() == []


def test_an_empty_router_does_not_route(db):
    router = SmartRouter({"steps": []})
    proc = LeadCaptureProcessor(_FakeEngine(router))
    assert proc.process_submission({"name": "Jane"})["ok"] is True
    assert router.get_routing_history() == []


async def test_an_enabled_step_actually_routes_the_new_lead(db):
    """Inside a running loop the processor schedules route_leads; the captured
    lead must reach the pipeline. Called directly (not via to_thread) because
    get_running_loop() is thread-local."""
    router = SmartRouter({"steps": [
        {"name": "dedup", "label": "d", "description": "x", "enabled": True, "config": {}}]})
    proc = LeadCaptureProcessor(_FakeEngine(router))
    r = proc.process_submission({"name": "Routed Lead"})
    await asyncio.sleep(0.05)  # let the scheduled task run
    history = router.get_routing_history()
    assert len(history) == 1, history
    assert history[0]["input_count"] == 1
    assert history[0]["steps_run"] == ["dedup"]
    assert r["ok"] is True


async def test_a_routing_failure_is_logged_and_does_not_lose_the_capture(db, caplog):
    class _Boom:
        _steps = {"s": type("S", (), {"enabled": True})()}

        async def route_leads(self, leads):
            raise RuntimeError("boom")

    proc = LeadCaptureProcessor(_FakeEngine(_Boom()))
    with caplog.at_level(logging.ERROR, logger="engine.capture"):
        r = proc.process_submission({"name": "Doomed Lead"})
        await asyncio.sleep(0.05)
    assert r["ok"] is True
    assert len(proc.get_submissions()) == 1
    assert "Routing task failed" in caplog.text


def test_routing_is_skipped_outside_a_running_event_loop(db):
    """`asyncio.get_running_loop()` raises RuntimeError outside a loop, and the
    except must swallow it — the capture still succeeds synchronously."""
    router = SmartRouter({"steps": [
        {"name": "dedup", "label": "d", "description": "x", "enabled": True, "config": {}}]})
    proc = LeadCaptureProcessor(_FakeEngine(router))
    assert proc.process_submission({"name": "Sync Lead"})["ok"] is True
    assert router.get_routing_history() == []


def test_routing_is_skipped_when_the_ambient_loop_is_not_running(db, monkeypatch):
    """The `loop.is_running()` guard is defensive: a loop object that exists but
    is not running must not get a task scheduled onto it. In practice the running
    loop always reports True, so this patches the loop to reach that branch."""
    router = SmartRouter({"steps": [
        {"name": "dedup", "label": "d", "description": "x", "enabled": True, "config": {}}]})
    proc = LeadCaptureProcessor(_FakeEngine(router))
    idle = asyncio.new_event_loop()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: idle)
    try:
        assert proc.process_submission({"name": "Idle Loop Lead"})["ok"] is True
    finally:
        idle.close()
    assert router.get_routing_history() == []


def _boom(message):
    async def _raise(*a, **k):
        raise AssertionError(message)

    return _raise


# ── get_submissions / get_submission_stats ───────────────────────────────────
def test_get_submissions_is_empty_before_anything_is_captured(proc):
    assert proc.get_submissions() == []
    assert proc.get_submission_stats() == {
        "total": 0, "avg_score": 0, "max_score": 0, "min_score": 0
    }


def test_get_submissions_only_returns_landing_page_leads(proc):
    engine = proc._engine
    engine._leads["a"] = type("L", (), {"source": "landing_page", "as_dict": lambda s: {"id": "a"}})()
    engine._leads["b"] = type("L", (), {"source": "exa", "as_dict": lambda s: {"id": "b"}})()
    engine._leads["c"] = "not even a lead"
    assert proc.get_submissions() == [{"id": "a"}]


def test_get_submissions_returns_a_plain_dict_unchanged_when_the_lead_has_no_as_dict(proc):
    proc._engine._leads["a"] = type("L", (), {"source": "landing_page"})()
    assert proc.get_submissions() == [proc._engine._leads["a"]]


def test_get_submissions_respects_the_limit(proc):
    for i in range(5):
        proc.process_submission({"name": f"Lead {i}"})
    assert len(proc.get_submissions(limit=2)) == 2
    assert len(proc.get_submissions()) == 5


def test_submission_stats_average_max_and_min_scores(proc):
    for name in ["A", "B", "C"]:
        proc.process_submission({"name": name})
    stats = proc.get_submission_stats()
    assert stats == {"total": 3, "avg_score": 50.0, "max_score": 50.0, "min_score": 50.0}


def test_submission_stats_reads_the_score_key_and_defaults_to_50(proc):
    """A stored lead whose dict has no "score" must not make the stats blow up."""
    proc._engine._leads["a"] = type("L", (), {"source": "landing_page", "as_dict": lambda s: {"id": "a"}})()
    assert proc.get_submission_stats() == {
        "total": 1, "avg_score": 50.0, "max_score": 50.0, "min_score": 50.0
    }


def test_submission_stats_rounds_a_fractional_average_to_one_decimal(proc):
    """Two captured leads plus one hand-built lead at 60 -> (50+50+60)/3 = 53.33."""
    for name in ["A", "B"]:
        proc.process_submission({"name": name})
    proc._engine._leads["z"] = type("L", (), {
        "source": "landing_page", "as_dict": lambda s: {"id": "z", "score": 60}})()
    assert proc.get_submission_stats() == {
        "total": 3, "avg_score": 53.3, "max_score": 60.0, "min_score": 50.0
    }


# ── _resolve_industry ───────────────────────────────────────────────────────
def test_resolve_industry_with_no_page_id_is_the_default(db):
    assert LeadCaptureProcessor(_FakeEngine())._resolve_industry("") == "home improvement"


def test_resolve_industry_is_the_default_for_known_and_unknown_pages_alike(db):
    proc = LeadCaptureProcessor(_FakeEngine(), landing_pages={"pg-1": {}})
    assert proc._resolve_industry("pg-1") == "home improvement"
    assert proc._resolve_industry("unknown") == "home improvement"


def test_a_missing_landing_pages_mapping_becomes_an_empty_dict(db):
    assert LeadCaptureProcessor(_FakeEngine(), landing_pages=None)._landing_pages == {}


def test_resolve_industry_swallows_a_hostile_page_mapping(db):
    """The `try/except` around the lookup must not turn a broken registry into a
    500 on the public capture endpoint."""
    class _Hostile(dict):
        def __contains__(self, key):
            raise RuntimeError("registry exploded")

    proc = LeadCaptureProcessor(_FakeEngine(), landing_pages=_Hostile({"pg-1": {}}))
    assert proc._resolve_industry("pg-1") == "home improvement"
    assert proc.process_submission({"name": "J"}, source_page_id="pg-1")["ok"] is True


def test_capture_source_is_lost_because_the_lead_never_reads_it(db):
    """BUG (pinned, not endorsed): process_submission puts "_capture_source" in
    lead_data, but _CaptureLead.__init__ never assigns it, so as_dict()'s
    `getattr(self, "_capture_source", "")` always falls back to "". Every captured
    lead therefore reports no originating landing page, and the /api/capture/stats
    and export views cannot attribute a conversion to the page that produced it.
    Fix: `self._capture_source = data.get("_capture_source", "")` in __init__."""
    proc = LeadCaptureProcessor(_FakeEngine())
    r = proc.process_submission({"name": "J"}, source_page_id="pg-1")
    assert proc._engine._leads[r["lead_id"]].as_dict()["_capture_source"] == ""


def test_capture_source_is_empty_without_a_page_id(db):
    proc = LeadCaptureProcessor(_FakeEngine())
    r = proc.process_submission({"name": "J"})
    assert proc._engine._leads[r["lead_id"]].as_dict()["_capture_source"] == ""


def test_module_exposes_the_email_and_phone_validators():
    """Guard the regexes themselves: the email anchor must reject a trailing
    newline, the phone counter must only see digits."""
    assert capture._EMAIL_RE.match("jane@acme.com")
    assert not capture._EMAIL_RE.match("jane@acme.com\nBcc: eve@evil.com")
    assert len(capture._PHONE_DIGITS_RE.findall("(512) 555-1234")) == 10
