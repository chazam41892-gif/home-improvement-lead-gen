from .trades import get_trade_config
from .base import TradeLead


def score_trade_lead(lead: TradeLead, trade: str) -> float:
    """
    Score a trade lead based on multiple factors.
    Returns 0-100 score.
    """
    config = get_trade_config(trade)
    if not config:
        return 50.0

    score = 50.0

    if lead.phone:
        score += 10

    if lead.email:
        score += 10

    if lead.website:
        score += 5

    if lead.address:
        score += 5

    if lead.rating > 4.0:
        score += 5
    elif lead.rating > 0:
        score += 2

    if lead.review_count > 20:
        score += 5
    elif lead.review_count > 5:
        score += 2

    platform_multiplier = len(lead.platforms_found)
    if platform_multiplier >= 3:
        score += 10
    elif platform_multiplier >= 2:
        score += 5

    return min(score, 100.0)


def score_trade_leads(leads: list[TradeLead], trade: str) -> list[TradeLead]:
    for lead in leads:
        lead.score = score_trade_lead(lead, trade)
    return sorted(leads, key=lambda l: l.score, reverse=True)
