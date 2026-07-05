"""Interactive CLI key setup wizard for Lead Gen Pro.

Usage:
    python scripts/key_wizard.py          # Interactive mode — asks for each key
    python scripts/key_wizard.py --check  # Check-only: reports which keys are set
"""

import argparse
import os
import re
import sys


ENV_TEMPLATE = """# ============================================================
# LEAD GEN PRO — Bring Your Own Keys
# ============================================================
# Search Providers (at least one required):
#   Exa:       https://dashboard.exa.ai
#   Perplexity: https://www.perplexity.ai/settings/api
#
EXA_API_KEY={exa}
PERPLEXITY_API_KEY={perplexity}

# API Authentication (optional — enable for production):
#   Generate a strong key: python -c "import secrets; print(secrets.token_urlsafe(32))"
#
API_KEY={api_key}

# LLM Scoring (optional — alternate via CometAPI):
#   Anthropic: https://console.anthropic.com
#   CometAPI:  https://www.cometapi.com (OpenAI-compatible, 500+ models)
#
ANTHROPIC_API_KEY={anthropic}
COMETAPI_API_KEY={cometapi}

# Lead Enrichment (optional):
#   Clearbit: https://dashboard.clearbit.com
#   Hunter:   https://hunter.io/api-keys
#
CLEARBIT_API_KEY={clearbit}
HUNTER_API_KEY={hunter}

# Stripe Billing (required for payment processing):
#   STRIPE_SECRET_KEY: https://dashboard.stripe.com/apikeys
#   STRIPE_WEBHOOK_SECRET: https://dashboard.stripe.com/webhooks (endpoint: /api/billing/webhook)
#   STRIPE_PRICE_*: Price IDs from Stripe Dashboard > Products
#
STRIPE_SECRET_KEY={stripe_secret}
STRIPE_WEBHOOK_SECRET={stripe_webhook}
STRIPE_PRICE_STARTER={price_starter}
STRIPE_PRICE_GROWTH={price_growth}
STRIPE_PRICE_PRO={price_pro}
STRIPE_PRICE_ENTERPRISE={price_enterprise}
"""


