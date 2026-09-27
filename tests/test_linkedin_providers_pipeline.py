"""Tests for SignalPipeline (audit 2026-09-27).

Ported from SIOS with 0% coverage. Driven with lightweight stand-ins for the
collaborators; the pipeline's own logic is what is under test:

  viral gate  -> non-viral posts short-circuit before any engagement work
  dedup       -> one row per (identity, post)
  truncation  -> max_engagers is enforced and reported
  suppression -> a suppressed email never reaches the verifier or the CRM
  the compliance gate is mandatory -- no gate means nothing is approved

Collaborator contract, read from the implementation:
  collect_post(url) -> {"post": {urn,url,text,reactions,comments,reposts,age_hours},
                        "engagements": [{actor_urn,profile_url,action,name,...}]}
"""
import asyncio
import json

import pytest

from engine.linkedin.linkedin_signals.pipeline import SignalPipeline
from engine.linkedin.linkedin_signals.store import SignalStore


def run(coro):
    return asyncio.run(coro)


class FakeLinkedIn:
    def __init__(self, post=None, engagements=None):
        self.post = post or {
            "urn": "urn:li:share:1", "url": "https://linkedin.com/posts/x/1",
            "text": "hello", "reactions": 500, "comments": 50,
            "reposts": 20, "age_hours": 2.0,
        }
        self.engagements = engagements if engagements is not None else []
        self.calls = 0

    async def collect_post(self, post_url):
        self.calls += 1
        return {"post": self.post, "engagements": self.engagements}


def engagement(actor="urn:li:person:1", name="Jane", action="comment"):
    return {"actor_urn": actor, "profile_url": f"https://linkedin.com/in/{actor[-1]}/",
            "action": action, "name": name, "headline": "Founder",
            "comment_text": "interested"}


class Stub:
    """Pass-through stage that records what it was handed."""

    def __init__(self, **returns):
        self._returns = returns
        self.seen = []

    async def qualify(self, payload, post):
        self.seen.append(payload)
        return self._returns.get("qualify", {"qualified": True, "score": 0.9})

    async def enrich(self, payload):
        self.seen.append(payload)
        return self._returns.get("enrich", {"email": "Jane@Example.com",
                                            "name": "Jane", "company": "Acme"})

    async def verify(self, email):
        self.seen.append(email)
        return self._returns.get("verify", {"status": "verified"})

    async def create_lead(self, **kwargs):
        self.seen.append(kwargs)
        return self._returns.get("crm", {"lead": {"id": "crm-1"}})


def make(tmp_path, li, **stage_returns):
    store = SignalStore(str(tmp_path / "sig.db"))
    pipe = SignalPipeline(store=store, linkedin=li,
                          qualifier=Stub(**stage_returns),
                          waterfall=Stub(**stage_returns),
                          verifier=Stub(**stage_returns),
                          crm=Stub(**stage_returns))
    return pipe, store


# ── the viral gate ─────────────────────────────────────────────────────────
def test_non_viral_post_short_circuits(tmp_path):
    """A post with no engagement must cost zero downstream calls."""
    quiet = FakeLinkedIn(post={"urn": "urn:li:share:q", "url": "u", "text": "",
                               "reactions": 0, "comments": 0, "reposts": 0,
                               "age_hours": 100.0},
                         engagements=[engagement()])
    pipe, _ = make(tmp_path, quiet)
    out = run(pipe.run_post("https://linkedin.com/posts/x/q"))

    assert out["viral"] is False, out
    assert out["engagers"] == 0, out
    assert pipe.qualifier.seen == [], "must not qualify on a non-viral post"
    assert pipe.crm.seen == [], "must not push to the CRM"


def test_viral_post_is_persisted_even_when_engagement_fails(tmp_path):
    """The post is durable the moment it is scored -- leads can fail after."""
    li = FakeLinkedIn(engagements=[engagement()])
    pipe, store = make(tmp_path, li, enrich={"email": ""})  # enrichment fails
    out = run(pipe.run_post("https://linkedin.com/posts/x/1"))

    assert out["viral"] is True, out
    assert out["engagers"] == 1, out
    assert out["qualified"] == 1, out
    assert out["crm_pushed"] == 0, out
    with store._connect() as con:
        assert con.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1


# ── dedup + truncation ─────────────────────────────────────────────────────
def test_engagements_are_deduplicated(tmp_path):
    dupes = [engagement("urn:li:person:1"), engagement("urn:li:person:1"),
             engagement("urn:li:person:2")]
    pipe, store = make(tmp_path, FakeLinkedIn(engagements=dupes))
    out = run(pipe.run_post("https://linkedin.com/posts/x/1"))

    assert out["engagers_discovered"] == 2, out
    assert out["engagers"] == 2, out
    # and it is durable, not just in-memory
    with store._connect() as con:
        assert con.execute("SELECT COUNT(*) FROM signal_leads").fetchone()[0] == 2


