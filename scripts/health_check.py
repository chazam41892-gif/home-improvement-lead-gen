import json
import sys
import urllib.request
import urllib.error


def check_health(host: str) -> int:
    url = f"{host.rstrip('/')}/health"
    try:
        resp = urllib.request.urlopen(url, timeout=10)
        data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"ERROR: HTTP {e.code} {e.reason}")
        return 1
    except urllib.error.URLError as e:
        print(f"ERROR: {e.reason}")
        return 1
    except json.JSONDecodeError as e:
        print(f"ERROR: invalid JSON — {e}")
        return 1

    status = data.get("status", "unknown")
    version = data.get("version", "?")
    uptime = data.get("uptime_sec", 0)
    auth = data.get("auth_enabled", False)
    stripe = data.get("stripe_configured", False)
    exa = data.get("exa_configured", False)
    perplexity = data.get("perplexity_configured", False)
    leads = data.get("total_leads", 0)
    missing = data.get("missing_config", {})

    print(f"Status:             {status}")
    print(f"Version:            {version}")
    print(f"Uptime (sec):       {uptime}")
    print(f"Auth enabled:       {auth}")
    print(f"Stripe configured:  {stripe}")
    print(f"Exa configured:     {exa}")
    print(f"Perplexity config:  {perplexity}")
    print(f"Total leads:        {leads}")
    if missing:
        print(f"Missing config ({len(missing)}):")
        for k, v in missing.items():
            print(f"  - {k}: {v}")

    if status == "ok":
        return 0
    print(f"WARNING: status is '{status}' (expected 'ok')")
    return 1


def main():
    host = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080"
    sys.exit(check_health(host))


if __name__ == "__main__":
    main()