def parse_env(path: str) -> dict[str, str]:
    env: dict[str, str] = {}
    if not os.path.exists(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            env[key.strip()] = val.strip()
    return env


def key_display(val: str) -> str:
    if not val:
        return "(not set)"
    if len(val) <= 12:
        return val
    return val[:8] + "..." + val[-4:]


def validate_key(name: str, value: str) -> str | None:
    if not value:
        return None
    if name == "EXA_API_KEY":
        if not re.match(r"^[a-zA-Z0-9_-]{8,128}$", value):
            return "Exa keys are alphanumeric, 8–128 chars"
    elif name == "PERPLEXITY_API_KEY":
        if not re.match(r"^pplx-[a-zA-Z0-9_-]{16,}$", value):
            return "Perplexity keys start with pplx-"
    elif name == "STRIPE_SECRET_KEY":
        if not re.match(r"^sk_(live|test)_[a-zA-Z0-9]+$", value):
            return "Stripe keys start with sk_live_ or sk_test_"
    elif name == "ANTHROPIC_API_KEY":
        if not re.match(r"^sk-ant-[a-zA-Z0-9]{16,}$", value):
            return "Anthropic keys start with sk-ant-"
    elif name == "STRIPE_WEBHOOK_SECRET":
        if not re.match(r"^whsec_[a-zA-Z0-9]+$", value):
            return "Stripe webhook secrets start with whsec_"
    return None


KEY_DEFS = [
    ("EXA_API_KEY", "Exa Search", "https://dashboard.exa.ai"),
    ("PERPLEXITY_API_KEY", "Perplexity Search", "https://www.perplexity.ai/settings/api"),
    ("API_KEY", "API Auth (optional)", "Generate with: python -c \"import secrets; print(secrets.token_urlsafe(32))\""),
    ("ANTHROPIC_API_KEY", "Anthropic LLM (optional)", "https://console.anthropic.com"),
    ("COMETAPI_API_KEY", "CometAPI LLM (optional)", "https://www.cometapi.com"),
    ("CLEARBIT_API_KEY", "Clearbit Enrichment (optional)", "https://dashboard.clearbit.com"),
    ("HUNTER_API_KEY", "Hunter Enrichment (optional)", "https://hunter.io/api-keys"),
    ("STRIPE_SECRET_KEY", "Stripe Secret Key", "https://dashboard.stripe.com/apikeys"),
    ("STRIPE_WEBHOOK_SECRET", "Stripe Webhook Secret", "https://dashboard.stripe.com/webhooks"),
]

ENV_KEYS = [k for k, _, _ in KEY_DEFS]
ENV_DEFAULTS = {
    "STRIPE_PRICE_STARTER": "price_starter",
    "STRIPE_PRICE_GROWTH": "price_growth",
    "STRIPE_PRICE_PRO": "price_pro",
    "STRIPE_PRICE_ENTERPRISE": "price_enterprise",
}


def cmd_check(env: dict[str, str]) -> None:
    print("Key Status Report")
    print("=" * 60)
    set_count = 0
    for key, label, source in KEY_DEFS:
        val = env.get(key, "")
        status = "[set]" if val else "[missing]"
        hint = f"  ({source})" if not val else key_display(val)
        print(f"  {label:30s} {status:10s} {hint}")
        if val:
            set_count += 1

    for key, default in ENV_DEFAULTS.items():
        val = env.get(key, "")
        if val:
            set_count += 1

    print()
    print(f"{set_count} of {len(KEY_DEFS)} primary keys set")
    print(f"  File: {env_path}")


def cmd_interactive(env: dict[str, str]) -> None:
    print("Key Setup Wizard")
    print("=" * 60)
    print("Enter values for each key. Leave blank to skip / keep current.")
    print()

    updated = dict(env)

    for key, label, source in KEY_DEFS:
        current = env.get(key, "")
        display = f" [{key_display(current)}]" if current else ""
        prompt = f"  {label:30s} ({source}){display}: "

        val = input(prompt).strip()
        if val:
            warn = validate_key(key, val)
            if warn:
                print(f"    ⚠ {warn}")
                again = input("    Try again? (enter new value or leave blank): ").strip()
                if again:
                    val = again
                else:
                    val = current
            updated[key] = val
        elif not current:
            updated[key] = ""

    for key, default in ENV_DEFAULTS.items():
        current = env.get(key, "")
        if not current:
            val = input(f"  {key:30s} [{default}]: ").strip()
            updated[key] = val or default

    out = ENV_TEMPLATE.format(
        exa=updated.get("EXA_API_KEY", ""),
        perplexity=updated.get("PERPLEXITY_API_KEY", ""),
        api_key=updated.get("API_KEY", ""),
        anthropic=updated.get("ANTHROPIC_API_KEY", ""),
        cometapi=updated.get("COMETAPI_API_KEY", ""),
        clearbit=updated.get("CLEARBIT_API_KEY", ""),
        hunter=updated.get("HUNTER_API_KEY", ""),
        stripe_secret=updated.get("STRIPE_SECRET_KEY", ""),
        stripe_webhook=updated.get("STRIPE_WEBHOOK_SECRET", ""),
        price_starter=updated.get("STRIPE_PRICE_STARTER", "price_starter"),
        price_growth=updated.get("STRIPE_PRICE_GROWTH", "price_growth"),
        price_pro=updated.get("STRIPE_PRICE_PRO", "price_pro"),
        price_enterprise=updated.get("STRIPE_PRICE_ENTERPRISE", "price_enterprise"),
    )

    with open(env_path, "w", encoding="utf-8") as f:
        f.write(out)

    print()
    print(f"Written → {env_path}")
    print()
    print("Your .env is ready. Run `docker compose up --build` or `python run.py`")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Lead Gen Pro — Key Setup Wizard")
    parser.add_argument("--check", action="store_true", help="Check-only: report which keys are set")
    args = parser.parse_args()

    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    env = parse_env(env_path)

    if args.check:
        cmd_check(env)
    else:
        cmd_interactive(env)
