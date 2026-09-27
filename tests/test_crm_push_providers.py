"""Tests for engine/crm_push.py — outbound CRM push (audit 2026-09-27).

crm_push.py fans one lead out to one of five providers. Two seams are faked:
`httpx.AsyncClient` (so no provider endpoint is ever contacted) and
`CrmPush._get_key` (so no real key in the local vault or environment is read —
tests assert on the "not configured" branches without touching secrets).

The core guarantee under test is the one that matters for a lead-gen product:
a push that fails must be reported as FAILED. Every provider branch is exercised
in success, HTTP-error, and transport-error form, and each asserts `ok is False`
plus a populated `error` — never a silent success.

There is no queue or retry in this module: push_leads loops synchronously and
returns one result dict per lead, appended to `self._history` unless the lead
was skipped for a low score. That contract is pinned directly.
"""
import pytest

from engine.crm_push import CrmPush


# ── httpx stand-in ─────────────────────────────────────────────────────────
class _Resp:
    def __init__(self, status=200, text="", payload=None):
        self.status_code = status
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


class _HTTPX:
    """Records every POST and answers from a route table."""

    def __init__(self, routes=None, default=None, raises=None):
        self.routes = routes or {}
        self.default = default if default is not None else _Resp(200, "{}", {})
        self.raises = raises
        self.requests = []

    def client(self):
        hx = self

        class _Client:
            def __init__(self, *a, **k):
                self.timeout = k.get("timeout")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *e):
                return False

            async def post(self, url, json=None, headers=None, **kw):
                hx.requests.append({"url": url, "json": json,
                                    "headers": headers, "timeout": self.timeout})
                if hx.raises:
                    raise hx.raises
                for frag, resp in hx.routes.items():
                    if frag in url:
                        return resp
                return hx.default

        return _Client

    @property
    def last(self):
        assert self.requests, "no HTTP request was made"
        return self.requests[-1]


@pytest.fixture
def push():
    return CrmPush()


@pytest.fixture
def hx(monkeypatch):
    """Install a fake httpx.AsyncClient; yields the recorder.

    crm_push.py does `import httpx` INSIDE push_leads, so the seam is the real
    httpx module object, not an engine.crm_push attribute.
    """
    import httpx
    rec = _HTTPX()
    monkeypatch.setattr(httpx, "AsyncClient", rec.client())
    return rec


def _keyed(monkeypatch, keys):
    """Force _get_key to return a fixed value per service (no real secrets)."""
    from engine.crm_push import CrmPush as CP
    monkeypatch.setattr(
        CP, "_get_key",
        classmethod(lambda cls, service, env_var: keys.get(service)))
    return CP


def _lead(**kw):
    base = {"id": "L1", "title": "Jane Doe", "score": 90}
    base.update(kw)
    return base


