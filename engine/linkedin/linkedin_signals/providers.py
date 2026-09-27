import asyncio
import json
import re
import time
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote

import aiohttp

from .prompts import render_prompt


class ProviderError(RuntimeError):
    pass


def post_urn_from_value(value: str) -> str:
    value = (value or "").strip()
    if value.startswith("urn:li:"):
        return value
    match = re.search(r"(?:activity|share|ugcPost)[-:](\d{8,})", value)
    if not match:
        raise ValueError("LinkedIn post URL must contain an activity/share identifier or be a LinkedIn URN")
    return f"urn:li:activity:{match.group(1)}"


class LinkedInAPIClient:
    name = "linkedin"

    def __init__(self, access_token: str, version: str = "202607", timeout: int = 45, max_pages: int = 10):
        if not access_token:
            raise ValueError("LinkedIn access token is required")
        self.access_token = access_token
        self.version = version
        self.timeout = timeout
        self.max_pages = max(1, min(int(max_pages), 50))
        self.base_url = "https://api.linkedin.com/rest"

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Linkedin-Version": self.version,
            "X-Restli-Protocol-Version": "2.0.0",
        }

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with aiohttp.ClientSession(headers=self.headers) as session, session.get(
            f"{self.base_url}{path}",
            params=params,
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise ProviderError(f"LinkedIn API {response.status}: {text[:500]}")
            return json.loads(text) if text else {}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {**self.headers, "Content-Type": "application/json"}
        async with aiohttp.ClientSession(headers=headers) as session, session.post(
            f"{self.base_url}{path}",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise ProviderError(f"LinkedIn API {response.status}: {text[:500]}")
            data = json.loads(text) if text else {}
            if response.headers.get("x-restli-id"):
                data["id"] = response.headers["x-restli-id"]
            return data

    async def create_text_post(self, author_urn: str, commentary: str) -> dict[str, Any]:
        if not author_urn.startswith("urn:li:"):
            raise ValueError("LinkedIn post author must be a LinkedIn URN")
        if not commentary.strip():
            raise ValueError("LinkedIn post commentary is required")
        return await self._post(
            "/posts",
            {
                "author": author_urn,
                "commentary": commentary.strip(),
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            },
        )

    async def list_posts(self, author_urn: str, count: int = 20):
        data = await self._get(
            "/posts",
            {"q": "author", "author": author_urn, "count": max(1, min(count, 100)), "sortBy": "LAST_MODIFIED"},
        )
        return data.get("elements", [])

    async def _get_paged(self, path: str, params: dict[str, Any] | None = None, count: int = 100):
        records = []
        start = 0
        pages = 0
        while pages < self.max_pages:
            page_params = {**(params or {}), "start": start, "count": count}
            data = await self._get(path, page_params)
            pages += 1
            elements = data.get("elements", [])
            records.extend(elements)
            paging = data.get("paging") or {}
            total = paging.get("total")
            start += len(elements)
            if not elements or len(elements) < count or (total is not None and start >= int(total)):
                break
        return records

    async def collect_post(self, post_url: str) -> dict[str, Any]:
        post_urn = post_urn_from_value(post_url)
        encoded = quote(post_urn, safe="")
        post = await self._get(f"/posts/{encoded}")
        metadata = await self._get(f"/socialMetadata/{encoded}")
        reactions = await self._get_paged(
            f"/reactions/(entity:{encoded})",
            {"q": "entity", "sort": "(value:REVERSE_CHRONOLOGICAL)"},
        )
        comments = await self._get_paged(f"/socialActions/{encoded}/comments")
        reaction_count = sum(int(item.get("count", 0)) for item in metadata.get("reactionSummaries", {}).values())
        comment_count = int(metadata.get("commentSummary", {}).get("count", len(comments)))
        repost_count = int(metadata.get("reshareSummary", {}).get("count", 0))
        created_ms = post.get("createdAt") or post.get("created", {}).get("time")
        engagements = []
        for item in reactions:
            created = item.get("created") or {}
            engagements.append({
                "actor_urn": item.get("actor") or created.get("actor", ""),
                "profile_url": "",
                "action": item.get("reactionType", "REACTION"),
            })
        for item in comments:
            actor = item.get("actor", "")
            message = item.get("message", {})
            engagements.append({
                "actor_urn": actor,
                "profile_url": item.get("profileUrl", ""),
                "action": "COMMENT",
                "comment_text": message.get("text", "") if isinstance(message, dict) else str(message or ""),
            })
        return {
            "post": {
                "urn": post.get("id", post_urn),
                "url": post_url,
                "text": post.get("commentary", ""),
                "reactions": reaction_count,
                "comments": comment_count,
                "reposts": repost_count,
                "age_hours": max((time.time() * 1000 - float(created_ms)) / 3_600_000, 1.0) if created_ms is not None else None,
                "raw": {"post": post, "metadata": metadata},
            },
            "engagements": engagements,
        }


class ApifyLinkedInCollector:
    name = "apify"
    reactions_actor = "apimaestro~linkedin-post-reactions"
    comments_actor = "apimaestro~linkedin-post-comments-replies-engagements-scraper-no-cookies"

    def __init__(self, api_token: str, official_client=None, max_pages: int = 10, timeout: int = 180):
        if not api_token:
            raise ValueError("Apify API token is required")
        self.api_token = api_token
        self.official_client = official_client
        self.max_pages = max(1, min(max_pages, 50))
        self.timeout = timeout

    async def _run_actor(self, actor: str, payload: dict[str, Any]):
        url = f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items"
        async with aiohttp.ClientSession() as session, session.post(
            url,
            params={"token": self.api_token},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=self.timeout),
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ProviderError(f"Apify actor {response.status}: {str(data)[:500]}")
            return data if isinstance(data, list) else data.get("items", [])

    @staticmethod
    def normalize_reaction(item: dict[str, Any]) -> dict[str, Any]:
        reactor = item.get("reactor") or item.get("author") or item.get("actor") or {}
        if not isinstance(reactor, dict):
            reactor = {}
        return {
            "actor_urn": reactor.get("urn") or reactor.get("id") or "",
            "profile_url": reactor.get("profile_url") or reactor.get("profileUrl") or reactor.get("linkedin_url") or "",
            "name": reactor.get("name") or reactor.get("fullName") or "",
            "headline": reactor.get("headline") or "",
            "action": item.get("reaction_type") or item.get("reactionType") or "REACTION",
        }

    @staticmethod
    def normalize_comment(item: dict[str, Any]) -> dict[str, Any]:
        author = item.get("author") or item.get("commenter") or item.get("actor") or {}
        if not isinstance(author, dict):
            author = {}
        return {
            "actor_urn": author.get("urn") or author.get("id") or "",
            "profile_url": author.get("profile_url") or author.get("profileUrl") or author.get("linkedin_url") or item.get("profile_url") or "",
            "name": author.get("name") or author.get("fullName") or item.get("author_name") or "",
            "headline": author.get("headline") or item.get("author_headline") or "",
            "action": "COMMENT",
            "comment_text": item.get("text") or item.get("comment_text") or item.get("message") or "",
        }

    async def _paged(self, actor: str, payload_factory):
        records = []
        for page in range(1, self.max_pages + 1):
            batch = await self._run_actor(actor, payload_factory(page))
            records.extend(batch)
            if len(batch) < 100:
                break
        return records

    async def list_posts(self, author_urn: str, count: int = 20):
        if not self.official_client:
            raise ProviderError("Source-account scheduling requires a LinkedIn developer access token")
        return await self.official_client.list_posts(author_urn, count)

    async def collect_post(self, post_url: str) -> dict[str, Any]:
        official_result = await self.official_client.collect_post(post_url) if self.official_client else None
        reactions = await self._paged(
            self.reactions_actor,
            lambda page: {"post_urls": [post_url], "page_number": page, "reaction_type": "ALL", "limit": 100},
        )
        comments = await self._paged(
            self.comments_actor,
            lambda page: {"postIds": [post_url], "page_number": page, "sortOrder": "most recent", "limit": 100},
        )
        engagements = list(official_result.get("engagements", [])) if official_result else []
        engagements.extend(self.normalize_reaction(item) for item in reactions)
        engagements.extend(self.normalize_comment(item) for item in comments)
        if official_result:
            post = official_result["post"]
            post["raw"] = {
                **(post.get("raw") or {}),
                "collector": "linkedin+apify",
                "reaction_records": len(reactions),
                "comment_records": len(comments),
            }
            return {"post": post, "engagements": engagements}
        return {
            "post": {
                "urn": post_urn_from_value(post_url),
                "url": post_url,
                "text": "",
                "reactions": len(reactions),
                "comments": len(comments),
                "reposts": 0,
                "age_hours": None,
                "raw": {"collector": "apify", "reaction_records": len(reactions), "comment_records": len(comments)},
            },
            "engagements": engagements,
        }


class LLMQualifier:
    def __init__(self, llm_func, target_profile: dict[str, Any] | None = None):
        self.llm_func = llm_func
        self.target_profile = target_profile or {}

    async def qualify(self, lead: dict[str, Any], post: dict[str, Any]) -> dict[str, Any]:
        if not self.llm_func:
            return {
                "qualified": False,
                "confidence_score": 0.0,
                "intent_score": 0.0,
                "persona": "",
                "matched_criteria": [],
                "missing_evidence": ["LLM qualification unavailable"],
                "reason": "Awaiting manual qualification",
            }
        payload = json.dumps(
            {"target_profile": self.target_profile, "lead": lead, "post": post},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        raw = await self.llm_func(render_prompt("lead_qualification", payload))
        cleaned = str(raw or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1].rsplit("```", 1)[0]
        result = json.loads(cleaned)
        if not isinstance(result, dict) or not isinstance(result.get("qualified"), bool):
            raise ProviderError("LLM qualification returned an invalid contract")
        return result


class EnrichmentWaterfall:
    def __init__(self, providers: Iterable[Any], mobile_provider: Any = None,
                 max_attempts: int = 3, retry_delay_seconds: float = 0.25):
        self.providers = list(providers)
        self.mobile_provider = mobile_provider
        self.max_attempts = max(1, int(max_attempts))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds))

    @staticmethod
    def _retryable(error: ProviderError) -> bool:
        message = str(error)
        return " 429" in message or any(f" {status}" in message for status in range(500, 600))

    async def enrich(self, lead: dict[str, Any]) -> dict[str, Any] | None:
        for provider in self.providers:
            result = None
            for attempt in range(self.max_attempts):
                try:
                    result = await provider.enrich(lead)
                    break
                except ProviderError as error:
                    if attempt + 1 >= self.max_attempts or not self._retryable(error):
                        break
                    await asyncio.sleep(self.retry_delay_seconds * (2 ** attempt))
            if result and result.get("email"):
                enriched = {**result, "enrichment_source": provider.name}
                if self.mobile_provider and not enriched.get("phone"):
                    try:
                        enriched["phone"] = await self.mobile_provider.find_mobile({**lead, **enriched})
                    except ProviderError:
                        enriched["phone"] = ""
                return enriched
        return None


class ApolloEnricher:
    name = "apollo"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def enrich(self, lead: dict[str, Any]) -> dict[str, Any] | None:
        if not self.api_key or not lead.get("profile_url"):
            return None
        payload = {"linkedin_url": lead["profile_url"], "reveal_personal_emails": False}
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json", "Cache-Control": "no-cache"}
        async with aiohttp.ClientSession(headers=headers) as session, session.post(
            "https://api.apollo.io/api/v1/people/match",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ProviderError(f"Apollo API {response.status}: {str(data)[:500]}")
        person = data.get("person") or {}
        if not person.get("email"):
            return None
        organization = person.get("organization") or {}
        return {
            "email": person.get("email", ""),
            "name": person.get("name", ""),
            "phone": person.get("phone_number", ""),
            "title": person.get("title", ""),
            "company": organization.get("name", ""),
            "profile_url": person.get("linkedin_url", lead.get("profile_url", "")),
        }


class ProspeoEnricher:
    name = "prospeo"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def enrich(self, lead: dict[str, Any]) -> dict[str, Any] | None:
        if not self.api_key or not lead.get("profile_url"):
            return None
        headers = {"X-KEY": self.api_key, "Content-Type": "application/json"}
        payload = {"only_verified_email": True, "data": {"linkedin_url": lead["profile_url"]}}
        async with aiohttp.ClientSession(headers=headers) as session, session.post(
            "https://api.prospeo.io/enrich-person",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ProviderError(f"Prospeo API {response.status}: {str(data)[:500]}")
        person = data.get("person") or {}
        email_record = person.get("email") or {}
        email = email_record.get("email", "") if isinstance(email_record, dict) else str(email_record or "")
        if not email:
            return None
        company = data.get("company") or {}
        mobile_record = person.get("mobile") or {}
        return {
            "email": email,
            "name": person.get("full_name", ""),
            "phone": mobile_record.get("mobile", "") if isinstance(mobile_record, dict) else "",
            "title": person.get("current_job_title", ""),
            "company": company.get("name", ""),
            "profile_url": person.get("linkedin_url", lead.get("profile_url", "")),
        }


class LeadMagicEnricher:
    name = "leadmagic"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.leadmagic.io/v1/people"

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
        async with aiohttp.ClientSession(headers=headers) as session, session.post(
            f"{self.base_url}/{path}",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ProviderError(f"LeadMagic API {response.status}: {str(data)[:500]}")
            return data

    async def enrich(self, lead: dict[str, Any]) -> dict[str, Any] | None:
        profile_url = lead.get("profile_url", "")
        if not self.api_key or not profile_url:
            return None
        data = await self._post("b2b-profile-email", {"profile_url": profile_url})
        if not data.get("email"):
            return None
        return {
            "email": data["email"],
            "name": lead.get("name", ""),
            "title": lead.get("headline", ""),
            "profile_url": data.get("profile_url", profile_url),
        }

    async def find_mobile(self, lead: dict[str, Any]) -> str:
        if not self.api_key:
            return ""
        payload = {
            key: value for key, value in {
                "profile_url": lead.get("profile_url", ""),
                "work_email": lead.get("email", ""),
            }.items() if value
        }
        if not payload:
            return ""
        data = await self._post("mobile-finder", payload)
        return str(data.get("mobile_number", ""))


class MillionVerifier:
    name = "millionverifier"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def verify(self, email: str) -> dict[str, Any]:
        if not self.api_key:
            return {"status": "unconfigured", "email": email}
        async with aiohttp.ClientSession() as session, session.get(
            "https://api.millionverifier.com/api/v3/",
            params={"api": self.api_key, "email": email, "timeout": 10},
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ProviderError(f"MillionVerifier API {response.status}: {str(data)[:500]}")
        return {"status": str(data.get("result", "unknown")).lower(), "email": email, "details": data}


class InstantlyClient:
    name = "instantly"

    def __init__(self, api_key: str):
        self.api_key = api_key

    @staticmethod
    def build_payload(campaign_id: str, lead: dict[str, Any]) -> dict[str, Any]:
        name_parts = str(lead.get("name", "")).strip().split(maxsplit=1)
        first_name = lead.get("first_name") or (name_parts[0] if name_parts else "")
        last_name = lead.get("last_name") or (name_parts[1] if len(name_parts) > 1 else "")
        return {
            "campaign": campaign_id,
            "email": lead["email"],
            "first_name": first_name,
            "last_name": last_name,
            "company_name": lead.get("company", ""),
            "personalization": lead.get("personalization", ""),
            "custom_variables": {
                "subject": lead.get("subject", ""),
                "linkedin_profile": lead.get("profile_url", ""),
                "source_post_urn": lead.get("source_post_urn", ""),
            },
            "skip_if_in_workspace": True,
            "skip_if_in_campaign": True,
        }

    async def add_lead(self, campaign_id: str, lead: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError("Instantly API key is not configured")
        payload = self.build_payload(campaign_id, lead)
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession(headers=headers) as session, session.post(
            "https://api.instantly.ai/api/v2/leads",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise ProviderError(f"Instantly API {response.status}: {str(data)[:500]}")
            return data
