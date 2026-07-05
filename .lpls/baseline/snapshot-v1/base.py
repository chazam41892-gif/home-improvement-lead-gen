from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SearchHit:
    title: str
    url: str
    snippet: str = ""
    published_date: Optional[str] = None
    score: float = 0.0
    extras: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "published_date": self.published_date,
            "score": self.score,
            **self.extras,
        }


@dataclass
class SearchResult:
    query: str
    hits: List[SearchHit]
    provider: str
    elapsed_sec: float = 0.0
    total_results: Optional[int] = None
    raw: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.error is None,
            "query": self.query,
            "provider": self.provider,
            "count": len(self.hits),
            "total_results": self.total_results,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "error": self.error,
            "hits": [h.as_dict() for h in self.hits],
        }


class SearchProvider:
    name = "base"

    def __init__(self, *, api_key: Optional[str] = None, timeout: float = 30.0):
        self.api_key = api_key
        self.timeout = timeout

    async def search(self, query: str, *,
                     num_results: int = 10,
                     **kwargs) -> SearchResult:
        raise NotImplementedError
