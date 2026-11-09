"""
instagram_accounts.py  --  Scrape specific fashionable creators' recent posts.

Instead of random hashtag posts (mostly small accounts, few likes), this pulls
the latest posts from a CURATED list of fashionable young creators. Their posts
naturally have high likes, real people posing, and on-trend looks -- exactly the
"fashionable people 16-26" signal we want.

Accounts come from IG_ACCOUNTS (comma-separated handles), set per style by the
caller from accounts.py. Uses Apify's instagram-scraper actor.
"""

import os

from .instagram_apify import _post, _get, _parse, TOKEN, API

ACTOR = os.environ.get("ACCOUNTS_ACTOR", "apify~instagram-scraper")
ACCOUNTS = [a.strip().lstrip("@") for a in os.environ.get("IG_ACCOUNTS", "").split(",") if a.strip()]
PER_ACCOUNT = int(os.environ.get("RESULTS_PER_ACCOUNT", "12"))


def fetch(limit=None):
    import time
    if not TOKEN:
        print("  [ig-accounts] APIFY_TOKEN not set -- skipping.")
        return []
    if not ACCOUNTS:
        print("  [ig-accounts] no IG_ACCOUNTS for this style -- skipping. (Add handles in accounts.py.)")
        return []

    urls = [f"https://www.instagram.com/{a}/" for a in ACCOUNTS]
    body = {"directUrls": urls, "resultsType": "posts", "resultsLimit": PER_ACCOUNT,
            "addParentData": False}
    try:
        run = _post(f"{API}/acts/{ACTOR}/runs?token={TOKEN}", body)["data"]
    except Exception as e:
        print(f"  [ig-accounts] could not start run ({e})")
        return []

    run_id, dataset = run["id"], run["defaultDatasetId"]
    print(f"  [ig-accounts] run {run_id} for {len(ACCOUNTS)} accounts ({PER_ACCOUNT} posts each)...")
    deadline = time.time() + 900
    status = run["status"]
    while status in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(10)
        try:
            status = _get(f"{API}/actor-runs/{run_id}?token={TOKEN}")["data"]["status"]
        except Exception:
            break
    print(f"  [ig-accounts] run status: {status}")

    try:
        items = _get(f"{API}/datasets/{dataset}/items?token={TOKEN}&clean=true&format=json")
    except Exception as e:
        print(f"  [ig-accounts] could not fetch items ({e})")
        return []

    out, seen = [], set()
    for it in items:
        p = _parse(it)
        if p and p["id"] not in seen:
            seen.add(p["id"])
            out.append(p)
    print(f"  [ig-accounts] got {len(out)} photo posts from {len(ACCOUNTS)} accounts")
    return out[:limit] if limit else out
