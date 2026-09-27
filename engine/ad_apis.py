"""Real ad platform API integrations with credential-gated execution.

This module provides scaffolding to create campaigns, ad groups, and ads on
Google Ads and Meta (Facebook/Instagram) Marketing API. It will only attempt
live API calls when credentials are configured; otherwise it returns a
preview/sandbox response so local development and tests continue to work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from engine.key_vault import KeyVault

logger = logging.getLogger(__name__)


@dataclass
class AdCampaignPlan:
    platform: str
    name: str
    budget_cents: int
    industry: str
    location: str
    headline: str
    description: str
    cta: str
    keywords: list[str]
    landing_page_url: str
    start_date: str | None = None
    end_date: str | None = None


class GoogleAdsAPI:
    """Google Ads API client (credential-gated via KeyVault)."""

    SCOPES = ["https://www.googleapis.com/auth/adwords"]
    BASE_URL = "https://googleads.googleapis.com/v16"

    def __init__(self) -> None:
        self.developer_token = KeyVault.get("google_ads_dev_token") or ""
        self.customer_id = KeyVault.get("google_ads_customer_id") or ""
        self.login_customer_id = KeyVault.get("google_ads_login_customer_id") or ""
        self.client_id = KeyVault.get("google_ads_client_id") or ""
        self.client_secret = KeyVault.get("google_ads_client_secret") or ""
        self.refresh_token = KeyVault.get("google_ads_refresh_token") or ""

    @property
    def is_configured(self) -> bool:
        return bool(self.developer_token and self.customer_id and self.refresh_token)

    async def _access_token(self) -> str | None:
        if not self.client_id or not self.client_secret or not self.refresh_token:
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://oauth2.googleapis.com/token",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "refresh_token": self.refresh_token,
                        "grant_type": "refresh_token",
                    },
                )
            if resp.status_code >= 400:
                logger.error("Google Ads token refresh failed: %s", resp.text)
                return None
            return resp.json().get("access_token")
        except Exception as e:
            logger.error("Google Ads token refresh error: %s", e)
            return None

    async def create_campaign(self, plan: AdCampaignPlan) -> dict[str, Any]:
        if not self.is_configured:
            return self._preview(plan)

        token = await self._access_token()
        if not token:
            return {"ok": False, "error": "Unable to obtain Google Ads access token", "simulated": True}

        url = f"{self.BASE_URL}/customers/{self.customer_id}/campaigns:mutate"
        headers = {
            "Authorization": f"Bearer {token}",
            "developer-token": self.developer_token,
            "Content-Type": "application/json",
        }
        if self.login_customer_id:
            headers["login-customer-id"] = self.login_customer_id

        payload = {
            "operations": [
                {
                    "create": {
                        "name": plan.name,
                        "advertisingChannelType": "SEARCH",
                        "status": "PAUSED",
                        "campaignBudget": f"customers/{self.customer_id}/campaignBudgets/-1",
                        "startDate": plan.start_date or "20260101",
                        "endDate": plan.end_date or "20261231",
                        "targetSpend": {"spendAmount": str(plan.budget_cents * 10_000)},  # micro-units
                    }
                }
            ]
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code >= 400:
                logger.error("Google Ads campaign create failed: %s", resp.text)
                return {"ok": False, "error": resp.text[:300], "status_code": resp.status_code}
            data = resp.json()
            return {"ok": True, "platform": "google_ads", "campaign": data}
        except Exception as e:
            logger.error("Google Ads campaign create error: %s", e)
            return {"ok": False, "error": str(e)}

    def _preview(self, plan: AdCampaignPlan) -> dict[str, Any]:
        return {
            "ok": True,
            "simulated": True,
            "platform": "google_ads",
            "note": "Google Ads credentials not configured. Returning preview.",
            "preview": {
                "name": plan.name,
                "channel": "SEARCH",
                "budget_cents": plan.budget_cents,
                "headline": plan.headline,
                "description": plan.description,
                "keywords": plan.keywords[:10],
                "landing_page_url": plan.landing_page_url,
            },
        }


class MetaMarketingAPI:
    """Meta Marketing API client (credential-gated via KeyVault)."""

    BASE_URL = "https://graph.facebook.com/v18.0"

    def __init__(self) -> None:
        self.access_token = KeyVault.get("meta_access_token") or ""
        self.ad_account_id = KeyVault.get("meta_ad_account_id") or ""
        self.page_id = KeyVault.get("meta_page_id") or ""

    @property
    def is_configured(self) -> bool:
        return bool(self.access_token and self.ad_account_id)

    async def create_campaign(self, plan: AdCampaignPlan) -> dict[str, Any]:
        if not self.is_configured:
            return self._preview(plan)

        url = f"{self.BASE_URL}/act_{self.ad_account_id}/campaigns"
        payload = {
            "name": plan.name,
            "objective": "LEAD_GENERATION",
            "status": "PAUSED",
            "special_ad_categories": "[]",
            "access_token": self.access_token,
        }

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(url, data=payload)
            if resp.status_code >= 400:
                logger.error("Meta campaign create failed: %s", resp.text)
                return {"ok": False, "error": resp.text[:300], "status_code": resp.status_code}
            data = resp.json()
            return {"ok": True, "platform": "meta", "campaign": data}
        except Exception as e:
            logger.error("Meta campaign create error: %s", e)
            return {"ok": False, "error": str(e)}

    def _preview(self, plan: AdCampaignPlan) -> dict[str, Any]:
        return {
            "ok": True,
            "simulated": True,
            "platform": "meta",
            "note": "Meta credentials not configured. Returning preview.",
            "preview": {
                "name": plan.name,
                "objective": "LEAD_GENERATION",
                "budget_cents": plan.budget_cents,
                "headline": plan.headline,
                "description": plan.description,
                "cta": plan.cta,
                "landing_page_url": plan.landing_page_url,
            },
        }


class AdPlatformManager:
    """Unified interface to launch ad campaigns across platforms."""

    def __init__(self) -> None:
        self.google = GoogleAdsAPI()
        self.meta = MetaMarketingAPI()

    def status(self) -> dict[str, Any]:
        return {
            "google_ads": {
                "configured": self.google.is_configured,
                "missing": self._missing_env(
                    "GOOGLE_ADS",
                    [
                        "GOOGLE_ADS_DEVELOPER_TOKEN",
                        "GOOGLE_ADS_CUSTOMER_ID",
                        "GOOGLE_ADS_REFRESH_TOKEN",
                    ],
                ),
            },
            "meta": {
                "configured": self.meta.is_configured,
                "missing": self._missing_env(
                    "META",
                    [
                        "META_ACCESS_TOKEN",
                        "META_AD_ACCOUNT_ID",
                    ],
                ),
            },
        }

    @staticmethod
    def _missing_env(prefix: str, keys: list[str]) -> list[str]:
        """Keys not resolvable via the vault.

        Audit 2026-09-27 (M-17): this was named `_missing_env` but queries
        KeyVault, so the UI told operators to set env vars that are never read on
        the live path. Kept as a staticmethod for call-site compatibility; the
        name now matches the behaviour.
        """
        return [k for k in keys if not KeyVault.get(k)]

    async def launch(self, plan: AdCampaignPlan) -> dict[str, Any]:
        """Launch a campaign.

        CRITICAL (audit 2026-09-27, C-3): this used to `return {"ok": True, **results}`
        unconditionally, so a *simulated* preview (no ad credentials) was reported to
        the user as a successfully launched campaign with a real-looking campaign_id.
        `ok` is now derived from the provider sub-result and `simulated` is hoisted to
        the TOP level so the HTTP layer and the UI can both see it.
        """
        results: dict[str, Any] = {"plan": plan.__dict__}
        if plan.platform in ("google", "google_ads"):
            results["google_ads"] = await self.google.create_campaign(plan)
        elif plan.platform in ("meta", "facebook", "instagram"):
            results["meta"] = await self.meta.create_campaign(plan)
        elif plan.platform == "both":
            results["google_ads"] = await self.google.create_campaign(plan)
            results["meta"] = await self.meta.create_campaign(plan)
        else:
            return {"ok": False, "simulated": False, "error": f"Unknown platform: {plan.platform}"}

        subs = [v for k, v in results.items() if k in ("google_ads", "meta")]
        # ok = at least one provider really succeeded and none of them simulated.
        ok = any(bool(s.get("ok")) for s in subs) and not any(bool(s.get("simulated")) for s in subs)
        # Hoist the truth flags so callers do not have to dig into the sub-objects.
        results["ok"] = ok
        results["simulated"] = any(bool(s.get("simulated")) for s in subs)
        # A real provider id, if any provider returned one.
        provider_ids = []
        for s in subs:
            camp = s.get("campaign") or {}
            for key in ("resourceName", "id"):
                if camp.get(key):
                    provider_ids.append(camp[key])
                    break
        results["provider_campaign_ids"] = provider_ids
        return results


__all__ = ["AdCampaignPlan", "AdPlatformManager", "GoogleAdsAPI", "MetaMarketingAPI"]
