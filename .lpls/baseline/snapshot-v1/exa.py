from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .base import SearchProvider, SearchResult, SearchHit

EXA_BASE = "https://api.exa.ai"


class ExaSearchProvider(SearchProvider):
    name = "exa"

    def __init__(self, *, api_key: Optional[str] = None, timeout: float = 30.0,
                 base_url: str = EXA_BASE):
        super().__init__(
            api_key=api_key or os.environ.get("EXA_API_KEY"),
            timeout=timeout,
        )
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": self.api_key or "",
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
                     category: Optional[str] = None,
                     text: bool = False,
                     highlights: bool = False,
                     start_published_date: Optional[str] = None,
                     end_published_date: Optional[str] = None,
                     include_domains: Optional[List[str]] = None,
                     exclude_domains: Optional[List[str]] = None,
                     **kwargs) -> SearchResult:
        t0 = time.time()
        if not self.api_key:
            return SearchResult(query=query, hits=[], provider=self.name,
                                elapsed_sec=time.time() - t0,
                                error="EXA_API_KEY not set. Add your key in Settings.")

        body: Dict[str, Any] = {
            "query": query,
            "numResults": num_results,
            "type": search_type,
        }
        if category: body["category"] = category
        if start_published_date: body["startPublishedDate"] = start_published_date
        if end_published_date: body["endPublishedDate"] = end_published_date
        if include_domains: body["includeDomains"] = include_domains
        if exclude_domains: body["excludeDomains"] = exclude_domains
        if text or highlights:
            body["contents"] = {}
            if text: body["contents"]["text"] = True
            if highlights:
                body["contents"]["highlights"] = {"numSentences": 3}

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
                snippet=(r.get("text") or "")[:500] or (
                    " ".join(r.get("highlights") or [])[:500]
                ),
                published_date=r.get("publishedDate"),
                score=float(r.get("score", 0.0) or 0.0),
                extras={"author": r.get("author"), "image": r.get("image")},
            ))
        return SearchResult(query=query, hits=hits, provider=self.name,
                            elapsed_sec=time.time() - t0,
                            raw=resp)

    async def contents(self, urls: List[str], *,
                       text: bool = True,
                       highlights: bool = False,
                       summary: bool = False,
                       livecrawl: str = "fallback") -> Dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "error": "EXA_API_KEY not set"}
        body: Dict[str, Any] = {"ids": urls, "livecrawl": livecrawl}
        if text: body["text"] = True
        if highlights: body["highlights"] = {"numSentences": 3}
        if summary: body["summary"] = {"query": "summarize"}
        return await asyncio.to_thread(self._post, "/contents", body)

    async def answer(self, query: str, *, text: bool = True) -> Dict[str, Any]:
        if not self.api_key:
            return {"ok": False, "error": "EXA_API_KEY not set"}
        body = {"query": query, "text": text}
        return await asyncio.to_thread(self._post, "/answer", body)