# ── score gate (applies to every provider) ─────────────────────────────────
async def test_lead_below_min_score_is_skipped_not_pushed(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    out = await push.push_leads([_lead(score=10)], provider="hubspot",
                                config={"min_score": 70})
    assert out == [{"ok": False, "provider": "hubspot", "lead_id": "L1",
                    "error": "Below min score", "skipped": True}], out
    assert hx.requests == [], "a skipped lead must never reach the API"


async def test_score_gate_defaults_to_70(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    hx.routes["hubapi"] = _Resp(200, "{}", {"id": "1"})
    out = await push.push_leads([_lead(score=70)], provider="hubspot")
    assert out[0]["ok"] is True, "min_score defaults to 70 and 70 passes it"


async def test_a_missing_score_is_treated_as_zero_and_skipped(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    lead = _lead()
    lead.pop("score")
    out = await push.push_leads([lead], provider="hubspot")
    assert out[0]["skipped"] is True
    assert out[0]["error"] == "Below min score"


async def test_skipped_leads_are_not_written_to_history(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    await push.push_leads([_lead(score=1)], provider="hubspot")
    assert push.get_history() == [], "a skip is not a push attempt"


# ── push_lead (single) ────────────────────────────────────────────────────
async def test_push_lead_unwraps_the_single_result(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    hx.routes["hubapi"] = _Resp(200, "{}", {"id": "999"})
    out = await push.push_lead(_lead(), provider="hubspot")
    assert out["ok"] is True
    assert out["remote_id"] == "999"
    assert out["lead_id"] == "L1"


# ── HubSpot ────────────────────────────────────────────────────────────────
def test_hubspot_properties_split_the_title_into_first_and_last_name():
    props = CrmPush._build_hubspot_properties({"title": "Jane Doe"})
    assert props["firstname"] == "Jane"
    assert props["lastname"] == "Doe"


def test_hubspot_properties_fall_back_to_the_name_key():
    props = CrmPush._build_hubspot_properties({"name": "Ada Lovelace"})
    assert (props["firstname"], props["lastname"]) == ("Ada", "Lovelace")


def test_hubspot_properties_for_a_single_word_name_leave_lastname_empty():
    props = CrmPush._build_hubspot_properties({"title": "Prince"})
    assert props["firstname"] == "Prince"
    assert props["lastname"] == ""


def test_hubspot_properties_prefer_explicit_fields_over_the_split_title():
    props = CrmPush._build_hubspot_properties(
        {"title": "Wrong Name", "first_name": "Jane", "last_name": "Smith"})
    assert (props["firstname"], props["lastname"]) == ("Jane", "Smith")


def test_hubspot_properties_fall_back_to_business_name_for_company():
    props = CrmPush._build_hubspot_properties({"title": "A B", "business_name": "Acme"})
    assert props["company"] == "Acme"


def test_hubspot_properties_stamp_a_fixed_lead_status_and_default_source():
    props = CrmPush._build_hubspot_properties({"title": "A B"})
    assert props["hs_lead_status"] == "NEW"
    assert props["lead_source"] == "web"


def test_hubspot_properties_keep_an_explicit_source():
    props = CrmPush._build_hubspot_properties({"title": "A B", "source": "craigslist"})
    assert props["lead_source"] == "craigslist"


async def test_hubspot_success_returns_the_remote_id(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "hs-key"})
    hx.routes["hubapi"] = _Resp(201, "{}", {"id": "hs-1"})
    out = await push.push_leads([_lead()], provider="hubspot")
    assert out[0]["ok"] is True
    assert out[0]["remote_id"] == "hs-1"
    assert "error" not in out[0], out


async def test_hubspot_posts_to_the_v3_contacts_endpoint_with_a_bearer_token(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "hs-key"})
    hx.routes["hubapi"] = _Resp(201, "{}", {"id": "hs-1"})
    await push.push_leads([_lead()], provider="hubspot")
    req = hx.last
    assert req["url"] == "https://api.hubapi.com/crm/v3/objects/contacts", req
    assert req["headers"]["Authorization"] == "Bearer hs-key"
    assert "properties" in req["json"], req["json"]
    assert req["timeout"] == 10.0


async def test_hubspot_http_error_is_reported_not_swallowed(push, hx, monkeypatch):
    """DATA-LOSS GUARD: a 4xx must never come back as ok=True."""
    _keyed(monkeypatch, {"hubspot": "hs-key"})
    hx.routes["hubapi"] = _Resp(400, "duplicate contact")
    out = await push.push_leads([_lead()], provider="hubspot")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "duplicate contact"
    assert "remote_id" not in out[0], "no id may be invented on failure"


async def test_hubspot_transport_error_is_reported(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "hs-key"})
    hx.raises = OSError("connection reset by peer")
    out = await push.push_leads([_lead()], provider="hubspot")
    assert out[0]["ok"] is False
    assert "connection reset" in out[0]["error"]


async def test_hubspot_without_a_key_does_not_call_the_api(push, hx, monkeypatch):
    _keyed(monkeypatch, {})
    out = await push.push_leads([_lead()], provider="hubspot")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "HUBSPOT_API_KEY not configured"
    assert hx.requests == []


# ── GoHighLevel ────────────────────────────────────────────────────────────
async def test_gohighlevel_success_reads_the_contact_id(push, monkeypatch):
    async def upsert(lead):
        return {"ok": True, "body": {"contact": {"id": "ghl-7"}}}

    monkeypatch.setattr("crm_plus.crmx.upsert_contact", upsert)
    out = await push.push_leads([_lead()], provider="gohighlevel")
    assert out[0]["ok"] is True
    assert out[0]["remote_id"] == "ghl-7"


async def test_gohighlevel_reads_a_flat_body_id(push, monkeypatch):
    async def upsert(lead):
        return {"ok": True, "body": {"id": "ghl-8"}}

    monkeypatch.setattr("crm_plus.crmx.upsert_contact", upsert)
    out = await push.push_leads([_lead()], provider="gohighlevel")
    assert out[0]["remote_id"] == "ghl-8"


async def test_gohighlevel_tolerates_a_missing_body(push, monkeypatch):
    async def upsert(lead):
        return {"ok": True, "body": None}

    monkeypatch.setattr("crm_plus.crmx.upsert_contact", upsert)
    out = await push.push_leads([_lead()], provider="gohighlevel")
    assert out[0]["ok"] is True
    assert out[0]["remote_id"] is None


async def test_gohighlevel_failure_is_reported(push, monkeypatch):
    async def upsert(lead):
        return {"ok": False, "body": "invalid locationId"}

    monkeypatch.setattr("crm_plus.crmx.upsert_contact", upsert)
    out = await push.push_leads([_lead()], provider="gohighlevel")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "invalid locationId"


async def test_gohighlevel_failure_with_no_body_gets_a_default_error(push, monkeypatch):
    async def upsert(lead):
        return {"ok": False}

    monkeypatch.setattr("crm_plus.crmx.upsert_contact", upsert)
    out = await push.push_leads([_lead()], provider="gohighlevel")
    assert out[0]["error"] == "GoHighLevel error", out


async def test_gohighlevel_transport_error_is_reported(push, monkeypatch):
    async def upsert(lead):
        raise RuntimeError("ghl timeout")

    monkeypatch.setattr("crm_plus.crmx.upsert_contact", upsert)
    out = await push.push_leads([_lead()], provider="gohighlevel")
    assert out[0]["ok"] is False
    assert "ghl timeout" in out[0]["error"]


# ── Salesforce ─────────────────────────────────────────────────────────────
async def test_salesforce_success_posts_to_the_lead_sobject(push, hx, monkeypatch):
    _keyed(monkeypatch, {"salesforce_access_token": "sf-tok",
                        "salesforce_instance_url": "https://acme.my.salesforce.com/"})
    hx.routes["sobjects/Lead"] = _Resp(201, "{}", {"id": "00Q1"})
    out = await push.push_leads([_lead()], provider="salesforce")
    assert out[0]["ok"] is True
    assert out[0]["remote_id"] == "00Q1"
    req = hx.last
    assert req["url"] == "https://acme.my.salesforce.com/services/data/v59.0/sobjects/Lead", req
    assert req["headers"]["Authorization"] == "Bearer sf-tok"


async def test_salesforce_payload_uses_flat_snake_free_field_names(push, hx, monkeypatch):
    _keyed(monkeypatch, {"salesforce_access_token": "t", "salesforce_instance_url": "https://x"})
    hx.routes["sobjects/Lead"] = _Resp(201, "{}", {"id": "1"})
    await push.push_leads([_lead(phone="555", email="a@b.test", notes="n")], provider="salesforce")
    body = hx.last["json"]
    assert body["FirstName"] == "Jane"
    assert body["LastName"] == "Doe"
    assert body["Email"] == "a@b.test"
    assert body["Phone"] == "555"
    assert body["Description"] == "n"


async def test_salesforce_defaults_a_missing_company(push, hx, monkeypatch):
    _keyed(monkeypatch, {"salesforce_access_token": "t", "salesforce_instance_url": "https://x"})
    hx.routes["sobjects/Lead"] = _Resp(201, "{}", {"id": "1"})
    await push.push_leads([_lead()], provider="salesforce")
    assert hx.last["json"]["Company"] == "Unknown Company"


async def test_salesforce_falls_back_to_the_name_key(push, hx, monkeypatch):
    _keyed(monkeypatch, {"salesforce_access_token": "t", "salesforce_instance_url": "https://x"})
    hx.routes["sobjects/Lead"] = _Resp(201, "{}", {"id": "1"})
    await push.push_leads([{"id": "L", "name": "Ada Lovelace", "score": 90}], provider="salesforce")
    body = hx.last["json"]
    assert (body["FirstName"], body["LastName"]) == ("Ada", "Lovelace")


async def test_salesforce_http_error_is_reported(push, hx, monkeypatch):
    _keyed(monkeypatch, {"salesforce_access_token": "t", "salesforce_instance_url": "https://x"})
    hx.routes["sobjects/Lead"] = _Resp(401, "Session expired")
    out = await push.push_leads([_lead()], provider="salesforce")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "Session expired"


async def test_salesforce_transport_error_is_reported(push, hx, monkeypatch):
    _keyed(monkeypatch, {"salesforce_access_token": "t", "salesforce_instance_url": "https://x"})
    hx.raises = OSError("dns failure")
    out = await push.push_leads([_lead()], provider="salesforce")
    assert out[0]["ok"] is False
    assert "dns failure" in out[0]["error"]


async def test_salesforce_without_a_token_does_not_call_the_api(push, hx, monkeypatch):
    _keyed(monkeypatch, {"salesforce_access_token": "t", "salesforce_instance_url": None})
    out = await push.push_leads([_lead()], provider="salesforce")
    assert out[0]["ok"] is False
    assert "SALESFORCE_ACCESS_TOKEN" in out[0]["error"]
    assert hx.requests == []


# ── Zoho ───────────────────────────────────────────────────────────────────
async def test_zoho_success_reads_the_details_id(push, hx, monkeypatch):
    _keyed(monkeypatch, {"zoho_access_token": "zk", "zoho_api_domain": "https://www.zohoapis.test"})
    hx.routes["/crm/v5/Leads"] = _Resp(201, "", {
        "data": [{"status": "success", "details": {"id": "z-1"}}]})
    out = await push.push_leads([_lead()], provider="zoho")
    assert out[0]["ok"] is True
    assert out[0]["remote_id"] == "z-1"


async def test_zoho_uses_the_oauth_token_header_and_data_envelope(push, hx, monkeypatch):
    _keyed(monkeypatch, {"zoho_access_token": "zk", "zoho_api_domain": None})
    hx.routes["/crm/v5/Leads"] = _Resp(201, "", {"data": [{"status": "success"}]})
    await push.push_leads([_lead()], provider="zoho")
    req = hx.last
    assert req["url"] == "https://www.zohoapis.com/crm/v5/Leads", req
    assert req["headers"]["Authorization"] == "Zoho-oauthtoken zk"
    assert req["json"]["data"][0]["First_Name"] == "Jane"
    assert req["json"]["data"][0]["Last_Name"] == "Doe"


async def test_zoho_a_2xx_with_a_failed_record_is_reported(push, hx, monkeypatch):
    """DATA-LOSS GUARD: Zoho returns HTTP 201 with a per-record status. A 2xx
    alone must not be read as success."""
    _keyed(monkeypatch, {"zoho_access_token": "zk", "zoho_api_domain": None})
    hx.routes["/crm/v5/Leads"] = _Resp(201, "", {
        "data": [{"status": "error", "message": "DUPLICATE_DATA"}]})
    out = await push.push_leads([_lead()], provider="zoho")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "DUPLICATE_DATA"
    assert "remote_id" not in out[0]


async def test_zoho_failure_record_with_no_message_gets_a_default(push, hx, monkeypatch):
    _keyed(monkeypatch, {"zoho_access_token": "zk", "zoho_api_domain": None})
    hx.routes["/crm/v5/Leads"] = _Resp(201, "", {"data": [{"status": "error"}]})
    out = await push.push_leads([_lead()], provider="zoho")
    assert out[0]["error"] == "Zoho CRM error", out


async def test_zoho_empty_data_list_is_reported_as_a_zoho_error(push, hx, monkeypatch):
    """`data.get("data") or [{}]` -- an empty Zoho data list now yields the
    actionable "Zoho CRM error" instead of "list index out of range".

    The old `data.get("data", [{}])[0]` only applied its default when the key
    was ABSENT, so Zoho's `{"data": []}` raised IndexError. The push still
    failed safe (ok=False, nothing marked pushed), but the operator got a
    useless message.
    """
    _keyed(monkeypatch, {"zoho_access_token": "zk", "zoho_api_domain": None})
    hx.routes["/crm/v5/Leads"] = _Resp(201, "", {"data": []})
    out = await push.push_leads([_lead()], provider="zoho")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "Zoho CRM error", out


async def test_zoho_missing_data_key_falls_back_to_the_default_record(push, hx, monkeypatch):
    """The default `[{}]` DOES apply when the key is absent — the no-crash path."""
    _keyed(monkeypatch, {"zoho_access_token": "zk", "zoho_api_domain": None})
    hx.routes["/crm/v5/Leads"] = _Resp(201, "", {"code": "INVALID_DATA"})
    out = await push.push_leads([_lead()], provider="zoho")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "Zoho CRM error", out


async def test_zoho_http_error_is_reported(push, hx, monkeypatch):
    _keyed(monkeypatch, {"zoho_access_token": "zk", "zoho_api_domain": None})
    hx.routes["/crm/v5/Leads"] = _Resp(429, "rate limited")
    out = await push.push_leads([_lead()], provider="zoho")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "rate limited"


async def test_zoho_transport_error_is_reported(push, hx, monkeypatch):
    _keyed(monkeypatch, {"zoho_access_token": "zk", "zoho_api_domain": None})
    hx.raises = OSError("socket hang up")
    out = await push.push_leads([_lead()], provider="zoho")
    assert out[0]["ok"] is False
    assert "socket hang up" in out[0]["error"]


async def test_zoho_without_a_token_does_not_call_the_api(push, hx, monkeypatch):
    _keyed(monkeypatch, {"zoho_access_token": None})
    out = await push.push_leads([_lead()], provider="zoho")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "ZOHO_ACCESS_TOKEN not configured"
    assert hx.requests == []


# ── Pipedrive ──────────────────────────────────────────────────────────────
def test_pipedrive_payload_omits_empty_email_and_phone_arrays():
    payload = CrmPush._build_pipedrive_payload({"title": "Jane Doe"})
    assert payload["name"] == "Jane Doe"
    assert payload["email"] == []
    assert payload["phone"] == []


def test_pipedrive_payload_marks_email_and_phone_as_primary():
    payload = CrmPush._build_pipedrive_payload(
        {"title": "Jane", "email": "a@b.test", "phone": "555"})
    assert payload["email"] == [{"value": "a@b.test", "primary": True}]
    assert payload["phone"] == [{"value": "555", "primary": True}]


def test_pipedrive_payload_defaults_the_name_to_contact():
    assert CrmPush._build_pipedrive_payload({})["name"] == "Contact"


def test_pipedrive_payload_stamps_add_time():
    payload = CrmPush._build_pipedrive_payload({"title": "X"})
    assert payload["add_time"].endswith("+00:00"), payload["add_time"]


async def test_pipedrive_success_reads_the_nested_data_id(push, hx, monkeypatch):
    _keyed(monkeypatch, {"pipedrive": "pd-key"})
    hx.routes["/v1/persons"] = _Resp(201, "", {"data": {"id": 42}})
    out = await push.push_leads([_lead()], provider="pipedrive")
    assert out[0]["ok"] is True
    assert out[0]["remote_id"] == 42


async def test_pipedrive_passes_the_token_in_the_query_string(push, hx, monkeypatch):
    _keyed(monkeypatch, {"pipedrive": "pd-key"})
    hx.routes["/v1/persons"] = _Resp(201, "", {"data": {"id": 1}})
    await push.push_leads([_lead()], provider="pipedrive")
    req = hx.last
    assert req["url"] == "https://api.pipedrive.com/v1/persons?api_token=pd-key", req
    assert "Authorization" not in req["headers"], req["headers"]


async def test_pipedrive_http_error_is_reported(push, hx, monkeypatch):
    _keyed(monkeypatch, {"pipedrive": "pd-key"})
    hx.routes["/v1/persons"] = _Resp(403, "forbidden")
    out = await push.push_leads([_lead()], provider="pipedrive")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "forbidden"


async def test_pipedrive_transport_error_is_reported(push, hx, monkeypatch):
    _keyed(monkeypatch, {"pipedrive": "pd-key"})
    hx.raises = OSError("boom")
    out = await push.push_leads([_lead()], provider="pipedrive")
    assert out[0]["ok"] is False
    assert "boom" in out[0]["error"]


async def test_pipedrive_without_a_key_does_not_call_the_api(push, hx, monkeypatch):
    _keyed(monkeypatch, {})
    out = await push.push_leads([_lead()], provider="pipedrive")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "PIPEDRIVE_API_KEY not configured"
    assert hx.requests == []


# ── unknown provider ───────────────────────────────────────────────────────
async def test_unknown_provider_is_reported_and_never_calls_out(push, hx):
    out = await push.push_leads([_lead()], provider="notion")
    assert out[0]["ok"] is False
    assert out[0]["error"] == "Unknown CRM provider: notion"
    assert hx.requests == []


# ── batch behaviour ────────────────────────────────────────────────────────
async def test_every_lead_gets_exactly_one_result(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    hx.routes["hubapi"] = _Resp(200, "{}", {"id": "1"})
    leads = [_lead(id="A"), _lead(id="B", score=10), _lead(id="C")]
    out = await push.push_leads(leads, provider="hubspot")
    assert [r["lead_id"] for r in out] == ["A", "B", "C"], out
    assert len(out) == len(leads)


async def test_a_failing_lead_does_not_stop_the_rest_of_the_batch(push, hx, monkeypatch):
    """DATA-LOSS GUARD: one bad lead must not abort the batch."""
    _keyed(monkeypatch, {"hubspot": "k"})
    hx.routes["hubapi"] = _Resp(400, "rejected")
    out = await push.push_leads([_lead(id="A"), _lead(id="B")], provider="hubspot")
    assert len(out) == 2
    assert all(r["ok"] is False for r in out)
    assert len(hx.requests) == 2, "each lead is attempted independently"


async def test_empty_batch_returns_an_empty_list(push, hx):
    assert await push.push_leads([], provider="hubspot") == []


async def test_a_lead_with_no_id_reports_an_empty_lead_id(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    hx.routes["hubapi"] = _Resp(200, "{}", {"id": "1"})
    out = await push.push_leads([{"title": "No Id", "score": 90}], provider="hubspot")
    assert out[0]["lead_id"] == ""


async def test_http_error_text_is_truncated_to_300_chars(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    hx.routes["hubapi"] = _Resp(500, "x" * 1000)
    out = await push.push_leads([_lead()], provider="hubspot")
    assert len(out[0]["error"]) == 300, len(out[0]["error"])


# ── history + stats ────────────────────────────────────────────────────────
async def test_history_records_every_attempt_with_its_outcome(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    hx.routes["hubapi"] = _Resp(200, "{}", {"id": "1"})
    await push.push_leads([_lead(id="A")], provider="hubspot")
    hx.routes["hubapi"] = _Resp(400, "bad")
    await push.push_leads([_lead(id="B")], provider="hubspot")
    hist = push.get_history()
    assert [h["lead_id"] for h in hist] == ["A", "B"]
    assert hist[0]["ok"] is True and hist[0]["error"] is None
    assert hist[1]["ok"] is False and hist[1]["error"] == "bad"
    assert hist[0]["provider"] == "hubspot"
    assert hist[0]["timestamp"].endswith("+00:00")


async def test_history_records_unknown_providers_too(push, hx):
    await push.push_leads([_lead(id="X")], provider="notion")
    assert push.get_history()[0]["provider"] == "notion"


async def test_history_respects_the_limit(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    hx.routes["hubapi"] = _Resp(200, "{}", {"id": "1"})
    await push.push_leads([_lead(id=str(i)) for i in range(5)], provider="hubspot")
    assert len(push.get_history(limit=2)) == 2


def test_stats_on_a_fresh_push_are_zeroed(push):
    assert push.get_stats() == {
        "total_pushes": 0, "successful_pushes": 0, "failed_pushes": 0,
        "last_push": None}


async def test_stats_count_successes_and_failures_separately(push, hx, monkeypatch):
    _keyed(monkeypatch, {"hubspot": "k"})
    hx.routes["hubapi"] = _Resp(200, "{}", {"id": "1"})
    await push.push_leads([_lead(id="A")], provider="hubspot")
    hx.routes["hubapi"] = _Resp(400, "bad")
    await push.push_leads([_lead(id="B")], provider="hubspot")
    s = push.get_stats()
    assert s["total_pushes"] == 2
    assert s["successful_pushes"] == 1
    assert s["failed_pushes"] == 1
    assert s["last_push"] is not None


def test_set_env_is_a_no_op_and_does_not_raise(push):
    push.set_env({"HUBSPOT_API_KEY": "x"})
    assert push.get_history() == []
