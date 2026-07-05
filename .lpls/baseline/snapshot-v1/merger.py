from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

logger = logging.getLogger("SourceMerger")


@dataclass
class MergedResult:
    source_count: int = 0
    dedup_removed: int = 0
    total_before_dedup: int = 0
    sources_used: List[str] = field(default_factory=list)
    elapsed_sec: float = 0.0


def _domain_key(url: str) -> str:
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower().replace("www.", "")
        path = parsed.path.rstrip("/")
        return f"{domain}{path}" if path else domain
    except Exception:
        return url.lower().rstrip("/")


def _title_similarity(a: str, b: str) -> float:
    a = re.sub(r"[^a-z0-9\s]", "", a.lower()).strip()
    b = re.sub(r"[^a-z0-9\s]", "", b.lower()).strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if len(a) > 3 and len(b) > 3 and (a in b or b in a):
        return 0.85
    return SequenceMatcher(None, a, b).ratio()


MERGE_SIMILARITY_THRESHOLD = 0.78


def merge_leads(results: List[Dict[str, Any]],
                sources: List[str],
                merge_threshold: float = MERGE_SIMILARITY_THRESHOLD) -> Dict[str, Any]:
    t0 = time.time()
    merged: List[Dict[str, Any]] = []
    seen_domains: Set[str] = set()
    seen_titles: List[str] = []
    dedup_count = 0

    all_leads: List[Tuple[str, Dict[str, Any]]] = []
    for lead in results:
        src = lead.get("source", "unknown")
        all_leads.append((src, lead))

    for src, lead in all_leads:
        url = lead.get("url", "") or ""
        title = lead.get("title", "") or ""

        domain_key = _domain_key(url) if url else ""
        if domain_key and domain_key in seen_domains:
            dedup_count += 1
            continue

        is_dup = False
        for existing_title in seen_titles:
            if _title_similarity(title, existing_title) >= merge_threshold:
                is_dup = True
                break
        if is_dup:
            dedup_count += 1
            continue

        if domain_key:
            seen_domains.add(domain_key)
        if title and len(title) > 3:
            seen_titles.append(title)

        lead["_merged_from"] = src
        merged.append(lead)

    elapsed = time.time() - t0

    return {
        "leads": merged,
        "stats": {
            "total_before_dedup": len(results),
            "dedup_removed": dedup_count,
            "after_dedup": len(merged),
            "sources_used": sources,
            "elapsed_sec": round(elapsed, 3),
        },
    }
