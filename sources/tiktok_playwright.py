"""
tiktok_playwright.py  --  OUR OWN TikTok scraper (no third-party scraping lib).

How it works (plain version):
  1. Open a real headless browser at TikTok's hashtag page, e.g.
     https://www.tiktok.com/tag/ootd
  2. As the page loads, TikTok's own code asks its servers for the list of
     videos (with views/likes/dates). We quietly LISTEN for those responses and
     grab the JSON -- the exact same data the website itself uses.
  3. We scroll a few times to make it load more videos.
  4. We convert each video into our standard shape.

Reality check: TikTok fights scraping. Sometimes you'll get a captcha or empty
results. When that happens this returns what it has (maybe nothing) and the rest
of the system keeps working. Run with BROWSER_HEADLESS=0 to watch what happens.
"""

import os
import time

# Fashion hashtags to scan (kept clothing-focused). Override with TIKTOK_HASHTAGS.
# More hashtags = more surface area = more fresh videos survive the week cap.
HASHTAGS = [h.strip() for h in os.environ.get(
    "TIKTOK_HASHTAGS",
    "ootd,outfit,outfitinspo,outfitideas,fashiontiktok,fashion,thriftflip,"
    "streetwear,grwm,y2kfashion,fitcheck,summeroutfit"
).split(",") if h.strip()]

# How many videos to try to pull per scan (more = more trustworthy trends).
SCRAPE_LIMIT = int(os.environ.get("SCRAPE_LIMIT", "150"))
# How many times to scroll each hashtag page to load more videos.
SCROLLS = int(os.environ.get("TIKTOK_SCROLLS", "8"))

# TikTok URLs that carry the video lists we want to capture.
_ITEM_LIST_MARKERS = ("/api/challenge/item_list", "/api/post/item_list",
                      "/api/search/general", "/api/recommend/item_list",
                      "/api/explore/item_list")


def _parse_item(item, source_tag=None):
    """Turn one TikTok video JSON object into our standard shape."""
    stats = item.get("stats") or item.get("statsV2") or {}
    author = item.get("author") or {}
    if isinstance(author, dict):
        uid = author.get("uniqueId") or author.get("unique_id") or ""
    else:
        uid = str(author)
    video = item.get("video") or {}
    # Prefer originCover (full-resolution first frame) so the vision model has
    # the most detail to read; fall back to the smaller thumbnails.
    cover = video.get("originCover") or video.get("cover") or video.get("dynamicCover")

    def num(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return 0

    return {
        "id": f"tiktok:{item.get('id')}",
        "platform": "tiktok",
        "author": f"@{uid}" if uid else None,
        "title": (item.get("desc") or "")[:200],
        "url": f"https://www.tiktok.com/@{uid}/video/{item.get('id')}",
        "image_url": cover,          # cover frame -> the watcher can analyze this
        "source_tag": source_tag,
        "post_time": float(item.get("createTime") or time.time()),
        "views": num(stats.get("playCount")),
        "likes": num(stats.get("diggCount")),
        "comments": num(stats.get("commentCount")),
        "shares": num(stats.get("shareCount")),
    }


def _scrape_tag(context, tag, want):
    """Open one hashtag page, capture the video-list JSON it loads."""
    import json
    captured = []

    page = context.new_page()

    def on_response(resp):
        url = resp.url
        if any(m in url for m in _ITEM_LIST_MARKERS):
            try:
                data = resp.json()
            except Exception:
                return
            items = data.get("itemList") or data.get("item_list") or []
            for it in items:
                captured.append(it)

    page.on("response", on_response)

    try:
        page.goto(f"https://www.tiktok.com/tag/{tag}", timeout=30000,
                  wait_until="domcontentloaded")
        # Scroll to trigger more loads.
        for _ in range(SCROLLS):
            if len(captured) >= want:
                break
            page.mouse.wheel(0, 3000)
            page.wait_for_timeout(1500)
    except Exception as e:
        print(f"  [tiktok] page load issue for #{tag}: {e}")

    # Fallback: if listening caught nothing, try the data baked into the HTML.
    if not captured:
        try:
            html_state = page.evaluate(
                "() => { const el = document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__');"
                " return el ? el.textContent : null; }"
            )
            if html_state:
                blob = json.loads(html_state)
                scope = blob.get("__DEFAULT_SCOPE__", {})
                item_module = (scope.get("webapp.video-detail", {}) or {})
                # ItemModule lives under different keys depending on page; scan broadly.
                for v in scope.values():
                    if isinstance(v, dict) and "itemList" in v:
                        captured.extend(v["itemList"])
        except Exception as e:
            print(f"  [tiktok] HTML fallback failed for #{tag}: {e}")

    page.close()
    return [_parse_item(it, source_tag=tag) for it in captured[:want]]


def fetch(limit=None):
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:
        print("  [tiktok] playwright not installed -- skipping.")
        return []
    from . import browser_util as bu

    limit = limit or SCRAPE_LIMIT
    per_tag = max(10, limit // max(1, len(HASHTAGS)))
    results = []
    try:
        with sync_playwright() as pw:
            browser, context = bu.new_context(pw)
            for tag in HASHTAGS:
                if len(results) >= limit:
                    break
                got = _scrape_tag(context, tag, per_tag)
                print(f"  [tiktok] #{tag}: {len(got)} videos")
                results.extend(got)
            context.close()
            browser.close()
    except Exception as e:
        print(f"  [tiktok] scraper failed ({e}) -- skipping, system OK.")
        return []

    # De-dupe by id (same video can appear under multiple tags).
    seen, unique = set(), []
    for v in results:
        if v["id"] in seen:
            continue
        seen.add(v["id"])
        unique.append(v)
    return unique[:limit]
