#!/usr/bin/env python3
"""Pre-flight environment validation for Lead Gen Pro deployments.

Run before deploying or as an entrypoint smoke test:
    python scripts/validate_env.py

Exits with code 0 when required environment variables for the current
DEPLOYMENT_MODE are present, otherwise prints a clear report and exits 1.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List


MODE_PROFILES: Dict[str, Dict[str, List[str]]] = {
    "minimal": {
        "required": [],
        "recommended": ["EXA_API_KEY", "PERPLEXITY_API_KEY"],
    },
    "demo": {
        "required": [],
        "recommended": ["EXA_API_KEY", "PERPLEXITY_API_KEY", "ANTHROPIC_API_KEY"],
    },
    "production": {
        "required": [
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "TWILIO_ACCOUNT_SID",
            "TWILIO_AUTH_TOKEN",
            "TWILIO_FROM_NUMBER",
            "SENDGRID_API_KEY",
            "SENDGRID_FROM_EMAIL",
        ],
        "recommended": [
            "EXA_API_KEY",
            "PERPLEXITY_API_KEY",
            "APOLLO_API_KEY",
            "GOOGLE_ADS_DEVELOPER_TOKEN",
            "GOOGLE_ADS_CUSTOMER_ID",
            "GOOGLE_ADS_REFRESH_TOKEN",
            "META_ACCESS_TOKEN",
            "META_AD_ACCOUNT_ID",
            "DATABASE_FILE",
            "API_KEY",
        ],
    },
}


def validate(mode: str | None = None) -> bool:
    mode = mode or os.getenv("DEPLOYMENT_MODE", "demo").lower()
    if mode not in MODE_PROFILES:
        print(f"Unknown DEPLOYMENT_MODE '{mode}'. Use one of: {', '.join(MODE_PROFILES)}")
        return False

    profile = MODE_PROFILES[mode]
    missing_required = [k for k in profile["required"] if not os.getenv(k)]
    missing_recommended = [k for k in profile["recommended"] if not os.getenv(k)]

    print(f"Deployment mode: {mode}")
    if missing_required:
        print("\nMissing required environment variables:")
        for k in missing_required:
            print(f"  - {k}")
    if missing_recommended:
        print("\nMissing recommended environment variables:")
        for k in missing_recommended:
            print(f"  - {k}")
    if not missing_required and not missing_recommended:
        print("All checked environment variables are present.")
        return True
    if missing_required:
        print("\nDeployment blocked: required variables missing.")
        return False
    print("\nDeployment allowed with reduced capability.")
    return True


if __name__ == "__main__":
    ok = validate(sys.argv[1] if len(sys.argv) > 1 else None)
    sys.exit(0 if ok else 1)
