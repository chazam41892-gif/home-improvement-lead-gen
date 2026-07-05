from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .base import SearchProvider, SearchResult, SearchHit

PERPLEXITY_BASE = "https://api.perplexity.ai"


class PerplexitySearchProvider(SearchProvider):
    name = "perplexity"

    def __init__(self, *, api_key: Optional[str] = None, timeout: float = 30.0,
                 base_url: str = PERPLEXITY_BASE):
        super().__init__(
            api_key=api_key or os.environ.get("PERPLEXITY_API_KEY"),
            timeout=timeout,
        )
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key or ''}",
            "User-Agent": "LeviathanLeadGen/3.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
            return {"error": f"HTTP {e.code}: {body_text[:300]}"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}

    async def search(self, query: str, *,
                     num_results: int = 10,
                     search_type: str = "auto",
                     **kwargs) -> SearchResult:
        t0 = time.time()
        if not self.api_key:
            return SearchResult(query=query, hits=[], provider=self.name,
                                elapsed_sec=time.time() - t0,
                                error="PERPLEXITY_API_KEY not set. Add your key in Settings.")

        body: Dict[str, Any] = {
            "query": query,
            "max_results": num_results,
            "search_recency": kwargs.get("recency", "any"),
        }

        resp = await asyncio.to_thread(self._post, "/search", body)
        if "error" in resp:
            return SearchResult(query=query, hits=[], provider=self.name,
                                elapsed_sec=time.time() - t0,
                                error=resp["error"])

        hits: List[SearchHit] = []
        for r in resp.get("results", [])[:num_results]:
            hits.append(SearchHit(
                title=r.get("title", "") or "",
                url=r.get("url", "") or "",
                snippet=r.get("snippet", "")[:500] or r.get("content", "")[:500],
                published_date=r.get("published_date") or r.get("date"),
                score=float(r.get("score", 0.0) or 0.0),
                extras={"source": "perplexity", "author": r.get("author")},
            ))
        return SearchResult(query=query, hits=hits, provider=self.name,
                            elapsed_sec=time.time() - t0,
                            raw=resp)
