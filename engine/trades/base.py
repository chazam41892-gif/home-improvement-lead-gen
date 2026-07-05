import uuid
from datetime import datetime
from typing import Any, Optional


class TradeLead:
    def __init__(
        self,
        business_name: str = "",
        phone: str = "",
        email: str = "",
        address: str = "",
        website: str = "",
        source: str = "",
        trade: str = "",
        rating: float = 0.0,
        review_count: int = 0,
        platforms_found: Optional[list[str]] = None,
        notes: str = "",
    ):
        self.id = uuid.uuid4().hex[:12]
        self.business_name = business_name
        self.phone = phone
        self.email = email
        self.address = address
        self.website = website
        self.source = source
        self.trade = trade
        self.rating = rating
        self.review_count = review_count
        self.platforms_found = platforms_found or [source] if source else []
        self.notes = notes
        self.found_at = datetime.now().isoformat()
        self.score = 50.0
        self.status = "new"
        self.converted = False
        self.account_id = ""
        self.payment_id = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "business_name": self.business_name,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "website": self.website,
            "source": self.source,
            "trade": self.trade,
            "rating": self.rating,
            "review_count": self.review_count,
            "platforms_found": self.platforms_found,
            "notes": self.notes,
            "found_at": self.found_at,
            "score": self.score,
            "status": self.status,
            "converted": self.converted,
            "account_id": self.account_id,
            "payment_id": self.payment_id,
        }


class TradeLeadSource:
    def __init__(self, trade: str, config: dict):
        self.trade = trade
        self.config = config

    async def discover(self, location: str, max_results: int = 25) -> list[TradeLead]:
        raise NotImplementedError
