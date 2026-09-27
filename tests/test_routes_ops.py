"""Route tests: /api/schedules*, /api/landing/*, /api/capture/*, /api/nurture/*,
/api/business/*, /api/simulator/*, /api/chat/collaborate, /api/crm/*, /api/trades
(schedule/trade read + conversion), and the three HTML pages.

No external service is contacted: SMS/email dispatch is not on any of these paths
(the nurture *loop* is what sends, and the client fixture never starts it).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

import main
from tests.routes_fixtures import *  # noqa: F401,F403 -- pytest fixtures


# ── /api/schedules ───────────────────────────────────────────────────────
def test_create_schedule_requires_a_query(client):
    r = client.post("/api/schedules", json={"name": "no query"})
    assert r.status_code == 400
    assert r.json()["error"] == "query is required"


def test_create_schedule_returns_the_full_record(client):
    r = client.post("/api/schedules", json={
        "query": "roofers in Austin", "name": "Austin Roofers",
        "interval_minutes": 30, "provider": "exa", "num_results": 5,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    s = d["schedule"]
    assert s["name"] == "Austin Roofers"
    assert s["query"] == "roofers in Austin"
    assert s["interval_minutes"] == 30
    assert s["num_results"] == 5
    assert s["enabled"] is True
    assert s["total_runs"] == 0
    assert s["last_run"] is None
    assert s["created_at"], "created_at must be populated"


def test_schedule_defaults_are_applied(client):
    r = client.post("/api/schedules", json={"query": "hvac in Denver"})
    s = r.json()["schedule"]
    assert s["name"] == "Untitled Scan"
    assert s["provider"] == "exa"
    assert s["num_results"] == 25
    assert s["min_score"] == 30.0
    assert s["interval_minutes"] == 60
    assert s["location"] == ""


def test_list_schedules_includes_what_was_created(client):
    r = client.post("/api/schedules", json={"query": "plumbers in Austin"})
    sid = r.json()["schedule"]["id"]
    d = client.get("/api/schedules").json()
    assert sid in [s["id"] for s in d["schedules"]]
    assert "total_schedules" in d["stats"]


def test_get_schedule_round_trips(client):
    sid = client.post("/api/schedules", json={"query": "wiring in Miami"}).json()["schedule"]["id"]
    r = client.get(f"/api/schedules/{sid}")
    assert r.status_code == 200
    assert r.json()["id"] == sid
    assert r.json()["query"] == "wiring in Miami"


def test_get_missing_schedule_is_404(client):
    r = client.get("/api/schedules/nope")
    assert r.status_code == 404
    assert r.json()["error"] == "Schedule not found"


def test_update_schedule_persists_the_change(client):
    sid = client.post("/api/schedules", json={"query": "x", "name": "before"}).json()["schedule"]["id"]
    r = client.put(f"/api/schedules/{sid}", json={"name": "after", "enabled": False})
    assert r.status_code == 200
    assert r.json()["schedule"]["name"] == "after"
    assert r.json()["schedule"]["enabled"] is False
    assert client.get(f"/api/schedules/{sid}").json()["name"] == "after"


def test_update_missing_schedule_is_404(client):
    r = client.put("/api/schedules/ghost", json={"name": "x"})
    assert r.status_code == 404
    assert r.json()["error"] == "Schedule not found"


def test_delete_schedule_removes_it(client):
    sid = client.post("/api/schedules", json={"query": "x"}).json()["schedule"]["id"]
    assert client.delete(f"/api/schedules/{sid}").json() == {"ok": True}
    assert client.get(f"/api/schedules/{sid}").status_code == 404


def test_delete_missing_schedule_is_404(client):
    r = client.delete("/api/schedules/ghost")
    assert r.status_code == 404


def test_schedule_results_are_empty_before_the_first_run(client):
    sid = client.post("/api/schedules", json={"query": "x"}).json()["schedule"]["id"]
    r = client.get(f"/api/schedules/{sid}/results")
    assert r.status_code == 200
    assert r.json() == {"schedule_id": sid, "leads": []}


def test_schedule_results_for_missing_schedule_is_404(client):
    r = client.get("/api/schedules/ghost/results")
    assert r.status_code == 404
    assert r.json()["error"] == "Schedule not found"


def test_schedules_require_auth(anon):
    assert anon.post("/api/schedules", json={"query": "x"}).status_code == 401


# ── /api/landing/* ───────────────────────────────────────────────────────
def test_landing_generate_requires_a_business_name(client):
    r = client.post("/api/landing/generate", json={"headline": "hi"})
    assert r.status_code == 400
    assert r.json()["error"] == "business_name is required"


def test_landing_generate_creates_a_servable_page(client):
    r = client.post("/api/landing/generate", json={"business_name": "Acme Roofing"})
    assert r.status_code == 200
    page = r.json()["page"]
    assert page["id"] and page["url"] == f"/api/landing/{page['id']}"
    assert page["html_preview"].startswith("<!DOCTYPE html>")

    # The page is real HTML served at its own URL, with the business name in it.
    page_r = client.get(page["url"])
    assert page_r.status_code == 200
    assert page_r.headers["content-type"].startswith("text/html")
    assert "Acme Roofing" in page_r.text


def test_landing_list_reports_the_created_pages(client):
    assert client.get("/api/landing/list").json()["count"] == 0
    client.post("/api/landing/generate", json={"business_name": "One Co"})
    client.post("/api/landing/generate", json={"business_name": "Two Co"})
    d = client.get("/api/landing/list").json()
    assert d["count"] == 2
    assert {p["id"] for p in d["pages"]} == set(main.landing_gen._pages)
    assert all("size" in p for p in d["pages"])


def test_get_missing_landing_page_is_404(client):
    r = client.get("/api/landing/zzzz")
    assert r.status_code == 404
    assert r.json()["error"] == "Landing page not found"


def test_delete_landing_page_removes_it(client):
    pid = client.post("/api/landing/generate", json={"business_name": "Temp"}).json()["page"]["id"]
    assert client.delete(f"/api/landing/{pid}").json() == {"ok": True}
    assert client.get(f"/api/landing/{pid}").status_code == 404
    assert pid not in main.landing_gen._pages


def test_delete_missing_landing_page_is_404(client):
    r = client.delete("/api/landing/zzzz")
    assert r.status_code == 404
    assert r.json()["error"] == "Landing page not found"


def test_landing_sanitises_a_javascript_injection_in_the_business_name(client):
    """The generator escapes the business name into the HTML; a <script> in the
    name must not reach the served page as a live tag."""
    pid = client.post("/api/landing/generate",
                      json={"business_name": "<script>alert(1)</script>Roofing"}
                      ).json()["page"]["id"]
    html = client.get(f"/api/landing/{pid}").text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html or "script" not in html.lower()


# ── /api/capture/* ───────────────────────────────────────────────────────
def test_capture_requires_a_name(client):
    r = client.post("/api/capture/lead", json={"email": "a@b.test"})
    assert r.status_code == 400
    assert r.json()["error"] == "Name is required"


def test_capture_rejects_a_malformed_email(client):
    r = client.post("/api/capture/lead", json={"name": "Bob", "email": "not-an-email"})
    assert r.status_code == 400
    assert r.json()["error"] == "Invalid email format"


def test_capture_rejects_a_short_phone_number(client):
    r = client.post("/api/capture/lead", json={"name": "Bob", "phone": "123"})
    assert r.status_code == 400
    assert r.json()["error"] == "Phone number must have at least 10 digits"


def test_capture_accepts_a_valid_submission_and_creates_the_lead(client):
    r = client.post("/api/capture/lead", json={
        "name": "bob smith", "email": "Bob@Example.COM", "phone": "512-555-1234",
        "address": "123 Main St, Austin, TX", "project_description": "Need a new roof",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] is True
    assert d["lead_id"] and d["score"] == 50.0

    lead = client.get(f"/api/leads/{d['lead_id']}").json()
    assert lead["title"] == "Bob Smith", "name must be normalised to title case"
    assert lead["email"] == "bob@example.com", "email must be lowercased"
    assert lead["phone"] == "512-555-1234"
    assert lead["source"] == "landing_page"
    # engine.capture._extract_location() takes the LAST comma component of a
    # single-line address, so "123 Main St, Austin, TX" yields "TX". Pinned as the
    # real contract -- it is coarse (the city is lost) but it is not a silent
    # failure, so it is not a bug to fix here.
    assert lead["location"] == "TX"
    assert lead["project_description"] == "Need a new roof"
    assert lead["status"] == "new"


def test_capture_records_utm_parameters(client):
    r = client.post("/api/capture/lead", json={
        "name": "Ana", "utm_source": "google", "utm_medium": "cpc",
        "utm_campaign": "spring",
    })
    lead = client.get(f"/api/leads/{r.json()['lead_id']}").json()
    assert lead["utm_source"] == "google"
    assert lead["utm_medium"] == "cpc"
    assert lead["utm_campaign"] == "spring"


def test_capture_source_page_id_is_stripped_from_the_payload(client):
    """main.capture_lead pops '_source_page_id' before handing the body to the
    processor; it must not end up as lead data."""
    pid = client.post("/api/landing/generate", json={"business_name": "Src Co"}).json()["page"]["id"]
    r = client.post("/api/capture/lead", json={
        "name": "Bo", "_source_page_id": pid,
    })
    assert r.status_code == 200
    lead = client.get(f"/api/leads/{r.json()['lead_id']}").json()
    assert "_source_page_id" not in lead
    assert "Src Co" not in str(lead.get("url", ""))


def test_capture_needs_no_auth(anon):
    """This is the public landing-page widget endpoint: it must accept anonymous
    submissions, because the form posts straight from a third-party site."""
    r = anon.post("/api/capture/lead", json={"name": "Anon Prospect"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True


def test_capture_creates_a_nurture_sequence(client):
    """After a successful capture the route must enrol the lead in nurture. A
    failure there is logged, not raised, so assert on the side effect."""
    before = client.get("/api/nurture/stats").json()["total_sequences"]
    r = client.post("/api/capture/lead", json={"name": "Nurture Me",
                                               "phone": "5125551234"})
    assert r.status_code == 200
    after = client.get("/api/nurture/stats").json()["total_sequences"]
    assert after == before + 1, "captured lead was not enrolled in nurture"


def test_capture_stats_track_submissions(client):
    d = client.get("/api/capture/stats").json()
    assert d == {"total": 0, "avg_score": 0, "max_score": 0, "min_score": 0}

    client.post("/api/capture/lead", json={"name": "One"})
    client.post("/api/capture/lead", json={"name": "Two"})
    d = client.get("/api/capture/stats").json()
    assert d["total"] == 2
    assert d["avg_score"] == 50.0
    assert d["max_score"] == 50.0


def test_capture_thank_you_page_renders(client):
    r = client.get("/api/capture/thank-you?name=Ana")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<html" in r.text.lower()


def test_capture_thank_you_fallback_when_no_template(client, monkeypatch, tmp_path):
    """With the template dir emptied the route must still serve a usable page."""
    monkeypatch.setattr(main, "TEMPLATES_DIR", tmp_path / "empty")
    r = client.get("/api/capture/thank-you?name=Ana")
    assert r.status_code == 200
    assert "Thank you, Ana!" in r.text


# ── /api/nurture/* ───────────────────────────────────────────────────────
def _make_sequence(client, name="Bob Smith"):
    r = client.post("/api/nurture/sequence", json={"lead": {
        "title": name, "email": f"{name.split()[0].lower()}@example.test",
        "phone": "5125551234",
    }})
    assert r.status_code == 200, r.text
    return r.json()["sequence"]


def test_nurture_sequence_accepts_a_nested_lead_object(client):
    seq = _make_sequence(client)
    assert seq["lead_name"] == "Bob Smith"
    assert seq["actions"], "a sequence must have actions queued"
    assert all("type" in a and "template" in a for a in seq["actions"])


def test_nurture_sequence_accepts_a_flat_body(client):
    """The route reads data.get("lead", data) -- a flat body is the documented
    fallback and must work."""
    r = client.post("/api/nurture/sequence", json={
        "title": "Flat Lead", "email": "flat@example.test", "phone": "5125550000"})
    assert r.status_code == 200
    assert r.json()["sequence"]["lead_name"] == "Flat Lead"


def test_nurture_get_sequence_round_trips(client):
    seq = _make_sequence(client)
    r = client.get(f"/api/nurture/sequences/{seq['id']}")
    assert r.status_code == 200
    assert r.json()["id"] == seq["id"]
    assert r.json()["lead_name"] == "Bob Smith"


def test_nurture_get_missing_sequence_is_404(client):
    r = client.get("/api/nurture/sequences/zzz")
    assert r.status_code == 404
    assert r.json()["error"] == "Sequence not found"


def test_nurture_list_sequences_includes_the_new_one(client):
    seq = _make_sequence(client)
    d = client.get("/api/nurture/sequences").json()
    assert seq["id"] in [s["id"] for s in d["sequences"]]
    assert "total_sequences" in d["stats"]


def test_nurture_delete_sequence(client):
    seq = _make_sequence(client)
    assert client.delete(f"/api/nurture/sequences/{seq['id']}").json() == {"ok": True}
    assert client.get(f"/api/nurture/sequences/{seq['id']}").status_code == 404


def test_nurture_delete_missing_sequence_is_404(client):
    r = client.delete("/api/nurture/sequences/zzz")
    assert r.status_code == 404
    assert r.json()["error"] == "Sequence not found"


def test_nurture_due_actions_are_empty_for_a_brand_new_sequence(client):
    """create_sequence schedules the first action +5min out, so nothing is due."""
    _make_sequence(client)
    d = client.get("/api/nurture/due").json()
    assert d["actions"] == []


def test_nurture_mark_sent_flags_the_action(client):
    seq = _make_sequence(client)
    r = client.post("/api/nurture/mark-sent",
                    json={"sequence_id": seq["id"], "action_index": 0})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert client.get(f"/api/nurture/sequences/{seq['id']}").json()["actions"][0]["sent"] is True


def test_nurture_mark_sent_on_missing_sequence_is_404(client):
    r = client.post("/api/nurture/mark-sent", json={"sequence_id": "zzz", "action_index": 0})
    assert r.status_code == 404
    assert r.json()["error"] == "Sequence or action not found"


def test_nurture_mark_sent_on_missing_action_index_is_404(client):
    seq = _make_sequence(client)
    r = client.post("/api/nurture/mark-sent",
                    json={"sequence_id": seq["id"], "action_index": 999})
    assert r.status_code == 404


def test_nurture_incoming_reply_requires_both_fields(client):
    for body in ({}, {"sequence_id": "x"}, {"reply_text": "stop"}):
        r = client.post("/api/nurture/incoming-reply", json=body)
        assert r.status_code == 400, body
        assert "required" in r.json()["error"]


def test_nurture_incoming_reply_on_missing_sequence_is_400(client):
    """handle_incoming_reply returns ok=False, which the route turns into a 400
    (not a 404 and not a silent 200)."""
    r = client.post("/api/nurture/incoming-reply",
                    json={"sequence_id": "zzz", "reply_text": "hello"})
    assert r.status_code == 400
    assert r.json()["error"] == "Sequence not found"


def test_nurture_incoming_reply_honours_an_opt_out(client):
    seq = _make_sequence(client)
    r = client.post("/api/nurture/incoming-reply",
                    json={"sequence_id": seq["id"], "reply_text": "STOP"})
    assert r.status_code == 200
    assert r.json()["action"] == "opt_out"
    assert "unsubscribed" in r.json()["response"].lower()
    assert client.get(f"/api/nurture/sequences/{seq['id']}").json()["completed"] is True


def test_nurture_incoming_reply_detects_booking_intent(client):
    seq = _make_sequence(client)
    r = client.post("/api/nurture/incoming-reply",
                    json={"sequence_id": seq["id"], "reply_text": "can I book a slot?"})
    assert r.status_code == 200
    assert r.json()["action"] != "opt_out"
    assert r.json()["response"]


def test_nurture_scheduling_requires_every_field(client):
    r = client.post("/api/nurture/schedule", json={})
    assert r.status_code == 400
    err = r.json()["error"]
    for field in ("Name", "Phone", "Email", "Date", "Time slot"):
        assert field in err, f"{field} missing from {err!r}"


def test_nurture_scheduling_rejects_a_past_date(client):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    r = client.post("/api/nurture/schedule", json={
        "name": "Bob", "phone": "5125551234", "email": "b@x.test",
        "date": yesterday, "time_slot": "10:00"})
    assert r.status_code == 400
    assert "future" in r.json()["error"]


def test_nurture_scheduling_rejects_an_unparseable_date(client):
    r = client.post("/api/nurture/schedule", json={
        "name": "Bob", "phone": "5125551234", "email": "b@x.test",
        "date": "not-a-date", "time_slot": "10:00"})
    assert r.status_code == 400
    assert "Invalid date" in r.json()["error"]


def test_nurture_scheduling_books_a_future_appointment(client):
    future = (date.today() + timedelta(days=30)).isoformat()
    r = client.post("/api/nurture/schedule", json={
        "name": "Bob Smith", "phone": "5125551234", "email": "b@x.test",
        "date": future, "time_slot": "10:00"})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["appointment_id"]
    assert d["date"] == future
    assert d["time_slot"] == "10:00"

    booked = client.get("/api/nurture/appointments").json()["appointments"]
    assert any(a["appointment_id"] == d["appointment_id"] for a in booked)


def test_nurture_scheduling_widget_renders_html(client):
    r = client.get("/api/nurture/schedule/widget")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "<div" in r.text
    assert "nsw-root" in r.text


def test_nurture_scheduling_widget_accepts_a_business_name(client):
    r = client.get("/api/nurture/schedule/widget?business_name=Acme Roofing")
    assert r.status_code == 200
    assert "Acme Roofing" in r.text


def test_nurture_stats_shape(client):
    d = client.get("/api/nurture/stats").json()
    assert {"total_sequences", "active", "completed", "pending_actions"} <= set(d)


def test_nurture_stats_count_a_new_sequence(client):
    before = client.get("/api/nurture/stats").json()["total_sequences"]
    _make_sequence(client)
    after = client.get("/api/nurture/stats").json()
    assert after["total_sequences"] == before + 1
    assert after["pending_actions"] >= 1


# ── /api/business/* ──────────────────────────────────────────────────────
def test_business_config_get_returns_defaults(client):
    r = client.get("/api/business/config")
    assert r.status_code == 200
    d = r.json()
    assert d["avg_job_size"] == 8500.0
    assert d["gross_margin"] == 0.35
    assert d["business_name"] == "Our Business"


def test_business_config_put_persists_and_returns_the_new_config(client):
    r = client.put("/api/business/config", json={
        "business_name": "Acme Roofing", "avg_job_size": 20000,
        "monthly_ad_budget": 5000, "target_roas": 6,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["business_name"] == "Acme Roofing"
    assert d["avg_job_size"] == 20000.0
    assert d["target_roas"] == 6.0
    # Persisted, not just echoed.
    assert client.get("/api/business/config").json()["business_name"] == "Acme Roofing"


def test_business_config_put_coerces_a_numeric_string(client):
    r = client.put("/api/business/config", json={"avg_job_size": "12345"})
    assert r.status_code == 200
    assert r.json()["avg_job_size"] == 12345.0


def test_business_config_put_ignores_unknown_keys(client):
    r = client.put("/api/business/config", json={"not_a_field": 1})
    assert r.status_code == 200
    assert "not_a_field" not in r.json()


def test_business_config_put_rejects_a_non_numeric_value(client):
    """BUG (audit 2026-09-27): business_config.update_config() raises ValueError
    for a bad value, but the route does not catch it, so the request 500s. A
    caller sending {"avg_job_size": "abc"} is a client error and must be a 400.
    Pinned as a known defect until the route is fixed."""
    r = client.put("/api/business/config", json={"avg_job_size": "abc"})
    assert r.status_code in (400, 500)
    if r.status_code == 500:
        pytest.xfail("PUT /api/business/config 500s on a bad value instead of 400 "
                     "(unhandled ValueError in the route)")
    assert r.json()["error"]


def test_business_config_put_rejects_a_negative_value(client):
    """Same unhandled-ValueError defect as the non-numeric case above."""
    r = client.put("/api/business/config", json={"avg_job_size": -5})
    assert r.status_code in (400, 500)
    if r.status_code == 500:
        pytest.xfail("PUT /api/business/config 500s on a negative value instead of 400")


def test_business_metrics_derive_from_the_config(client):
    client.put("/api/business/config",
               json={"avg_job_size": 10000, "gross_margin": 0.5,
                     "lead_cost_ceiling": 100, "monthly_ad_budget": 4000})
    d = client.get("/api/business/metrics").json()
    assert d["avg_profit_per_job"] == 5000.0
    assert d["leads_needed_per_job"] == 4.0
    assert d["cost_per_acquired_customer"] == 400.0
    assert d["max_cost_per_click"] == 10.0
    assert d["break_even_leads"] == pytest.approx(40.0)


def test_evaluate_lead_rejects_an_unknown_trade(client):
    r = client.post("/api/business/evaluate-lead", json={"trade": "unicorn-fixing"})
    assert r.status_code == 400
    assert "unicorn-fixing" in r.json()["error"]


def test_evaluate_lead_computes_a_verdict(client):
    r = client.post("/api/business/evaluate-lead",
                    json={"trade": "roofing", "lead_score": 80})
    assert r.status_code == 200
    d = r.json()
    assert d["verdict"] in {"pursue", "marginal", "skip"}
    assert d["trade_avg_job_value"] > 0
    assert d["roas"] > 0
    assert d["lead_score"] == 80
    assert "max_bid" in d


def test_evaluate_lead_defaults_the_score(client):
    r = client.post("/api/business/evaluate-lead", json={"trade": "roofing"})
    assert r.status_code == 200
    assert r.json()["lead_score"] == 50


def test_evaluate_lead_requires_auth(anon):
    assert anon.post("/api/business/evaluate-lead", json={"trade": "roofing"}).status_code == 401


def test_business_plans_are_priced_from_stripe_plans(client):
    from engine.stripe_integration import PLANS
    d = client.get("/api/business/plans").json()
    assert {p["id"] for p in d["plans"]} == set(PLANS)
    for plan in d["plans"]:
        assert plan["monthly_cents"] == PLANS[plan["id"]]
        assert plan["monthly_dollars"] == PLANS[plan["id"]] / 100


# ── /api/simulator/project-roi ───────────────────────────────────────────
def test_simulator_requires_trade_and_location(client):
    for body in ({}, {"trade": "roofing"}, {"location": "Austin"}):
        r = client.post("/api/simulator/project-roi", json=body)
        assert r.status_code == 400, body
        assert "trade and location are required" in r.json()["error"]


def test_simulator_rejects_an_unknown_trade(client):
    """project_roi raises ValueError; the route converts it to a 400."""
    r = client.post("/api/simulator/project-roi",
                    json={"trade": "unicorn-fixing", "location": "Austin"})
    assert r.status_code == 400
    assert "Unknown trade" in r.json()["error"]


def test_simulator_projects_a_30_day_campaign(client):
    r = client.post("/api/simulator/project-roi",
                    json={"trade": "roofing", "location": "Austin", "daily_budget": 100})
    assert r.status_code == 200
    d = r.json()
    assert d["ok"] is True
    assert d["trade"] == "roofing"
    assert d["location"] == "Austin"
    assert d["monthly_spend"] == 3000.0
    assert d["projected_cpl"] > 0
    assert len(d["daily_log"]) == 30, "the simulation must model all 30 days"
    assert d["roi_percentage"] is not None


def test_simulator_is_deterministic_per_trade_and_location(client):
    """Same inputs must give the same answer -- a sales rep quoting two numbers
    for the same campaign is a credibility bug."""
    body = {"trade": "plumbing", "location": "Dallas", "daily_budget": 75}
    a = client.post("/api/simulator/project-roi", json=body).json()
    b = client.post("/api/simulator/project-roi", json=body).json()
    assert a["projected_cpl"] == b["projected_cpl"]
    assert a["total_leads"] == b["total_leads"]
    assert a["roi_percentage"] == b["roi_percentage"]


def test_simulator_requires_auth(anon):
    assert anon.post("/api/simulator/project-roi",
                     json={"trade": "roofing", "location": "Austin"}).status_code == 401


# ── /api/chat/collaborate ────────────────────────────────────────────────
def test_chat_requires_a_message(client):
    r = client.post("/api/chat/collaborate", json={"message": "   "})
    assert r.status_code == 400
    assert r.json()["error"] == "message is required"


def test_chat_answers_a_roi_question(client, vault_sandbox):
    vault_sandbox.clear()
    r = client.post("/api/chat/collaborate", json={"message": "simulate roofing roi"})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "ROI" in r.json()["response"] or "roi" in r.json()["response"].lower()


@pytest.mark.parametrize("message,expect", [
    ("find me some leads", "Search Page"),
    ("where do I set up verticals", "Verticals Page"),
    ("how do I change my api key", "Key Vault"),
    ("hello there", "LeadForge AI Copilot"),
])
def test_chat_falls_back_to_the_topic_router(client, vault_sandbox, message, expect):
    vault_sandbox.clear()
    r = client.post("/api/chat/collaborate", json={"message": message})
    assert r.status_code == 200
    assert expect in r.json()["response"], r.json()["response"]


def test_chat_falls_back_when_the_llm_call_raises(client, vault_sandbox, monkeypatch):
    """A Perplexity outage must produce the local answer, not a 500."""
    vault_sandbox[("perplexity", "user")] = "pplx-fake"

    class Boom:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **kw):
            raise RuntimeError("perplexity is down")

    import httpx
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: Boom())

    r = client.post("/api/chat/collaborate", json={"message": "simulate roi"})
    assert r.status_code == 200
    assert r.json()["response"], "the fallback answer must be used"


# ── /api/crm/* ───────────────────────────────────────────────────────────
def test_crm_history_is_empty(client):
    assert client.get("/api/crm/history").json() == {"history": []}


def test_crm_stats_shape(client):
    d = client.get("/api/crm/stats").json()
    assert d == {"total_pushes": 0, "successful_pushes": 0,
                 "failed_pushes": 0, "last_push": None}


def test_crm_history_limit_is_enforced(client):
    assert client.get("/api/crm/history?limit=101").status_code == 422


# ── HTML pages ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("path,marker", [
    ("/", "Lead Gen"),
    ("/app", "<html"),
    ("/vault", "<html"),
])
def test_html_pages_serve_their_asset(client, path, marker):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert marker.lower() in r.text.lower(), r.text[:200]


def test_dashboard_serves_static_index(client):
    r = client.get("/")
    assert r.status_code == 200
    assert (main.STATIC_DIR / "index.html").read_text(encoding="utf-8")[:100] in r.text


@pytest.mark.parametrize("route,attr,fallback", [
    ("/", "dashboard", "Dashboard not found."),
    ("/app", "saas_app", "App UI not found."),
    ("/vault", "vault_page", "Vault UI not found."),
])
def test_html_pages_have_a_fallback_when_the_asset_is_missing(
        client, monkeypatch, tmp_path, route, attr, fallback):
    """If the static file is absent the route must still return 200 HTML with a
    human-readable message, not a 500."""
    monkeypatch.setattr(main, "STATIC_DIR", tmp_path / "gone")
    r = client.get(route)
    assert r.status_code == 200
    assert fallback in r.text


def test_capture_thank_you_requires_no_auth(anon):
    assert anon.get("/api/capture/thank-you").status_code == 200
