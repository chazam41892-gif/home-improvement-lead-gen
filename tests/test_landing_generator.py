"""Tests for engine/landing.py — the generated landing-page HTML (audit 2026-09-27).

This module renders a complete, self-contained HTML page from a config dict. The
dangerous parts are the ones that take operator input: unescaped text would be
XSS on a page every captured lead is sent to, and a javascript: hero image would
execute. So these tests assert on the actual generated HTML — escaping, the colour
and URL validators, form-field rendering, and the SQLite round-trip of pages.

Every generator is pointed at a temp SQLite file via Database.set_db_file, so
nothing here writes to the repo's data/lead_gen.db.
"""
from contextlib import closing

import pytest

from engine.database import Database
from engine.landing import (
    _COLOR_RE,
    _URL_SCHEME_RE,
    LandingPageGenerator,
)


@pytest.fixture(scope="session")
def landing_db(tmp_path_factory):
    """Create the schema once; re-running the full initialize() per test costs ~3s.

    Database.db_file is a CLASS attribute, so this must be restored on teardown:
    leaving a stray temp path installed would silently re-point every later test
    in the session at a database that no longer exists.
    """
    original = Database.db_file
    Database.set_db_file(str(tmp_path_factory.mktemp("landing") / "landing.db"))
    Database.initialize()
    path = Database.db_file
    try:
        yield path
    finally:
        Database.set_db_file(original)


@pytest.fixture
def gen(landing_db, monkeypatch):
    """A generator backed by a throwaway database, wiped clean for this test."""
    monkeypatch.setattr(Database, "db_file", landing_db)
    with closing(Database.get_connection()) as conn:
        conn.execute("DELETE FROM landing_pages")
        conn.commit()
    return LandingPageGenerator()


# ── the two input validators ────────────────────────────────────────────────
@pytest.mark.parametrize("color", [
    "#fff", "#ffffff", "#6366f1",
    "rgb(10, 20, 30)", "hsl(10, 20%, 30%)",
])
def test_color_validator_accepts_hex_rgb_and_hsl(color):
    assert _COLOR_RE.match(color), color


@pytest.mark.parametrize("color", ["red", "#gggggg", "", "#ffff", "rgb(300%, 1, 2)", "#6366f1;"])
def test_color_validator_rejects_everything_else(color):
    assert not _COLOR_RE.match(color), color


@pytest.mark.parametrize("url", ["http://x", "https://x", "HTTPS://X"])
def test_url_scheme_validator_accepts_http_and_https_any_case(url):
    assert _URL_SCHEME_RE.match(url), url


@pytest.mark.parametrize("url", ["ftp://x", "javascript:alert(1)", "//x.com", "", "/relative.png"])
def test_url_scheme_validator_rejects_non_http_schemes(url):
    assert not _URL_SCHEME_RE.match(url), url


# ── static HTML builders ────────────────────────────────────────────────────
def test_benefits_html_escapes_the_benefit_text():
    html = LandingPageGenerator._build_benefits_html(["5-Star & <b>Best</b>"])
    assert "5-Star &amp; &lt;b&gt;Best&lt;/b&gt;" in html
    assert "<b>Best</b>" not in html


def test_benefits_html_cycles_through_four_icons_in_order():
    html = LandingPageGenerator._build_benefits_html(["a", "b", "c", "d", "e"])
    icons = [chunk.split("</div>")[0]
             for chunk in html.split('<div class="benefit-icon">')[1:]]
    assert icons == ["✅", "\U0001f3ed", "\U0001f91d", "\U0001f3e0", "✅"]
    assert html.count('class="benefit-card"') == 5


def test_benefits_html_of_no_benefits_is_empty():
    assert LandingPageGenerator._build_benefits_html([]) == ""


def test_trust_html_escapes_text_and_defaults_a_missing_icon():
    html = LandingPageGenerator._build_trust_html(
        [{"icon": "★", "text": 'BBB "A+" & up'}, {"text": "no icon key"}]
    )
    assert 'BBB &quot;A+&quot; &amp; up' in html
    # The second badge has no icon key, so it falls back to the default check mark.
    assert html.count('class="trust-badge"') == 2
    assert html.split('class="icon">')[2].startswith("✅")


