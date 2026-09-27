"""Tests for engine/enrichment/llm_enricher.py.

ANTHROPIC_URL / OPENAI_URL are module constants, so we point them at a real
local HTTP server. The provider-selection logic (_setup), request-body
construction, headers, fenced-JSON parsing and the HTTP-error paths all run
for real.
"""
import asyncio
import json

import pytest

import engine.enrichment.llm_enricher as llm_mod
from engine.enrichment.llm_enricher import LLMEnricher
from tests.support_http import LocalServer
from tests.support_fixtures import no_real_network  # noqa: F401


def run(coro):
    return asyncio.run(coro)


def anthropic_reply(payload: dict) -> dict:
    return {"id": "msg_1", "model": "claude-sonnet-4-20250514",
            "content": [{"type": "text", "text": json.dumps(payload)}]}


def openai_reply(payload: dict) -> dict:
    return {"id": "cmpl_1", "model": "gpt-4o-mini",
            "choices": [{"index": 0,
                         "message": {"role": "assistant",
                                     "content": json.dumps(payload)}}]}


@pytest.fixture
def vault(monkeypatch):
    keys = {}
    monkeypatch.setattr(llm_mod.KeyVault, "get",
                        staticmethod(lambda s: keys.get(s)))
    return keys


@pytest.fixture
def srv():
    with LocalServer() as s:
        yield s


@pytest.fixture
def both_urls(srv, monkeypatch):
    monkeypatch.setattr(llm_mod, "ANTHROPIC_URL", srv.url("/v1/messages"))
    monkeypatch.setattr(llm_mod, "OPENAI_URL", srv.url("/v1/chat/completions"))
    return srv.rec


# ── availability / provider selection ───────────────────────────────────────
def test_unavailable_without_any_key(vault):
    e = LLMEnricher()
    assert e.is_available() is False
    r = run(e.enrich("Acme", "roofing"))
    assert r.error == "No LLM API key configured (anthropic or openai)"
    assert r.email is None and r.confidence == 0.0


def test_anthropic_wins_when_both_keys_present(vault):
    vault["anthropic"] = "sk-ant"
    vault["openai"] = "sk-oai"
    e = LLMEnricher()
    assert e.is_available() is True
    e._setup()
    assert e._provider == "anthropic"
    assert e._api_key == "sk-ant"


def test_openai_used_when_only_openai_key(vault):
    vault["openai"] = "sk-oai"
    e = LLMEnricher()
    e._setup()
    assert e._provider == "openai"
    assert e._api_key == "sk-oai"


def test_setup_is_idempotent(vault):
    vault["anthropic"] = "sk-ant"
    e = LLMEnricher()
    e._setup()
    vault["anthropic"] = "rotated"
    e._setup()
    assert e._api_key == "sk-ant"


def test_model_names_default_and_are_configurable(vault):
    vault["anthropic"] = "a"
    vault["openai"] = "o"
    e = LLMEnricher({"anthropic_model": "claude-opus-x", "openai_model": "gpt-4o"})
    e._setup()
    assert e._provider == "anthropic"
    assert e._model_name() == "claude-opus-x"
    e._provider = "openai"
    assert e._model_name() == "gpt-4o"
    # _model_name keys off _provider, which is None before _setup() -> openai default
    assert LLMEnricher()._model_name() == "gpt-4o-mini"


def test_call_llm_returns_none_when_no_provider_configured(vault):
    assert run(LLMEnricher()._call_llm("s", "p")) is None


# ── Anthropic request shape ─────────────────────────────────────────────────
def test_anthropic_request_carries_the_right_headers_and_body(vault, both_urls):
    vault["anthropic"] = "sk-ant-123"
    e = LLMEnricher()
    both_urls.add("POST", "/v1/messages",
                  anthropic_reply({"contact_name": "Dana Moxley"}))
    out = run(e._call_llm("system-msg", "prompt-msg"))
    assert "Dana Moxley" in out
    body = both_urls.last_body("POST", "/v1/messages")
    assert body["model"] == "claude-sonnet-4-20250514"
    assert body["max_tokens"] == 2000
    assert body["system"] == "system-msg"
    assert body["messages"] == [{"role": "user", "content": "prompt-msg"}]
    hdrs = both_urls.requests[-1]["headers"]
    assert hdrs["x-api-key"] == "sk-ant-123"
    assert hdrs["anthropic-version"] == "2023-06-01"


