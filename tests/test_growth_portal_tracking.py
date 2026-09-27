"""Tests for conversion tracking (audit 2026-09-27).

`tracking.py` is the attribution half of the growth funnel: a 1x1 pixel for
email/lander impressions, a JSON event endpoint, and a first-touch /
last-touch report keyed by `lead_id`. Both write to the real `utm_events`
table, so these run against a real temporary SQLite file and assert the exact
rows that land in it.

Read from the implementation before asserting:

  * `_record_event` mints `uuid4().hex[:12]` per call — it is NOT idempotent,
    so two identical pixel hits produce two rows with two distinct ids. Dedupe
    would silently under-count a funnel; the test pins the count instead of
    assuming a dedupe that does not exist.
  * `metadata` is every body key except the six promoted columns
    (`event_type`, `lead_id`, and the five `utm_*`), JSON-encoded.
  * the client IP comes from `request.client.host`, never from
    `X-Forwarded-For`.
  * `/track/event` defaults `event_type` to `"conversion"` only when the body
    omits it.
  * `/track/attribution/{lead_id}` parameterises the lead id, so a hostile id
    cannot execute SQL, and returns `first_touch`/`last_touch` as `None` (not
    an error) for an unknown lead.
"""
import json

import pytest
from fastapi.testclient import TestClient

import main
from engine.database import Database
from engine.growth_portal.tracking import _ensure_table

UTM_COLUMNS = ["id", "event_type", "lead_id", "utm_source", "utm_medium",
               "utm_campaign", "utm_term", "utm_content", "page_path", "referrer",
               "user_agent", "ip", "timestamp", "metadata"]