def test_trust_html_of_no_signals_is_empty():
    assert LandingPageGenerator._build_trust_html([]) == ""


def test_form_fields_html_renders_a_required_input():
    html = LandingPageGenerator._build_form_fields_html(
        [{"name": "name", "label": "Full Name", "type": "text", "required": True}]
    )
    assert '<label class="required" for="name">Full Name</label>' in html
    assert 'type="text" id="name" name="name" required>' in html
    assert 'id="name_error">Please enter your full name.</div>' in html


def test_form_fields_html_renders_a_textarea_without_the_required_attribute():
    html = LandingPageGenerator._build_form_fields_html(
        [{"name": "bio", "label": "Project Description", "type": "textarea"}]
    )
    assert '<textarea class="form-input" id="bio" name="bio"></textarea>' in html
    assert "required" not in html
    # The label has no `required` class and the error id is still wired up.
    assert '<label for="bio">' in html
    assert 'id="bio_error"' in html


def test_form_fields_html_falls_back_to_text_and_empty_label():
    html = LandingPageGenerator._build_form_fields_html([{"name": "z", "type": "weird"}])
    assert 'type="weird"' in html  # the caller's type is passed through, not validated
    assert '<label for="z"></label>' in html


def test_form_fields_html_strips_a_trailing_period_from_the_error_message():
    html = LandingPageGenerator._build_form_fields_html([{"name": "bio", "label": "Bio."}])
    assert ">Please enter your bio.</div>" in html


def test_form_fields_html_of_no_fields_is_empty():
    assert LandingPageGenerator._build_form_fields_html([]) == ""


def test_default_form_fields_cover_name_phone_email_address_and_description():
    names = [f["name"] for f in LandingPageGenerator._default_form_fields()]
    assert names == ["name", "phone", "email", "address", "project_description"]
    required = {f["name"]: f["required"] for f in LandingPageGenerator._default_form_fields()}
    assert required["address"] is False
    assert required["name"] is True


# ── create_page ─────────────────────────────────────────────────────────────
def test_create_page_returns_an_id_url_and_preview(gen):
    result = gen.create_page({"business_name": "Acme Roofing"})
    assert len(result["id"]) == 8
    assert all(c in "0123456789abcdef" for c in result["id"]), result["id"]
    assert result["url"] == f"/api/landing/{result['id']}"
    assert result["html_preview"] == gen.get_page(result["id"])[:500]
    assert result["html_preview"].startswith("<!DOCTYPE html>")


def test_create_page_generates_a_complete_document(gen):
    html = gen.create_page({"business_name": "Acme Roofing"})["html_preview"]
    full = gen.get_page(gen.list_pages()[0]["id"])
    assert full.startswith("<!DOCTYPE html>")
    assert full.rstrip().endswith("</html>")
    assert '<form id="leadForm" action="/api/capture/lead" method="POST" novalidate>' in full
    assert "fetch('/api/capture/lead'" in full
    assert "--accent: #6366f1;" in html  # default accent is the placeholder


def test_create_page_uses_the_supplied_business_name_in_title_and_footer(gen):
    r = gen.create_page({"business_name": "Acme Roofing"})
    html = gen.get_page(r["id"])
    assert "<title>Acme Roofing | Free Estimate</title>" in html
    assert "© Acme Roofing. All rights reserved." in html


def test_create_page_defaults_apply_when_config_is_empty(gen):
    r = gen.create_page({})
    html = gen.get_page(r["id"])
    assert "<title>Our Business | Free Estimate</title>" in html
    assert "Professional Home Improvement Services" in html
    assert html.count('class="benefit-card"') == 4
    assert html.count('class="trust-badge"') == 4
    assert html.count('class="form-group"') == 5
    assert html.count('class="hero-logo"') == 0
    assert html.count('class="hero-image"') == 0