# ── OpenAI request shape ────────────────────────────────────────────────────
def test_openai_request_uses_bearer_and_system_message(vault, both_urls):
    vault["openai"] = "sk-oai-999"
    e = LLMEnricher()
    both_urls.add("POST", "/v1/chat/completions",
                  openai_reply({"contact_name": "Sam Rivera"}))
    out = run(e._call_llm("system-msg", "prompt-msg"))
    assert "Sam Rivera" in out
    body = both_urls.last_body("POST", "/v1/chat/completions")
    assert body["model"] == "gpt-4o-mini"
    assert body["messages"] == [
        {"role": "system", "content": "system-msg"},
        {"role": "user", "content": "prompt-msg"},
    ]
    assert both_urls.requests[-1]["headers"]["authorization"] == "Bearer sk-oai-999"


# ── LLM HTTP error paths ────────────────────────────────────────────────────
@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
def test_anthropic_http_error_returns_none_not_an_exception(vault, both_urls, status):
    vault["anthropic"] = "sk-ant"
    both_urls.add("POST", "/v1/messages", {"error": "boom"}, status=status)
    assert run(LLMEnricher()._call_llm("s", "p")) is None


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
def test_openai_http_error_returns_none_not_an_exception(vault, both_urls, status):
    vault["openai"] = "sk-oai"
    both_urls.add("POST", "/v1/chat/completions", {"error": "boom"}, status=status)
    assert run(LLMEnricher()._call_llm("s", "p")) is None


def test_anthropic_rate_limited_enrich_surfaces_error_and_no_data(vault, both_urls):
    vault["anthropic"] = "sk-ant"
    both_urls.add("POST", "/v1/messages", {"error": "rate limit"}, status=429)
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.error == "LLM returned no response"
    assert r.email is None and r.phone is None
    assert r.confidence == 0.0


# ── enrich() parsing ────────────────────────────────────────────────────────
FULL = {
    "contact_name": "Dana Moxley", "title": "Owner",
    "phone": "+1 (555) 010-1234", "email": "dana@acmeroofing.com",
    "address": "100 Main St", "city": "Austin", "state": "TX", "zip": "78701",
    "employee_count": 12, "revenue": "$1M-$5M", "year_founded": 2009,
    "confidence": 0.8,
}


