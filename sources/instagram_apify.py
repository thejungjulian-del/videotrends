"""
instagram_apify.py  --  Scrape Instagram at SCALE via the Apify API.

This is the paid, reliable path: Apify runs a managed Instagram hashtag scraper
in the cloud and hands back thousands of posts as clean JSON (likes, caption,
image, date) -- no throwaway account, no browser, no bans on your side.

Needs in .env:
  APIFY_TOKEN = your Apify API token (apify.com -> Settings -> Integrations)
Optional:
  APIFY_ACTOR = actor slug (default apify~instagram-hashtag-scraper)
"""

import json
import os
import time
import urllib.parse
import urllib.request

TOKEN = os.environ.get("APIFY_TOKEN", "")
ACTOR = os.environ.get("APIFY_ACTOR", "apify~instagram-hashtag-scraper")
HASHTAGS = [h.strip() for h in os.environ.get("IG_HASHTAGS", "streetwear").split(",") if h.strip()]
SCRAPE_LIMIT = int(os.environ.get("SCRAPE_LIMIT", "1000"))
API = "https://api.apify.com/v2"


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def _parse(item):
    """Map an Apify Instagram post to our standard shape (photos only)."""
    if item.get("type") == "Video":   # photos / carousels only
        return None
    code = item.get("shortCode") or item.get("shortcode") or item.get("id")
    if not code:
        return None
    img = item.get("displayUrl") or (item.get("images") or [None])[0]
    if not img:
        return None
    ts = item.get("timestamp")
    try:
        from datetime import datetime
        post_time = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S.%fZ").timestamp()
    except Exception:
        try:
            post_time = float(ts)
        except (TypeError, ValueError):
            post_time = time.time()
    return {
        "id": f"instagram:{code}",
        "platform": "instagram",
        "author": f"@{item.get('ownerUsername')}" if item.get("ownerUsername") else None,
        "title": (item.get("caption") or "")[:200],
        "url": item.get("url") or f"https://www.instagram.com/p/{code}/",
        "image_url": img,
        "source_tag": (item.get("hashtags") or [None])[0],
        "post_time": float(post_time),
        "views": max(0, int(item.get("videoViewCount") or 0)),
        "likes": max(0, int(item.get("likesCount") or 0)),   # -1 = hidden -> 0
        "comments": max(0, int(item.get("commentsCount") or 0)),
        "shares": 0,
    }


def fetch(limit=None):
    if not TOKEN:
        print("  [apify] APIFY_TOKEN not set -- skipping. (Add it to .env; see README.)")
        return []
    want = limit or SCRAPE_LIMIT
    body = {"hashtags": HASHTAGS, "resultsType": "posts", "resultsLimit": want}
    try:
        run = _post(f"{API}/acts/{ACTOR}/runs?token={TOKEN}", body)["data"]
    except Exception as e:
        print(f"  [apify] could not start run ({e})")
        return []

    run_id, dataset = run["id"], run["defaultDatasetId"]
    print(f"  [apify] run {run_id} started for {HASHTAGS} (up to {want} posts)...")

    # Poll until the cloud run finishes (cap the wait so we never hang forever).
    deadline = time.time() + 900  # 15 min cap
    status = run["status"]
    while status in ("READY", "RUNNING") and time.time() < deadline:
        time.sleep(10)
        try:
            status = _get(f"{API}/actor-runs/{run_id}?token={TOKEN}")["data"]["status"]
        except Exception:
            break
    print(f"  [apify] run status: {status}")

    try:
        items = _get(f"{API}/datasets/{dataset}/items?token={TOKEN}&clean=true&format=json")
    except Exception as e:
        print(f"  [apify] could not fetch items ({e})")
        return []

    out, seen = [], set()
    for it in items:
        p = _parse(it)
        if p and p["id"] not in seen:
            seen.add(p["id"])
            out.append(p)
    print(f"  [apify] got {len(out)} photo posts")
    return out