def test_create_page_escapes_a_script_tag_in_the_business_name(gen):
    """The business name is operator input rendered into <title>, the hero logo alt
    text, the footer AND a JS string literal — it must be escaped in all of them."""
    r = gen.create_page({"business_name": "<script>alert(1)</script>"})
    html = gen.get_page(r["id"])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_create_page_escapes_html_in_the_headline(gen):
    html = gen.get_page(gen.create_page({"headline": "Free <b>Estimate</b>"})["id"])
    assert "Free &lt;b&gt;Estimate&lt;/b&gt;" in html
    assert "<b>Estimate</b>" not in html


def test_create_page_falls_back_to_the_default_accent_for_a_bad_colour(gen):
    html = gen.get_page(gen.create_page(
        {"business_name": "Acme", "primary_color": "chartreuse"}
    )["id"])
    assert "--accent: #6366f1;" in html
    assert "chartreuse" not in html


def test_create_page_honours_a_valid_custom_colour(gen):
    html = gen.get_page(gen.create_page(
        {"business_name": "Acme", "primary_color": "rgb(10, 20, 30)"}
    )["id"])
    assert "--accent: rgb(10, 20, 30);" in html


def test_create_page_drops_a_non_http_hero_image_url(gen):
    """A javascript: hero image would run on page load, so the URL is discarded
    entirely (no <img> tag) rather than escaped-and-kept."""
    html = gen.get_page(gen.create_page(
        {"business_name": "Acme", "hero_image_url": "javascript:alert(1)"}
    )["id"])
    assert "javascript" not in html
    assert 'class="hero-image"' not in html


def test_create_page_drops_a_non_http_logo_url(gen):
    html = gen.get_page(gen.create_page(
        {"business_name": "Acme", "logo_url": "data:text/html;base64,PHNjcmlwdD4="}
    )["id"])
    assert "base64" not in html
    assert 'class="hero-logo"' not in html


def test_create_page_renders_valid_https_hero_image_and_logo(gen):
    html = gen.get_page(gen.create_page({
        "business_name": "Acme",
        "hero_image_url": "https://cdn.example.com/hero.jpg",
        "logo_url": "https://cdn.example.com/logo.png",
    })["id"])
    assert 'src="https://cdn.example.com/hero.jpg"' in html
    assert 'loading="lazy"' in html
    assert 'src="https://cdn.example.com/logo.png"' in html
    assert 'alt="Acme logo"' in html


def test_create_page_renders_bespoke_benefits_and_trust_signals(gen):
    html = gen.get_page(gen.create_page({
        "business_name": "Acme",
        "benefits": ["Only one benefit"],
        "trust_signals": [{"icon": "🏅", "text": "Winner 2025"}],
        "form_fields": [{"name": "name", "label": "Name", "required": True}],
    })["id"])
    assert html.count('class="benefit-card"') == 1
    assert "Only one benefit" in html
    assert html.count('class="trust-badge"') == 1
    assert "Winner 2025" in html
    assert html.count('class="form-group"') == 1


def test_create_page_escapes_the_cta_text(gen):
    html = gen.get_page(gen.create_page(
        {"business_name": "Acme", "cta_text": "Get > Quote"}
    )["id"])
    assert "Get &gt; Quote" in html


def test_create_page_uses_a_custom_footer(gen):
    html = gen.get_page(gen.create_page(
        {"business_name": "Acme", "footer_text": "Serving Austin since 1999"}
    )["id"])
    assert "Serving Austin since 1999" in html
    assert "All rights reserved" not in html


def test_create_page_does_not_mutate_the_caller_config(gen):
    config = {"business_name": "Acme", "primary_color": "nope"}
    gen.create_page(config)
    assert config["primary_color"] == "nope"


def test_each_created_page_gets_a_distinct_id(gen):
    ids = {gen.create_page({"business_name": "Acme"})["id"] for _ in range(5)}
    assert len(ids) == 5