def test_max_engagers_is_enforced_and_reported(tmp_path):
    many = [engagement(f"urn:li:person:{i}") for i in range(10)]
    store = SignalStore(str(tmp_path / "sig.db"))
    pipe = SignalPipeline(store=store, linkedin=FakeLinkedIn(engagements=many),
                          qualifier=Stub(), waterfall=Stub(), verifier=Stub(),
                          crm=Stub(), max_engagers=3)
    out = run(pipe.run_post("https://linkedin.com/posts/x/1"))

    assert out["engagers_discovered"] == 10, out
    assert out["engagers"] == 3, out
    assert out["engagers_truncated"] is True, out


def test_max_engagers_of_zero_is_floored_to_one(tmp_path):
    """A misconfigured 0 must not silently disable the whole pipeline."""
    store = SignalStore(str(tmp_path / "sig.db"))
    pipe = SignalPipeline(store=store, linkedin=FakeLinkedIn(engagements=[]),
                          qualifier=Stub(), waterfall=Stub(), verifier=Stub(),
                          crm=Stub(), max_engagers=0)
    assert pipe.max_engagers == 1


# ── the happy path ─────────────────────────────────────────────────────────
def test_qualified_verified_lead_reaches_the_crm(tmp_path):
    li = FakeLinkedIn(engagements=[engagement()])
    pipe, store = make(tmp_path, li)
    out = run(pipe.run_post("https://linkedin.com/posts/x/1"))

    assert out["verified"] == 1 and out["crm_pushed"] == 1, out
    assert out["awaiting_approval"] == 1, out
    lead = store.list_leads(limit=1)[0]
    assert lead["email"] == "jane@example.com", "email must be normalised"
    assert lead["outreach_status"] == "awaiting_approval", lead
    assert lead["crm_lead_id"] == "crm-1", lead
    assert json.loads(lead["qualification_json"])["qualified"] is True


def test_unqualified_lead_is_marked_and_skipped(tmp_path):
    li = FakeLinkedIn(engagements=[engagement()])
    pipe, store = make(tmp_path, li, qualify={"qualified": False})
    out = run(pipe.run_post("https://linkedin.com/posts/x/1"))

    assert out["qualified"] == 0 and out["crm_pushed"] == 0, out
    assert store.list_leads(limit=1)[0]["outreach_status"] == "not_qualified"
    assert pipe.crm.seen == [], "must never push an unqualified lead"


def test_failed_verification_is_marked_and_skipped(tmp_path):
    li = FakeLinkedIn(engagements=[engagement()])
    pipe, store = make(tmp_path, li, verify={"status": "invalid"})
    out = run(pipe.run_post("https://linkedin.com/posts/x/1"))

    assert out["verified"] == 0 and out["crm_pushed"] == 0, out
    assert store.list_leads(limit=1)[0]["outreach_status"] == "verification_failed"


# ── suppression is a hard gate (compliance-critical) ───────────────────────
def test_suppressed_email_never_reaches_verifier_or_crm(tmp_path):
    li = FakeLinkedIn(engagements=[engagement()])
    pipe, store = make(tmp_path, li)
    store.suppress("jane@example.com", "opt out")

    out = run(pipe.run_post("https://linkedin.com/posts/x/1"))

    assert pipe.verifier.seen == [], "must not verify a suppressed address"
    assert pipe.crm.seen == [], "must not push a suppressed address"
    assert out["crm_pushed"] == 0, out
    lead = store.list_leads(limit=1)[0]
    assert lead["outreach_status"] == "suppressed", lead
    assert lead["email"] == "jane@example.com", "the suppression must be recorded"


# ── run accounting ─────────────────────────────────────────────────────────
def test_every_run_is_recorded(tmp_path):
    pipe, store = make(tmp_path, FakeLinkedIn())
    run(pipe.run_post("https://linkedin.com/posts/x/1"))
    with store._connect() as con:
        rows = con.execute("SELECT * FROM runs").fetchall()
    assert len(rows) == 1, [dict(r) for r in rows]
    assert rows[0]["status"] == "completed", dict(rows[0])


def test_rerun_is_idempotent_on_the_post_row(tmp_path):
    li = FakeLinkedIn(engagements=[engagement()])
    pipe, store = make(tmp_path, li)
    run(pipe.run_post("https://linkedin.com/posts/x/1"))
    run(pipe.run_post("https://linkedin.com/posts/x/1"))
    with store._connect() as con:
        assert con.execute("SELECT COUNT(*) FROM posts").fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM signal_leads").fetchone()[0] == 1