def test_enrich_parses_a_well_formed_anthropic_reply(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages", anthropic_reply(FULL))
    r = run(LLMEnricher().enrich("Acme Roofing", "roofing", location="Austin, TX"))
    assert r.contact_name == "Dana Moxley"
    assert r.title == "Owner"
    assert r.email == "dana@acmeroofing.com"
    assert r.phone == "+1 (555) 010-1234"
    assert r.address == "100 Main St"
    assert r.city == "Austin" and r.state == "TX" and r.zip == "78701"
    assert r.employee_count == 12
    assert r.revenue == "$1M-$5M"
    assert r.year_founded == 2009
    assert r.confidence == 0.8
    assert r.sources == ["llm:anthropic"]
    assert r.error is None


def test_enrich_parses_a_well_formed_openai_reply(vault, both_urls):
    vault["openai"] = "k"
    both_urls.add("POST", "/v1/chat/completions", openai_reply(FULL))
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.email == "dana@acmeroofing.com"
    assert r.sources == ["llm:openai"]


def test_prompt_includes_trade_location_and_raw_text(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages", anthropic_reply(FULL))
    run(LLMEnricher().enrich("Acme", "roofing", location="Austin, TX",
                             raw_text="call us at 555-010-1234"))
    prompt = both_urls.last_body("POST", "/v1/messages")["messages"][0]["content"]
    assert "Acme" in prompt and "roofing" in prompt
    assert "Austin, TX" in prompt
    assert "call us at 555-010-1234" in prompt


def test_prompt_states_the_placeholder_when_no_raw_text(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages", anthropic_reply(FULL))
    run(LLMEnricher().enrich("Acme", "roofing"))
    prompt = both_urls.last_body("POST", "/v1/messages")["messages"][0]["content"]
    assert "Location: unknown" in prompt
    assert "No raw data provided." in prompt


def test_raw_text_is_truncated_to_4000_chars_in_the_prompt(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages", anthropic_reply(FULL))
    run(LLMEnricher().enrich("Acme", "roofing", raw_text="X" * 9000))
    prompt = both_urls.last_body("POST", "/v1/messages")["messages"][0]["content"]
    assert "X" * 4000 in prompt
    assert "X" * 4001 not in prompt


def test_markdown_fenced_json_is_unwrapped(vault, both_urls):
    vault["anthropic"] = "k"
    fenced = "```json\n" + json.dumps(FULL) + "\n```"
    both_urls.add("POST", "/v1/messages",
                  {"content": [{"type": "text", "text": fenced}]})
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.email == "dana@acmeroofing.com"
    assert r.error is None


def test_bare_fence_with_no_language_tag_is_unwrapped(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages",
                  {"content": [{"type": "text",
                                "text": "```\n" + json.dumps(FULL) + "\n```"}]})
    assert run(LLMEnricher().enrich("Acme", "roofing")).email == "dana@acmeroofing.com"


def test_unparsable_llm_output_yields_error_and_keeps_no_fields(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages",
                  {"content": [{"type": "text", "text": "I could not find that."}]})
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.error is not None and "parse failed" in r.error
    assert r.email is None and r.phone is None and r.contact_name is None
    assert r.confidence == 0.0
    assert r.raw_data["llm_raw_response"] == "I could not find that."


def test_truncated_json_from_a_cutoff_response_is_reported_not_guessed(vault, both_urls):
    vault["anthropic"] = "k"
    cut = json.dumps(FULL)[:40]
    both_urls.add("POST", "/v1/messages", {"content": [{"type": "text", "text": cut}]})
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.email is None, "a half-parsed record must not yield an email"
    assert "parse failed" in r.error


def test_null_fields_in_the_llm_reply_are_left_absent(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages",
                  anthropic_reply({"contact_name": None, "title": None,
                                   "email": None, "confidence": 0.1}))
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.contact_name is None and r.email is None
    assert r.confidence == 0.1
    assert r.sources == ["llm:anthropic"]


def test_null_numeric_fields_do_not_become_zero(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages",
                  anthropic_reply({"employee_count": None, "year_founded": None}))
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.employee_count is None and r.year_founded is None


def test_non_numeric_headcount_is_rejected_and_reported(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages",
                  anthropic_reply({"employee_count": "about a dozen"}))
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.employee_count is None
    assert "parse failed" in r.error


def test_whitespace_only_reply_is_reported_as_unparsable_not_invented(vault, both_urls):
    """A blank-but-nonempty reply is truthy, so it reaches the JSON parser and
    fails loudly. It must NOT be reported as success with empty fields."""
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages", {"content": [{"type": "text", "text": "   "}]})
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.error is not None and "parse failed" in r.error
    assert r.email is None and r.contact_name is None
    assert r.sources == []


def test_anthropic_empty_content_block_does_not_crash(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages", {"content": []})
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.error == "LLM returned no response"
    assert r.email is None


def test_openai_empty_choices_does_not_crash(vault, both_urls):
    vault["openai"] = "k"
    both_urls.add("POST", "/v1/chat/completions", {"choices": []})
    r = run(LLMEnricher().enrich("Acme", "roofing"))
    assert r.error == "LLM returned no response"
    assert r.email is None


# ── CRITICAL: the LLM must not be allowed to invent an email ────────────────
def test_llm_cannot_invent_an_email_when_it_says_it_cannot_find_one(vault, both_urls):
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages", {"content": [{
        "type": "text",
        "text": json.dumps({"contact_name": "Dana", "email": None,
                            "confidence": 0.2})}]})
    r = run(LLMEnricher().enrich("Acme Roofing", "roofing"))
    assert r.email is None
    assert not (r.email or "").strip()
    assert r.contact_name == "Dana"


def test_email_is_never_derived_from_the_website_or_business_name(vault, both_urls):
    """No domain->mailbox pattern generation anywhere in this path."""
    vault["anthropic"] = "k"
    both_urls.add("POST", "/v1/messages", anthropic_reply({"contact_name": "Dana"}))
    r = run(LLMEnricher().enrich("Acme Roofing", "roofing",
                                 website="https://acmeroofing.com"))
    assert r.email is None
    blob = " ".join(str(v) for v in r.__dict__.values())
    assert "acmeroofing.com" not in blob