def test_create_page_survives_an_unwritable_database(monkeypatch, tmp_path):
    """A DB failure must not lose the in-memory page or raise — the operator can
    still read the page they just generated."""
    monkeypatch.setattr(Database, "db_file", "ZZ:/no_such_dir_xyz/landing.db")
    gen = LandingPageGenerator()
    r = gen.create_page({"business_name": "Acme"})
    assert gen.get_page(r["id"]) is not None


# ── get_page / list_pages / delete_page ─────────────────────────────────────
def test_get_page_returns_none_for_an_unknown_id(gen):
    assert gen.get_page("deadbeef") is None


def test_list_pages_is_empty_before_anything_is_created(gen):
    assert gen.list_pages() == []


def test_list_pages_reports_id_url_and_size(gen):
    r = gen.create_page({"business_name": "Acme"})
    (entry,) = gen.list_pages()
    assert entry == {
        "id": r["id"],
        "url": f"/api/landing/{r['id']}",
        "size": len(gen.get_page(r["id"])),
    }
    assert entry["size"] > 9000  # the page is a full document, not a stub


def test_delete_page_removes_it_and_returns_true(gen):
    r = gen.create_page({"business_name": "Acme"})
    assert gen.delete_page(r["id"]) is True
    assert gen.get_page(r["id"]) is None
    assert gen.list_pages() == []


def test_delete_page_of_an_unknown_id_returns_false(gen):
    assert gen.delete_page("deadbeef") is False


# ── persistence ─────────────────────────────────────────────────────────────
def test_generated_page_is_persisted_to_the_database(gen):
    r = gen.create_page({"business_name": "Acme"})
    with closing(Database.get_connection()) as conn:
        row = conn.execute(
            "SELECT page_id, html FROM landing_pages WHERE page_id = ?", (r["id"],)
        ).fetchone()
    assert row["page_id"] == r["id"]
    assert row["html"] == gen.get_page(r["id"])


def test_a_new_generator_reloads_pages_from_the_database(gen):
    r = gen.create_page({"business_name": "Acme"})
    reloaded = LandingPageGenerator()
    assert r["id"] in reloaded._pages
    assert reloaded.get_page(r["id"]) == gen.get_page(r["id"])


def test_delete_page_also_removes_the_database_row(gen):
    r = gen.create_page({"business_name": "Acme"})
    gen.delete_page(r["id"])
    with closing(Database.get_connection()) as conn:
        row = conn.execute(
            "SELECT page_id FROM landing_pages WHERE page_id = ?", (r["id"],)
        ).fetchone()
    assert row is None
    # And a fresh generator does not resurrect it.
    assert LandingPageGenerator()._pages == {}


def test_saving_the_same_page_id_twice_replaces_rather_than_duplicates(gen):
    gen._save_page_to_db("fixed", "<html>one</html>")
    gen._save_page_to_db("fixed", "<html>two</html>")
    with closing(Database.get_connection()) as conn:
        rows = conn.execute(
            "SELECT html FROM landing_pages WHERE page_id = 'fixed'"
        ).fetchall()
    assert [r["html"] for r in rows] == ["<html>two</html>"]


def test_delete_page_reports_success_even_when_the_database_write_fails(gen, monkeypatch):
    """The in-memory pop happens first, so an unreachable DB must not make the
    caller think the page is still there (a false negative would be worse)."""
    r = gen.create_page({"business_name": "Acme"})
    monkeypatch.setattr(Database, "db_file", "ZZ:/no_such_dir_xyz/landing.db")
    assert gen.delete_page(r["id"]) is True
    assert gen.get_page(r["id"]) is None


def test_constructor_survives_a_database_with_no_landing_pages_table(monkeypatch, tmp_path):
    """`SELECT * FROM landing_pages` on a fresh file raises — the bare `except`
    must swallow it and leave the generator usable with an empty registry."""
    monkeypatch.setattr(Database, "db_file", str(tmp_path / "empty.db"))
    gen = LandingPageGenerator()
    assert gen._pages == {}
    assert gen.create_page({"business_name": "Acme"})["id"]
