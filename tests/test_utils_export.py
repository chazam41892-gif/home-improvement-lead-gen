"""Tests for engine/utils/export.py — CSV/JSON serialisation of lead lists (audit 2026-09-27).

The output of these three functions is what a customer actually downloads, so the
tests assert the *format on disk*: exact column order, CRLF line endings, the
200-char snippet cap, RFC-4180 quoting of commas/quotes/newlines, which keys the
JSON exporter drops, and the shape of the timestamped filename.

Signatures were read from the implementation:
  export_to_csv(leads) -> str  (empty string for an empty list, NOT a header)
  export_to_json(leads) -> str (always a JSON array, "[]" for empty)
  export_timestamped_filename(prefix="leads", ext="csv") -> str
"""
import csv
import io
import json
import re

from engine.utils.export import (
    export_timestamped_filename,
    export_to_csv,
    export_to_json,
)

EXPECTED_COLUMNS = [
    "id", "title", "url", "snippet", "industry",
    "location", "score", "contact_score", "business_score",
    "industry_score", "location_score", "enrichment_score",
    "source", "found_at", "email", "phone",
]

FULL_LEAD = {
    "id": "abc123",
    "title": "Acme Roofing",
    "url": "https://acme.com",
    "snippet": "Licensed roofer in Austin",
    "industry": "roofing",
    "location": "Austin, TX",
    "score": 87.5,
    "contact_score": 100.0,
    "business_score": 40.0,
    "industry_score": 80.0,
    "location_score": 70.0,
    "enrichment_score": 55.0,
    "source": "exa",
    "found_at": "2026-09-27T04:00:00",
    "email": "jane@acme.com",
    "phone": "512-555-1234",
}


def _parse_csv(text):
    return list(csv.reader(io.StringIO(text)))


# ── export_to_csv ───────────────────────────────────────────────────────────
def test_export_csv_of_no_leads_is_the_empty_string_not_a_header():
    assert export_to_csv([]) == ""


def test_export_csv_writes_the_exact_column_order():
    rows = _parse_csv(export_to_csv([FULL_LEAD]))
    assert rows[0] == EXPECTED_COLUMNS


def test_export_csv_row_carries_every_value():
    rows = _parse_csv(export_to_csv([FULL_LEAD]))
    assert len(rows) == 2
    assert rows[1] == [
        "abc123", "Acme Roofing", "https://acme.com", "Licensed roofer in Austin",
        "roofing", "Austin, TX", "87.5", "100.0", "40.0", "80.0", "70.0", "55.0",
        "exa", "2026-09-27T04:00:00", "jane@acme.com", "512-555-1234",
    ]


def test_export_csv_defaults_missing_fields_instead_of_raising():
    """A lead missing every optional key must still produce a full-width row:
    strings become empty, scores become the literal 0."""
    rows = _parse_csv(export_to_csv([{"title": "Only A Title"}]))
    assert rows[1][1] == "Only A Title"
    assert rows[1][0] == ""  # id
    assert rows[1][6:12] == ["0", "0", "0", "0", "0", "0"]  # six score columns


def test_export_csv_drops_keys_that_are_not_columns():
    """extrasaction="ignore" means a stray key is dropped, not written or fatal."""
    lead = dict(FULL_LEAD, score_breakdown={"total": 1}, notes="private", _capture_source="pg")
    out = export_to_csv([lead])
    assert "score_breakdown" not in out
    assert "private" not in out
    assert "_capture_source" not in out
    assert _parse_csv(out)[0] == EXPECTED_COLUMNS


def test_export_csv_truncates_snippet_to_200_chars():
    lead = dict(FULL_LEAD, snippet="s" * 250)
    assert _parse_csv(export_to_csv([lead]))[1][3] == "s" * 200
    # A snippet of exactly 200 survives untouched.
    assert _parse_csv(export_to_csv([dict(FULL_LEAD, snippet="s" * 200)]))[1][3] == "s" * 200


def test_export_csv_quotes_commas_quotes_and_newlines():
    lead = dict(FULL_LEAD, title='Doe, Jane "JJ"', snippet="line1\nline2")
    raw = export_to_csv([lead])
    # RFC-4180: embedded quotes are doubled and the field is wrapped in quotes;
    # a newline inside a field means the raw text has more physical lines than rows.
    assert '"Doe, Jane ""JJ"""' in raw
    assert '"line1\nline2"' in raw
    # Round-tripping through a real CSV reader recovers the original strings, and
    # the embedded newline does NOT split the record into two rows.
    rows = _parse_csv(raw)
    assert len(rows) == 2
    assert rows[1][1] == 'Doe, Jane "JJ"'
    assert rows[1][3] == "line1\nline2"