PROMOTED_KEYS = {"event_type", "lead_id", "utm_source", "utm_medium",
                 "utm_campaign", "utm_term", "utm_content"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point the whole app at a throwaway SQLite file, schema included."""
    monkeypatch.setattr(Database, "db_file", str(tmp_path / "tracking.db"))
    Database.initialize()
    _ensure_table()
    return Database


@pytest.fixture
def client(db):
    # TestClient without the lifespan context manager: the tracking router has
    # no startup work and this keeps the scheduler threads out of the test.
    return TestClient(main.app)


def events_for(lead_id):
    with Database.get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM utm_events WHERE lead_id = ? ORDER BY timestamp, rowid",
            (lead_id,))]


def all_events():
    with Database.get_connection() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM utm_events ORDER BY rowid")]


# ── schema ─────────────────────────────────────────────────────────────────
def test_the_utm_events_table_exists_with_every_tracked_column(db):
    with Database.get_connection() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(utm_events)")}
    assert set(UTM_COLUMNS) <= cols, cols


def test_ensure_table_is_idempotent_on_an_already_populated_table(client, db):
    client.post("/track/event", json={"lead_id": "keep-me"})
    _ensure_table()  # must not drop or truncate
    assert len(events_for("keep-me")) == 1


# ── the pixel ──────────────────────────────────────────────────────────────
def test_the_pixel_returns_a_real_1x1_transparent_gif(client):
    r = client.get("/track/pixel.gif")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/gif"
    assert r.content.startswith(b"GIF89a\x01\x00\x01\x00")
    assert r.content.endswith(b";")
    assert len(r.content) == 43, "43-byte 1x1 GIF header + terminator"


def test_the_pixel_still_returns_a_gif_with_no_query_parameters_at_all(client):
    """A tracker that 500s on a bare pixel is a tracker nobody notices."""
    r = client.get("/track/pixel.gif")
    assert r.status_code == 200
    rows = all_events()
    assert len(rows) == 1
    assert rows[0]["event_type"] == "page_view", "the documented default"
    assert rows[0]["lead_id"] is None
    assert rows[0]["page_path"] == "/track/pixel.gif"


def test_the_pixel_records_every_utm_parameter_it_is_given(client):
    client.get("/track/pixel.gif", params={
        "lead_id": "PX1", "utm_source": "google", "utm_medium": "cpc",
        "utm_campaign": "spring", "utm_term": "roofing",
        "utm_content": "banner-b", "event_type": "email_open"})
    (row,) = events_for("PX1")
    assert row["event_type"] == "email_open", "explicit event_type overrides the default"
    assert row["utm_source"] == "google"
    assert row["utm_medium"] == "cpc"
    assert row["utm_campaign"] == "spring"
    assert row["utm_term"] == "roofing"
    assert row["utm_content"] == "banner-b"


def test_the_pixel_stamps_the_request_path_referrer_and_user_agent(client):
    client.get("/track/pixel.gif", params={"lead_id": "PX2"},
               headers={"referer": "https://mail.test/inbox",
                        "user-agent": "probe-UA/1.0"})
    (row,) = events_for("PX2")
    assert row["page_path"] == "/track/pixel.gif"
    assert row["referrer"] == "https://mail.test/inbox"
    assert row["user_agent"] == "probe-UA/1.0"


def test_the_pixel_does_not_trust_x_forwarded_for_the_client_ip(client):
    """Proxies rewrite X-Forwarded-For; `request.client` is the real peer."""
    client.get("/track/pixel.gif", params={"lead_id": "PX3"},
               headers={"X-Forwarded-For": "9.9.9.9"})
    (row,) = events_for("PX3")
    assert row["ip"] != "9.9.9.9", "X-Forwarded-For must not be stored as the client ip"


def test_repeat_pixel_hits_each_get_their_own_row_and_id(client):
    """No dedupe exists — a duplicate hit must be countable, not merged away."""
    for _ in range(3):
        client.get("/track/pixel.gif", params={"lead_id": "PX4", "utm_source": "fb"})
    rows = events_for("PX4")
    assert len(rows) == 3
    assert len({r["id"] for r in rows}) == 3, "each hit mints a fresh id"
    assert {r["event_type"] for r in rows} == {"page_view"}


def test_every_minted_event_id_is_twelve_hex_characters(client):
    client.post("/track/event", json={"lead_id": "ID1"})
    client.get("/track/pixel.gif", params={"lead_id": "ID1"})
    rows = events_for("ID1")
    assert rows
    for row in rows:
        assert len(row["id"]) == 12, row["id"]
        assert set(row["id"]) <= set("0123456789abcdef"), row["id"]


# ── the JSON event endpoint ────────────────────────────────────────────────
def test_posting_an_event_without_a_type_records_a_conversion(client):
    r = client.post("/track/event", json={"lead_id": "EV1", "utm_source": "g"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    (row,) = events_for("EV1")
    assert row["event_type"] == "conversion", "documented default for POST /track/event"
    assert row["utm_source"] == "g"
    assert row["page_path"] == "/track/event"


def test_an_explicit_event_type_beats_the_conversion_default(client):
    client.post("/track/event", json={"lead_id": "EV2", "event_type": "signup"})
    (row,) = events_for("EV2")
    assert row["event_type"] == "signup"


def test_utm_parameters_are_promoted_to_columns_not_left_in_metadata(client):
    client.post("/track/event", json={
        "lead_id": "EV3", "utm_source": "g", "utm_medium": "m",
        "utm_campaign": "c", "utm_term": "t", "utm_content": "ct",
        "event_type": "purchase", "order_value": 250, "tags": ["a", "b"]})
    (row,) = events_for("EV3")
    assert (row["utm_source"], row["utm_medium"], row["utm_campaign"]) == ("g", "m", "c")
    assert (row["utm_term"], row["utm_content"]) == ("t", "ct")
    assert row["event_type"] == "purchase"
    meta = json.loads(row["metadata"])
    assert meta == {"order_value": 250, "tags": ["a", "b"]}, \
        "only the seven promoted keys may be stripped from metadata"
    assert not (PROMOTED_KEYS & set(meta))


def test_a_payload_with_no_extra_keys_gets_an_empty_metadata_object(client):
    client.post("/track/event", json={"lead_id": "EV4"})
    (row,) = events_for("EV4")
    assert row["metadata"] == "{}"


def test_nested_metadata_survives_the_json_round_trip(client):
    client.post("/track/event", json={"lead_id": "EV5", "nested": {"a": [1, 2]}})
    (row,) = events_for("EV5")
    assert json.loads(row["metadata"]) == {"nested": {"a": [1, 2]}}


def test_the_event_timestamp_is_utc_iso8601(client):
    from datetime import datetime

    client.post("/track/event", json={"lead_id": "EV6"})
    (row,) = events_for("EV6")
    stamp = row["timestamp"]
    assert stamp.endswith("+00:00"), stamp
    parsed = datetime.fromisoformat(stamp)
    assert (parsed.tzinfo.utcoffset(parsed).total_seconds()) == 0


def test_the_pixel_and_the_event_endpoint_share_one_utm_events_funnel(client):
    client.get("/track/pixel.gif", params={"lead_id": "SHARED", "utm_source": "g"})
    client.post("/track/event", json={"lead_id": "SHARED", "event_type": "conversion"})
    rows = events_for("SHARED")
    assert [r["event_type"] for r in rows] == ["page_view", "conversion"]
    assert {r["page_path"] for r in rows} == {"/track/pixel.gif", "/track/event"}


def test_a_lead_capture_writes_to_leads_not_to_the_attribution_funnel(client):
    """The capture form and the tracker must not pollute each other's table."""
    with Database.get_connection() as conn:
        conn.execute(
            "INSERT INTO leads (id, title, source) VALUES ('c1', 'Cap', 'growth_portal')")
        conn.commit()
    assert all_events() == [], "capturing a lead must not fabricate a utm event"


# ── malformed input ────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw", [b"not json", b"", b"{", b"[1,2]", b'"a string"', b"null"])
def test_a_malformed_event_body_is_a_500_and_not_a_crash_or_a_silent_ok(client, raw):
    """The endpoint has no body guard: it must surface the failure, not fake success."""
    from starlette.testclient import TestClient as TC

    c = TC(main.app, raise_server_exceptions=False)
    r = c.post("/track/event", content=raw,
               headers={"content-type": "application/json"})
    assert r.status_code == 500
    assert r.json() == {"error": "Internal server error", "code": 500}
    assert all_events() == [], "no partial row may be written for a rejected body"


def test_a_malformed_event_body_writes_nothing_to_the_table(client):
    from starlette.testclient import TestClient as TC

    c = TC(main.app, raise_server_exceptions=False)
    c.post("/track/event", content=b"{oops",
          headers={"content-type": "application/json"})
    assert all_events() == []


def test_a_valid_event_after_a_malformed_one_still_lands(client):
    from starlette.testclient import TestClient as TC

    c = TC(main.app, raise_server_exceptions=False)
    c.post("/track/event", content=b"{", headers={"content-type": "application/json"})
    r = c.post("/track/event", json={"lead_id": "AFTER"})
    assert r.status_code == 200
    assert len(events_for("AFTER")) == 1


# ── the attribution report ─────────────────────────────────────────────────
def test_attribution_for_an_unknown_lead_is_empty_rather_than_an_error(client):
    r = client.get("/track/attribution/NOBODY-HERE")
    assert r.status_code == 200
    assert r.json() == {"lead_id": "NOBODY-HERE", "events": [],
                        "first_touch": None, "last_touch": None}


def test_first_and_last_touch_point_at_the_first_and_last_event_rows(client):
    client.post("/track/event", json={"lead_id": "AT1", "event_type": "first"})
    client.post("/track/event", json={"lead_id": "AT1", "event_type": "middle"})
    client.post("/track/event", json={"lead_id": "AT1", "event_type": "last"})
    body = client.get("/track/attribution/AT1").json()
    assert body["lead_id"] == "AT1"
    assert len(body["events"]) == 3
    assert [e["event_type"] for e in body["events"]] == ["first", "middle", "last"]
    assert body["first_touch"]["id"] == body["events"][0]["id"]
    assert body["last_touch"]["id"] == body["events"][-1]["id"]
    assert body["first_touch"]["event_type"] == "first"
    assert body["last_touch"]["event_type"] == "last"


def test_attribution_events_are_returned_oldest_first(client):
    for i in range(4):
        client.post("/track/event", json={"lead_id": "AT2", "event_type": f"e{i}"})
    stamps = [e["timestamp"] for e in client.get("/track/attribution/AT2").json()["events"]]
    assert stamps == sorted(stamps), "ORDER BY timestamp must be oldest-first"


def test_a_single_event_is_both_first_and_last_touch(client):
    client.post("/track/event", json={"lead_id": "AT3", "event_type": "only"})
    body = client.get("/track/attribution/AT3").json()
    assert body["first_touch"]["id"] == body["last_touch"]["id"]
    assert len(body["events"]) == 1


def test_attribution_is_scoped_to_one_lead_and_never_leaks_between_leads(client):
    client.post("/track/event", json={"lead_id": "AT4", "event_type": "mine"})
    client.post("/track/event", json={"lead_id": "AT5", "event_type": "theirs"})
    client.post("/track/event", json={"lead_id": "AT5", "event_type": "theirs-2"})
    assert len(client.get("/track/attribution/AT4").json()["events"]) == 1
    five = client.get("/track/attribution/AT5").json()
    assert [e["event_type"] for e in five["events"]] == ["theirs", "theirs-2"]
    assert {e["lead_id"] for e in five["events"]} == {"AT5"}


def test_leads_with_no_events_report_no_touch(client):
    client.post("/track/event", json={"lead_id": "AT6", "event_type": "x"})
    body = client.get("/track/attribution/AT6").json()
    assert body["first_touch"]["lead_id"] == "AT6"
    assert body["last_touch"]["lead_id"] == "AT6"


def test_every_returned_event_carries_the_full_event_shape(client):
    client.post("/track/event", json={"lead_id": "AT7", "utm_source": "g"})
    (event,) = client.get("/track/attribution/AT7").json()["events"]
    assert set(event) == set(UTM_COLUMNS), set(event) ^ set(UTM_COLUMNS)


def test_a_utm_conversion_rate_can_be_counted_exactly_from_the_report(client):
    """Hand-counted funnel: 3 page views from google, 1 from facebook, 1 conversion."""
    for _ in range(3):
        client.get("/track/pixel.gif", params={"lead_id": "FUN",
                                               "utm_source": "google"})
    client.get("/track/pixel.gif", params={"lead_id": "FUN", "utm_source": "facebook"})
    client.post("/track/event", json={"lead_id": "FUN", "event_type": "conversion"})

    events = client.get("/track/attribution/FUN").json()["events"]
    assert len(events) == 5
    page_views = [e for e in events if e["event_type"] == "page_view"]
    conversions = [e for e in events if e["event_type"] == "conversion"]
    assert len(page_views) == 4
    assert len(conversions) == 1
    google = [e for e in page_views if e["utm_source"] == "google"]
    assert len(google) == 3
    # 1 conversion / 4 page views = 25.0% exactly.
    assert 100 * len(conversions) / len(page_views) == 25.0
    # 1 of 3 google viewers converted = 33.33%, not the 25% blended rate.
    assert round(100 * len(conversions) / len(google), 2) == 33.33


# ── hostile lead ids ───────────────────────────────────────────────────────
@pytest.mark.parametrize("lead_id", [
    "'; DROP TABLE utm_events; --",
    "x'y",
    "1 OR 1=1",
    "%00",
    "a b",
    "'; UPDATE utm_events SET utm_source='pwned'; --",
])
def test_a_hostile_lead_id_is_echoed_back_and_cannot_execute_sql(client, lead_id):
    client.post("/track/event", json={"lead_id": lead_id, "utm_source": "sentinel"})
    r = client.get("/track/attribution/" + lead_id)
    assert r.status_code == 200
    body = r.json()
    if body["events"]:
        # Only the row carrying this exact id may come back.
        assert {e["lead_id"] for e in body["events"]} == {lead_id}
    with Database.get_connection() as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='utm_events'").fetchone()


def test_a_path_traversal_lead_id_never_reaches_the_attribution_route(client):
    """`../../etc/passwd` is resolved by the URL layer to /etc/passwd -> 404."""
    r = client.get("/track/attribution/../../etc/passwd")
    assert r.status_code == 404
    with Database.get_connection() as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE name='utm_events'").fetchone()


def test_a_lead_id_cannot_rewrite_existing_rows_through_sql(client):
    client.post("/track/event", json={"lead_id": "victim", "utm_source": "original"})
    client.post("/track/event",
                json={"lead_id": "'; UPDATE utm_events SET utm_source='pwned'; --"})
    assert events_for("victim")[0]["utm_source"] == "original", \
        "the parameterised UPDATE must not be reachable through the lead_id"


def test_an_injection_attempt_cannot_widen_the_result_set(client):
    for i in range(3):
        client.post("/track/event", json={"lead_id": f"INJ{i}", "event_type": "real"})
    r = client.get("/track/attribution/" + "' OR '1'='1")
    assert r.status_code == 200
    assert r.json()["events"] == [], "a quote-breakout must match nothing, not everything"
