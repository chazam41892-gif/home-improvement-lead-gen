"""Regression test for the nurture KeyError crash (audit 2026-09-27).

engine/nurture.py appends `incoming_reply` and `ai_response` log entries to
seq.actions with NO `delay_minutes` key. get_due_actions() read that key
unconditionally, so the background _nurture_loop raised KeyError on every such
sequence and aborted the entire due-action pass — silently stopping all outreach.
"""
import pytest

from engine.nurture import NurtureEngine


class _Seq:
    """Minimal stand-in for NurtureSequence with the shapes the code actually builds."""

    def __init__(self, actions, created_at, current_step=0):
        self.id = "seq_test"
        self.actions = actions
        self.current_step = current_step
        self.created_at = created_at
        self.completed = False
        self.lead_name = "Jane"
        self.industry = "roofing"


def test_due_actions_ignores_unscheduled_reply_entries(monkeypatch):
    """An incoming_reply entry has no delay_minutes and must be skipped, not crash."""
    from datetime import datetime, timedelta
    eng = NurtureEngine()
    created = (datetime.now() - timedelta(days=2)).isoformat()

    seq = _Seq([{"type": "incoming_reply",
                 "message": "sure, call me",
                 "sent_at": datetime.now().isoformat()}],
               created_at=created, current_step=0)
    # refresh=False is required: the default refresh=True re-reads the DB and
    # would replace this injected sequence with real persisted ones.
    monkeypatch.setattr(eng, "_sequences", {"seq_test": seq})

    # Must not raise.
    due = eng.get_due_actions(refresh=False)
    assert due == [], "an unscheduled log entry must not become a due action"


def test_due_actions_still_finds_real_scheduled_step(monkeypatch):
    """The fix must not break normal scheduling."""
    from datetime import datetime, timedelta
    eng = NurtureEngine()
    created = (datetime.now() - timedelta(days=2)).isoformat()

    seq = _Seq([{"type": "email", "delay_minutes": 5, "template": "hi {name}"}],
               created_at=created, current_step=0)
    # refresh=False is required: the default refresh=True re-reads the DB and
    # would replace this injected sequence with real persisted ones.
    monkeypatch.setattr(eng, "_sequences", {"seq_test": seq})

    due = eng.get_due_actions(refresh=False)
    assert len(due) == 1, f"expected the overdue email, got {due}"
    assert due[0]["type"] == "email"


def test_due_actions_respects_future_delay(monkeypatch):
    from datetime import datetime, timedelta
    eng = NurtureEngine()
    created = datetime.now().isoformat()  # just created, 1440min delay -> not due

    seq = _Seq([{"type": "call", "delay_minutes": 1440, "template": "call {name}"}],
               created_at=created, current_step=0)
    # refresh=False is required: the default refresh=True re-reads the DB and
    # would replace this injected sequence with real persisted ones.
    monkeypatch.setattr(eng, "_sequences", {"seq_test": seq})

    assert eng.get_due_actions(refresh=False) == []


def test_due_actions_skips_sent_actions(monkeypatch):
    from datetime import datetime, timedelta
    eng = NurtureEngine()
    created = (datetime.now() - timedelta(days=2)).isoformat()

    seq = _Seq([{"type": "email", "delay_minutes": 5, "template": "x", "sent": True}],
               created_at=created, current_step=0)
    # refresh=False is required: the default refresh=True re-reads the DB and
    # would replace this injected sequence with real persisted ones.
    monkeypatch.setattr(eng, "_sequences", {"seq_test": seq})

    assert eng.get_due_actions(refresh=False) == []


def test_due_actions_tolerates_bad_created_at(monkeypatch):
    eng = NurtureEngine()
    seq = _Seq([{"type": "email", "delay_minutes": 5, "template": "x"}],
               created_at="not-a-date", current_step=0)
    # refresh=False is required: the default refresh=True re-reads the DB and
    # would replace this injected sequence with real persisted ones.
    monkeypatch.setattr(eng, "_sequences", {"seq_test": seq})

    assert eng.get_due_actions(refresh=False) == []