def test_export_csv_uses_crlf_line_endings():
    assert export_to_csv([FULL_LEAD]).endswith("\r\n")


def test_export_csv_preserves_zero_scores_as_zero_not_empty():
    """A real score of 0 must not be confused with a missing score."""
    row = _parse_csv(export_to_csv([dict(FULL_LEAD, score=0, contact_score=0)]))[1]
    assert row[6:8] == ["0", "0"]


def test_export_csv_writes_one_row_per_lead_in_order():
    leads = [dict(FULL_LEAD, id=f"id{i}", title=f"Lead {i}") for i in range(5)]
    rows = _parse_csv(export_to_csv(leads))
    assert [r[0] for r in rows[1:]] == ["id0", "id1", "id2", "id3", "id4"]


# ── export_to_json ──────────────────────────────────────────────────────────
def test_export_json_of_no_leads_is_an_empty_array():
    assert export_to_json([]) == "[]"
    assert json.loads(export_to_json([])) == []


def test_export_json_round_trips_a_full_lead():
    assert json.loads(export_to_json([FULL_LEAD])) == [FULL_LEAD]


def test_export_json_drops_none_and_empty_string_keys_only():
    """The filter is `v is not None and v != ""` — so 0 and False are KEPT."""
    out = json.loads(export_to_json([{"a": 1, "b": None, "c": "", "d": 0, "e": False}]))
    assert out == [{"a": 1, "d": 0, "e": False}]


def test_export_json_keeps_nested_structures_and_empty_containers():
    """`{}` and `[]` are falsy but neither is None nor "", so they survive."""
    out = json.loads(export_to_json([{"a": {}, "b": [], "c": None}]))
    assert out == [{"a": {}, "b": []}]


def test_export_json_is_indented_by_two_spaces():
    assert export_to_json([{"a": 1}]).startswith("[\n  {")


def test_export_json_stringifies_values_it_cannot_serialise():
    """default=str keeps a value json can't encode from crashing the export — it
    degrades to a string rather than raising mid-download. Bytes are used because
    their repr is deterministic (unlike a set's)."""
    out = json.loads(export_to_json([{"raw": b"\\x00\\xff"}]))
    assert out == [{"raw": repr(b"\\x00\\xff")}]


def test_export_json_stringifies_a_set_without_raising():
    """A set's repr order is not deterministic, so assert only the shape."""
    out = json.loads(export_to_json([{"tags": {"a", "b"}}]))
    assert isinstance(out[0]["tags"], str)
    assert out[0]["tags"].startswith("{") and out[0]["tags"].endswith("}")
    assert set("ab") <= set(out[0]["tags"])


def test_export_json_output_is_reloadable_by_the_capture_persistence_path():
    """The persisted leads table stores score_breakdown as JSON, so a re-export
    must be loadable and still carry the breakdown."""
    lead = dict(FULL_LEAD, score_breakdown={"total": 87.5, "contact_completeness": 100.0})
    reloaded = json.loads(export_to_json([lead]))
    assert reloaded[0]["score_breakdown"]["total"] == 87.5


# ── export_timestamped_filename ─────────────────────────────────────────────
def test_timestamped_filename_default_prefix_and_extension():
    name = export_timestamped_filename()
    assert re.fullmatch(r"leads_\d{8}_\d{6}\.csv", name), name


def test_timestamped_filename_honours_prefix_and_extension():
    name = export_timestamped_filename("prospects", "json")
    assert re.fullmatch(r"prospects_\d{8}_\d{6}\.json", name), name


def test_timestamped_filename_uses_a_plausible_current_date():
    """The stamp is local time formatted %Y%m%d_%H%M%S — check today's date is in it."""
    from datetime import datetime

    stamp = export_timestamped_filename().split("_")[1]
    assert stamp == datetime.now().strftime("%Y%m%d"), stamp


def test_two_timestamps_within_the_same_second_are_allowed_to_match():
    """Documents that the filename is second-granular, so two exports in the same
    second collide — the function does not disambiguate."""
    a = export_timestamped_filename()
    b = export_timestamped_filename()
    assert a[6:20] <= b[6:20]
