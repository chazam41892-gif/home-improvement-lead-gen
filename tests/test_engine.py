from datetime import datetime

from engine.trades.trades import list_trades, get_trade_config
from engine.trades.base import TradeLead
from engine.trades.scoring import score_trade_lead
from engine.trades.convert import ConversionPipeline
from engine.scout import LeadResult
from engine.utils.scoring import LeadScore


def test_score_trade_lead():
    lead = TradeLead(
        business_name="Test Plumbing Co",
        phone="512-555-1234",
        email="test@example.com",
        website="https://example.com",
        trade="plumbing",
        rating=4.5,
        review_count=25,
        platforms_found=["google_maps", "yelp", "homeadvisor"],
    )
    score = score_trade_lead(lead, "plumbing")
    assert score >= 50.0
    assert score <= 100.0


def test_list_trades():
    trades = list_trades()
    assert len(trades) == 44


def test_get_trade_config():
    config = get_trade_config("plumbing")
    assert config is not None
    assert config["name"] == "Plumbing"
    assert "avg_job_value" in config
    assert "platforms" in config
    assert "conversion_rate" in config


async def test_conversion_pipeline(tmp_path):
    pipeline = ConversionPipeline(data_dir=str(tmp_path))
    lead = TradeLead(
        business_name="Test Plumbing Co",
        phone="512-555-1234",
        trade="plumbing",
    )
    account = await pipeline.convert_to_account(lead, plan="growth")
    assert account["account_id"] == f"acc_{lead.id}"
    assert account["plan"] == "growth"
    assert account["monthly_fee"] == 197

    payment = await pipeline.record_payment(account["account_id"], account["monthly_fee"])
    assert payment["account_id"] == account["account_id"]
    assert payment["amount"] == 197
    assert payment["status"] == "completed"

    stats = pipeline.get_revenue_stats()
    assert stats["total_accounts"] == 1
    assert stats["total_payments"] == 1
    assert stats["total_revenue"] == 197


def test_lead_result_as_dict():
    score = LeadScore(total=75.0)
    lead = LeadResult(
        id="test123",
        title="Test Contractor",
        url="https://example.com",
        snippet="A test contractor business",
        industry="plumbing",
        location="Austin, TX",
        source="exa",
        score=score,
        found_at=datetime.now().isoformat(),
        email="test@example.com",
        phone="512-555-1234",
        notes="Test note",
    )
    d = lead.as_dict()
    expected_keys = {
        "id", "title", "url", "snippet", "industry", "location",
        "source", "score", "contact_score", "business_score",
        "industry_score", "location_score", "enrichment_score",
        "score_breakdown", "found_at", "email", "phone", "notes",
    }
    assert set(d.keys()) == expected_keys
    assert d["id"] == "test123"
    assert d["score"] == 75.0
